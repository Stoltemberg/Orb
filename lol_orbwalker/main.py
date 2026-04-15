"""
main.py — External Orbwalker funcional.
Baseado diretamente na arquitetura do auto-kite-bot.

Funciona em 2 camadas:
    Camada 1 (obrigatória): Orbwalker cego (A+click / R-click com timing perfeito)
    Camada 2 (opcional):    Visão computacional para targeting inteligente
"""
import time
import os
import sys
import ctypes
import threading
import logging
import keyboard

from riot_api import RiotAPI
from champion_data import ChampionData
from orbwalker.engine import OrbwalkerEngine
from scripts import get_script

# ── Opcional: visão ──
VISION_AVAILABLE = False
try:
    from screen_capture import ScreenCapture
    from vision.health_bar_detector import HealthBarDetector
    from vision.entity_classifier import EntityClassifier, EntityType
    VISION_AVAILABLE = True
except ImportError as e:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("ExternalOrbwalker")

import cv2
import random

def convert_entity_to_yolo_class(entity_type) -> int:
    """Mapeia EntityType para as classes da YOLO do nosso dataset"""
    if entity_type == EntityType.CHAMPION: return 0
    if entity_type in (EntityType.MINION, EntityType.MINION_SIEGE): return 1
    if entity_type == EntityType.TURRET: return 2
    if entity_type == EntityType.MONSTER: return 4
    return 1  # Default fallback

def save_training_data_in_background(frame, entities, width, height, base_dir=None):
    """
    Salva a imagem bruta na inbox/ para ser anotada pelo auto-labeler (best.pt).
    NÃO gera labels estimadas — o auto-labeler usa o modelo treinado para maior precisão.
    """
    try:
        # Só captura se houver pelo menos 1 entidade detectada na tela
        if not entities:
            return

        if base_dir is None:
            from config import BASE_DIR
            base_dir = BASE_DIR

        inbox_dir = os.path.join(base_dir, "dataset", "inbox")
        os.makedirs(inbox_dir, exist_ok=True)

        timestamp = time.time()
        img_name = os.path.join(inbox_dir, f"play_{timestamp:.2f}.jpg")

        cv2.imwrite(img_name, frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
    except Exception:
        pass


BANNER = """
 ╔═══════════════════════════════════════════════╗
 ║   EXTERNAL ORBWALKER — No Memory Reading      ║
 ║   Based on Auto-Kite Bot architecture          ║
 ╚═══════════════════════════════════════════════╝
"""


class ExternalOrbwalker:
    def __init__(self):
        self.riot_api = RiotAPI()
        self.champion_data = ChampionData()
        self.engine = None
        self.running = False

        # ── Vision thread ──
        self.vision_enabled = VISION_AVAILABLE
        self.vision_thread = None

        # ── Target Selector (com filtro de attack range) ──
        from orbwalker.target_selector import TargetSelector
        self.target_selector = TargetSelector()

        # ── Key states ──
        self._combo_held = False
        self._lasthit_held = False
        self._laneclear_held = False
        self._harass_held = False
        self._keyboard_hook = None  # Referência ao hook do bot (para unhook preciso)

        # ── Módulos Extras ──
        from auto_summoner import AutoSummoner
        self.auto_summoner = AutoSummoner(self.riot_api)

    def start(self, blocking=True):
        print(BANNER)

        # ═══ 1. Conectar à Riot API ═══
        self.riot_api.start()
        logger.info("Aguardando League of Legends...")

        while not self.riot_api.connected:
            time.sleep(0.5)
        logger.info("✓ Conectado à API do jogo!")
        
        # ═══ Iniciar Auto-Summoner ═══
        self.auto_summoner.start()

        # ═══ 2. Identificar campeão ═══
        logger.info("Identificando campeão...")
        while not self.riot_api.raw_champion_name:
            time.sleep(0.5)

        champ = self.riot_api.champion_name
        raw = self.riot_api.raw_champion_name
        logger.info(f"✓ Campeão: {champ} ({raw})")

        # ═══ 3. Carregar dados do CommunityDragon ═══
        if not self.champion_data.load(raw):
            logger.error(f"Falha ao carregar dados de {raw}. Usando defaults.")

        # ═══ 4. Criar e iniciar engine ═══
        self.engine = OrbwalkerEngine(self.riot_api, self.champion_data)
        
        # Ativar visão no engine e carregar script do campeão
        self.engine.use_vision = True 
        # self.engine.script = get_script(raw, self.riot_api, self.champion_data)  # Scripts desativados
        self.engine.script = None
        
        # Permitir que as threads rodem antes de iniciá-las!
        self.running = True
        
        self.engine.start()

        # ═══ 5. Iniciar visão (opcional, thread separada) ═══
        if self.vision_enabled:
            self.vision_thread = threading.Thread(target=self._vision_loop, daemon=True)
            self.vision_thread.start()
            logger.info("✓ Visão computacional ativada (thread separada)")
        else:
            logger.info("⚠ Visão computacional não disponível (instale opencv-python + dxcam)")
            logger.info("  O orbwalker vai funcionar no modo cego (A+click no cursor)")

        # ═══ 6. Registrar hotkeys ═══
        try:
            self._keyboard_hook = keyboard.hook(self._on_key_event)
        except Exception as e:
            logger.error(f"Keyboard hook falhou: {e}")
            logger.error("Execute como Administrador!")
            self.running = False
            return


        # ═══ 7. Exibir controles ═══
        print()
        logger.info("═" * 50)
        logger.info("ORBWALKER PRONTO!")
        logger.info("  [SPACE] Segurar = Combo (só campeões)")
        logger.info("  [X]     Segurar = Last Hit (só minions matáveis)")
        logger.info("  [V]     Segurar = Lane Clear (tudo)")
        logger.info("  [C]     Segurar = Harass (last hit + poke campeão)")
        logger.info("  [Ctrl+C] = Sair")
        logger.info("═" * 50)
        print()

        # ═══ 8. Status loop ═══
        if blocking:
            self._status_loop()

    def _on_key_event(self, event):
        """Idêntico ao auto-kite-bot: ativa/desativa o orbwalker."""
        if not self.engine:
            return

        key = getattr(event, 'name', '').lower()

        # ── SPACE = Combo ──
        if key == 'space':
            if event.event_type == keyboard.KEY_DOWN:
                if not self._combo_held:
                    self._combo_held = True
                    self.engine.active = True
                    self.engine.mode = "combo"
            elif event.event_type == keyboard.KEY_UP:
                self._combo_held = False
                if self.engine.mode == "combo":
                    self.engine.active = False
                    self.engine.clear_vision_target()

        # ── X = Last Hit ──
        elif key == 'x':
            if event.event_type == keyboard.KEY_DOWN:
                if not self._lasthit_held:
                    self._lasthit_held = True
                    self.engine.active = True
                    self.engine.mode = "lasthit"
            elif event.event_type == keyboard.KEY_UP:
                self._lasthit_held = False
                if self.engine.mode == "lasthit":
                    self.engine.active = False
                    self.engine.clear_vision_target()

        # ── V = Lane Clear ──
        elif key == 'v':
            if event.event_type == keyboard.KEY_DOWN:
                if not self._laneclear_held:
                    self._laneclear_held = True
                    self.engine.active = True
                    self.engine.mode = "laneclear"
            elif event.event_type == keyboard.KEY_UP:
                self._laneclear_held = False
                if self.engine.mode == "laneclear":
                    self.engine.active = False
                    self.engine.clear_vision_target()

        # ── C = Harass (Last Hit + Poke Campeão) ──
        elif key == 'c':
            if event.event_type == keyboard.KEY_DOWN:
                if not self._harass_held:
                    self._harass_held = True
                    self.engine.active = True
                    self.engine.mode = "harass"
            elif event.event_type == keyboard.KEY_UP:
                self._harass_held = False
                if self.engine.mode == "harass":
                    self.engine.active = False
                    self.engine.clear_vision_target()

        # ── Q/W/E/R = Tracking de Cooldown + Reset attack timer (animation cancel) ──
        if key in ('q', 'w', 'e', 'r'):
            if event.name and self.engine.script:
                 self.engine.script.on_key_event(key, event.event_type)
            
            if event.event_type == keyboard.KEY_DOWN and self.engine.active:
                self.engine.reset_attack_timer()

    # ═══════════════════════════════════════════
    #  VISION LOOP — Thread separada, NÃO bloqueia o orbwalker
    # ═══════════════════════════════════════════

    def _vision_loop(self):
        """
        Thread de visão que detecta entidades e atualiza o target do engine.
        Se falhar ou não encontrar nada, o orbwalker continua funcionando cego.
        RESILIENTE: erros por frame são ignorados, thread só morre em erro fatal.
        """
        import traceback

        capture = None
        try:
            capture = ScreenCapture(target_fps=60)
            capture.start()

            if not capture._started:
                logger.error("Vision: Screen capture falhou ao iniciar!")
                logger.info("Orbwalker continua no modo cego (A+click no cursor)")
                return

            screen_w, screen_h = capture.get_screen_size()
            detector = HealthBarDetector(screen_w, screen_h)
            classifier = EntityClassifier(screen_w, screen_h)
            
            # ── Integrando a Mente Neural (YOLO) ──
            from vision.yolo_detector import YOLODetector
            from config import VisionConfig
            yolo_detector = YOLODetector()

            logger.info(f"Vision thread OK @ {screen_w}x{screen_h}")

            error_count = 0
            frame_count = 0
            fps_timer = time.perf_counter()
            track_memory = {}  # Temporal memory {id: dict}
            next_track_id = 0

            while self.running:
                try:
                    # Só processa quando o orbwalker está ativo
                    if not self.engine or not self.engine.active:
                        if self.engine:
                            self.engine.clear_vision_target()
                        time.sleep(0.05)
                        continue

                    frame = capture.grab()
                    if frame is None:
                        time.sleep(0.01)
                        continue

                    frame_count += 1

                    # Pipeline Híbrido Unificado (OpenCV + YOLO + Tracking)
                    # 1) Propostas via OpenCV
                    health_bars = detector.detect(frame)
                    raw_cv_entities = classifier.classify(frame, health_bars)
                    
                    # 2) Temporal Tracking & Ambiguity Filter
                    import math
                    cv_entities = []
                    for ent in raw_cv_entities:
                        matched_id = None
                        best_dist = 40.0 # max euclidian pixel dist
                        for tid, tdata in list(track_memory.items()):
                            if frame_count - tdata['last_seen'] > 10:
                                del track_memory[tid]
                                continue
                            dist = math.hypot(ent.screen_x - tdata['x'], ent.screen_y - tdata['y'])
                            if dist < best_dist:
                                best_dist = dist
                                matched_id = tid
                        
                        if matched_id is not None:
                            # Herdar tracking passado se for campeao
                            if track_memory[matched_id]['type'] == EntityType.CHAMPION and track_memory[matched_id]['conf'] > 0.8:
                                ent.entity_type = EntityType.CHAMPION
                                ent.confidence = max(ent.confidence, track_memory[matched_id]['conf'])
                                ent.is_ambiguous = False
                            
                            track_memory[matched_id]['x'] = ent.screen_x
                            track_memory[matched_id]['y'] = ent.screen_y
                            track_memory[matched_id]['last_seen'] = frame_count
                            track_memory[matched_id]['type'] = ent.entity_type
                            track_memory[matched_id]['conf'] = ent.confidence
                            tid_to_use = matched_id
                        else:
                            tid_to_use = next_track_id
                            next_track_id += 1
                            track_memory[tid_to_use] = {
                                'x': ent.screen_x, 'y': ent.screen_y,
                                'type': ent.entity_type, 'conf': ent.confidence, 
                                'last_seen': frame_count
                            }
                        cv_entities.append(ent)
                    
                    # 3) Rodar YOLO apenas se houver ambiguidades graves (Reclassificador)
                    run_yolo = any(e.is_ambiguous for e in cv_entities)
                    
                    yolo_entities = []
                    if run_yolo and yolo_detector.available and VisionConfig.YOLO_ENABLED:
                        yolo_entities = yolo_detector.detect(frame)
                        
                    # 4) Fusão
                    entities = classifier.fuse_entities(cv_entities, yolo_entities)
                    
                    # Atualizar trackers pós-fusão
                    for ent in entities:
                        for tid, tdata in list(track_memory.items()):
                            dist = math.hypot(ent.screen_x - tdata['x'], ent.screen_y - tdata['y'])
                            if dist < 40:
                                track_memory[tid]['type'] = ent.entity_type
                                if ent.entity_type == EntityType.CHAMPION:
                                    track_memory[tid]['conf'] = max(track_memory[tid]['conf'], 0.90)

                    if not entities:
                        self.engine.clear_vision_target()
                        time.sleep(0.005)
                        continue

                    # ── SHADOW CAPTURE (Pseudo-labeling) ──
                    # Diminui a taxa de amostragem quando o YOLO já estiver treinado pra poupar desempenho.
                    prob = 0.01 if yolo_detector.available else 0.05
                    if self.engine.active and random.random() < prob:
                        save_thread = threading.Thread(
                            target=save_training_data_in_background,
                            args=(frame.copy(), entities, screen_w, screen_h),
                            daemon=True
                        )
                        save_thread.start()

                    # ── Selecionar alvo baseado no modo (com filtro de range) ──
                    mode = self.engine.mode

                    # Atualizar range em tempo real (itens como RFC mudam isso)
                    self.target_selector.update_attack_range(self.riot_api.attack_range)

                    target = None
                    if mode == "combo":
                        target = self.target_selector.select_combo(entities)
                    elif mode == "lasthit":
                        target = self.target_selector.select_lasthit(entities)
                    elif mode == "laneclear":
                        target = self.target_selector.select_laneclear(entities)
                    elif mode == "harass":
                        target = self.target_selector.select_harass(entities)

                    # ── Atualizar target no engine ──
                    if target:
                        self.engine.set_vision_target(
                            target.screen_x, target.screen_y,
                            target.entity_type.name.lower()
                        )
                    else:
                        self.engine.clear_vision_target()

                    # Log detalhado a cada 3 segundos
                    now = time.perf_counter()
                    if now - fps_timer >= 3.0:
                        vfps = frame_count / (now - fps_timer)

                        # ── DEBUG: Mostrar cada entidade detectada ──
                        logger.info(f"─── Vision Debug ─── FPS:{vfps:.1f} | Bars:{len(health_bars)} | Entities:{len(entities)}")
                        for i, e in enumerate(entities):
                            hb = e.health_bar
                            logger.info(
                                f"  [{i}] {e.entity_type.name:15s} | "
                                f"w={hb.width:3d}px h={hb.height:2d}px | "
                                f"pos=({hb.center_x:4d},{hb.center_y:4d}) | "
                                f"fill={hb.fill_ratio:.0%} | "
                                f"lvl={'YES' if e.has_level else 'no ':3s} | "
                                f"conf={e.confidence:.0%}"
                            )

                        frame_count = 0
                        fps_timer = now
                        error_count = 0

                except Exception as frame_err:
                    error_count += 1
                    if error_count <= 3:
                        logger.warning(f"Vision frame error ({error_count}): {frame_err}")
                    if error_count > 100:
                        logger.error("Vision: muitos erros seguidos. Tentando reconectar (Backoff de 5s)...")
                        time.sleep(5)
                        try:
                            if capture:
                                try:
                                    capture.stop()
                                except: pass
                            time.sleep(1)
                            capture = ScreenCapture(target_fps=60)
                            capture.start()
                            if capture._started:
                                screen_w, screen_h = capture.get_screen_size()
                                detector = HealthBarDetector(screen_w, screen_h)
                                classifier = EntityClassifier(screen_w, screen_h)
                                error_count = 0
                                logger.info("Vision: Thread recuperada com sucesso.")
                            else:
                                logger.error("Vision: Falha ao recriar captura.")
                        except Exception as rec_err:
                            logger.error(f"Vision: Falha crítica na recuperação: {rec_err}")
                        continue

                time.sleep(0.008)

        except Exception as e:
            logger.error(f"Vision thread fatal error: {e}")
            logger.error(traceback.format_exc())
            logger.info("Orbwalker continua funcionando no modo cego.")
        finally:
            if capture:
                try:
                    capture.stop()
                except:
                    pass

    def _status_loop(self):
        """Exibe status no console."""
        try:
            while self.running:
                if self.engine:
                    mode = self.engine.mode if self.engine.active else "IDLE"
                    as_val = self.riot_api.attack_speed
                    hp = self.riot_api.health_percent * 100

                    target, ttype = self.engine.get_vision_target()
                    vision_str = f"→ {ttype} @({target[0]},{target[1]})" if target else "nenhum"

                    spa = self.engine.get_seconds_per_attack()
                    windup = self.engine.get_windup_duration()

                    print(
                        f"\r  [{mode:10s}] "
                        f"AS:{as_val:.2f} "
                        f"SecPerAtk:{spa:.3f}s "
                        f"Windup:{windup:.3f}s "
                        f"HP:{hp:.0f}% "
                        f"Atks:{self.engine.attacks} "
                        f"Moves:{self.engine.moves} "
                        f"Vision:{vision_str:30s}",
                        end="", flush=True
                    )

                time.sleep(0.5)
        except KeyboardInterrupt:
            self._shutdown()

    def _shutdown(self):
        logger.info("\nShutting down...")
        self.running = False
        if self.engine:
            self.engine.stop()
        self.riot_api.stop()
        # Remove APENAS o hook do bot — nunca unhook_all() para não matar o hook do menu
        try:
            if self._keyboard_hook:
                keyboard.unhook(self._keyboard_hook)
                self._keyboard_hook = None
        except:
            pass
        logger.info("Goodbye!")


if __name__ == "__main__":
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except:
        is_admin = False

    if not is_admin:
        logger.warning("⚠ Execute como Administrador para keyboard hooks!")

    app = ExternalOrbwalker()
    try:
        app.start()
    except KeyboardInterrupt:
        app._shutdown()
