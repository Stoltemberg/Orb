"""
orbwalker/engine.py — Motor do orbwalker baseado DIRETAMENTE no auto-kite-bot.

Princípio: funcionar PRIMEIRO como o auto-kite-bot (A+click cego),
e DEPOIS adicionar visão computacional para targeting inteligente.

O loop é idêntico ao auto-kite-bot:
    1. Se nextAttack < now → A + Left Click (ataca)
    2. Senão, se nextMove < now → Right Click (anda)
    3. Sleep tick_rate/2

A visão roda em thread SEPARADA e só atualiza a posição do cursor
se detectar um alvo. Se não detectar, o orbwalker funciona cego.
"""
import time
import ctypes
import ctypes.wintypes
import threading
import random
import logging
import psutil

from input.input_simulator import Keyboard, Mouse, DIK_A
from riot_api import RiotAPI
from champion_data import ChampionData
from humanizer import Humanizer

logger = logging.getLogger("ExternalOrbwalker.Engine")

user32 = ctypes.windll.user32


class OrbwalkerEngine:
    """
    Orbwalker funcional — réplica direta do auto-kite-bot com visão opcional.
    """

    def __init__(self, riot_api: RiotAPI, champion_data: ChampionData):
        self.riot_api = riot_api
        self.champ = champion_data

        # ── Timing (copiados do auto-kite-bot) ──
        self.WindupBuffer = 1.0 / 15.0       # ~66ms safety
        self.MinInputDelay = 1.0 / 30.0      # ~33ms entre inputs
        self.OrderTickRate = 1.0 / 30.0       # ~33ms tick rate
        self.PingOffsetMs = 0

        # ── State ──
        self.nextInput = 0.0
        self.nextMove = 0.0
        self.nextAttack = 0.0

        self.active = False          # Se o orbwalker está ativado (tecla segurada)
        self.mode = "combo"          # combo | lasthit | laneclear | harass
        self._running = False
        self._thread = None
        self._has_process = False

        # ── Vision targeting (opcional, preenchido pela thread de visão) ──
        self._vision_lock = threading.Lock()
        self._vision_target = None    # (screen_x, screen_y) ou None
        self._vision_mode = "none"    # "champion", "minion", ou "none"
        self.use_vision = False       # SÓ ativar quando visão está calibrada!

        # ── Scripts de Campeão ──
        self.script = None           # Instância de BaseScript

        # ── Stats ──
        self.attacks = 0
        self.moves = 0
        
        self.humanizer = Humanizer()

    # ═══════════════════════════════════════════
    #  TIMING — Exatamente como auto-kite-bot
    # ═══════════════════════════════════════════

    def get_seconds_per_attack(self) -> float:
        """Tempo de um ciclo completo de auto-attack."""
        as_val = self.riot_api.attack_speed
        if as_val <= 0:
            return 1.0
        return 1.0 / as_val

    def get_windup_duration(self) -> float:
        """Duração do windup — fórmula do auto-kite-bot."""
        spa = self.get_seconds_per_attack()
        return (((spa * self.champ.attack_delay_percent) - self.champ.attack_cast_time)
                * self.champ.attack_delay_scaling) + self.champ.attack_cast_time

    def get_buffered_windup_duration(self) -> float:
        """Windup + buffer + ping."""
        ping_s = self.PingOffsetMs / 1000.0
        return self.get_windup_duration() + self.WindupBuffer + ping_s

    # ═══════════════════════════════════════════
    #  VISION TARGET (thread-safe, set pela thread de visão)
    # ═══════════════════════════════════════════

    def set_vision_target(self, screen_x: int, screen_y: int, target_type: str = "champion"):
        """Chamado pela thread de visão quando encontra um alvo."""
        with self._vision_lock:
            self._vision_target = (screen_x, screen_y)
            self._vision_mode = target_type

    def clear_vision_target(self):
        """Limpa o alvo — chamado quando visão não encontra nada."""
        with self._vision_lock:
            self._vision_target = None
            self._vision_mode = "none"

    def get_vision_target(self):
        """Retorna o target atual da visão."""
        with self._vision_lock:
            return self._vision_target, self._vision_mode

    # ═══════════════════════════════════════════
    #  LIFECYCLE
    # ═══════════════════════════════════════════

    def start(self):
        """Inicia as threads do orbwalker."""
        self._running = True

        # Thread de detecção do processo
        t_proc = threading.Thread(target=self._check_process_loop, daemon=True)
        t_proc.start()

        # Thread principal do orbwalk
        self._thread = threading.Thread(target=self._orb_walk_loop, daemon=True)
        self._thread.start()

        logger.info("Orbwalker engine started")

    def stop(self):
        """Para o engine."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Orbwalker engine stopped")

    # ═══════════════════════════════════════════
    #  PROCESS DETECTION (do auto-kite-bot)
    # ═══════════════════════════════════════════

    def _check_process_loop(self):
        """Monitora se o League of Legends está aberto."""
        while self._running:
            try:
                found = False
                for proc in psutil.process_iter(['name']):
                    name = proc.info.get('name', '')
                    if name and 'League of Legends' in name:
                        found = True
                        break

                if found and not self._has_process:
                    self._has_process = True
                    logger.info("League of Legends detected!")
                elif not found and self._has_process:
                    self._has_process = False
                    logger.info("League of Legends closed.")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
            time.sleep(2)

    def _is_league_foreground(self) -> bool:
        """Verifica se a janela do LoL está em foco."""
        fg = user32.GetForegroundWindow()
        if fg:
            length = user32.GetWindowTextLengthW(fg)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(fg, buf, length + 1)
            return "League of Legends" in buf.value
        return False

    # ═══════════════════════════════════════════
    #  MAIN ORB WALK LOOP — Réplica do auto-kite-bot
    # ═══════════════════════════════════════════

    def _orb_walk_loop(self):
        """
        Loop principal do orbwalker — idêntico ao auto-kite-bot.

        A diferença é que, se a visão detectou um alvo, movemos o cursor
        para lá ANTES de atacar. Se não detectou, atacamos cego (A+click
        no cursor atual, que ataca o inimigo mais perto do cursor).
        """
        while self._running:
            # ── Inativo? Dormir. ──
            if not self._has_process or not self.active:
                time.sleep(0.001)
                continue

            # ── Janela do LoL não está em foco? Ignorar. ──
            if not self._is_league_foreground():
                time.sleep(0.001)
                continue

            now = time.perf_counter()

            # ════════ EXECUTAR SCRIPT DO CAMPEÃO (Combo) ════════
            # Executamos fora do timer de auto-attack para habilidades de baixo CD (ex: E da Cassio)
            if self.script and self.active:
                vision_target, vision_type = self.get_vision_target()
                target_mock = None
                
                # Sincronizar cursor se houver alvo e visão ativa
                # [Modificado: Teleporte do cursor foi desativado a pedido do usuário]
                # Para evitar flicking e perda de controle do personagem, os casts
                # ocorrerão onde o mouse físico do usuário estivar no momento.
                if self.use_vision and vision_target:
                    from vision.entity_classifier import DetectedEntity, EntityType
                    target_mock = DetectedEntity(
                        entity_type=EntityType.CHAMPION if vision_type == "champion" else EntityType.MINION,
                        screen_x=vision_target[0],
                        screen_y=vision_target[1],
                        health_bar=None, confidence=1.0, has_level=False
                    )

                # Executar script
                casted = self.script.execute(target_mock, self.mode)
                
                if casted:
                    # Se conjurou algo com cast time (Q), resetamos os timers e esperamos
                    self.reset_attack_timer()
                    self.nextInput = now + self.MinInputDelay
                    time.sleep(self.OrderTickRate / 2)
                    continue

            # ════════ ATACAR PRIMEIRO ════════
            # Nunca atrase o ataque por causa do rate-limit de movimento.
            # Nota: Somente ataca se o script do campeão permitir (ex: Cassio prefere não AA)
            allow_aa = self.script.allow_aa if self.script else True

            if allow_aa and self.nextAttack < now:
                self.nextInput = now + self.MinInputDelay

                # ── Se a visão está ativa E encontrou um alvo, mover cursor ──
                # [Modificado: Teleporte do mouse durante ataques removido!]
                # O usuário precisa manter o mouse físico no quadrante geral do inimigo e 
                # ter a opção "Atacar no Movimento no Cursor" ligada nas config do lol.
                if self.use_vision:
                    vision_target, vision_type = self.get_vision_target()

                # ── Attack input: A + Left Click (idêntico ao auto-kite-bot) ──
                # Usamos delays mínimos (1-3ms) para não prender o mouse na cara do inimigo
                Keyboard.press_key(DIK_A, min_delay=0.001, max_delay=0.003)
                Mouse.mouse_click(Mouse.Buttons.Left, min_delay=0.001, max_delay=0.003)

                attackTime = time.perf_counter()

                self.nextMove = attackTime + self.get_buffered_windup_duration()

                # Humanizer
                humanizer_delay = random.uniform(0.005, 0.015)
                self.nextAttack = attackTime + self.get_seconds_per_attack() + humanizer_delay

                self.attacks += 1

            # ════════ ANDAR DEPOIS ════════
            # Usamos IF em vez de ELIF para permitir movimento fluido mesmo se o attack falhou/foi pulado
            if self.nextMove < now and self.nextInput < now:
                self.nextInput = now + self.MinInputDelay 
                Mouse.mouse_click(Mouse.Buttons.Right, min_delay=0.005, max_delay=0.015)
                self.moves += 1

            # ── Sleep — mesmo timing do auto-kite-bot ──
            time.sleep(self.OrderTickRate / 2)

    def reset_attack_timer(self):
        """Reset ao usar skill que cancela auto (Q/W/E/R)."""
        now = time.perf_counter()
        if self.nextAttack > now + 0.05:
            self.nextAttack = now + 0.05
            self.nextMove = now + 0.05
