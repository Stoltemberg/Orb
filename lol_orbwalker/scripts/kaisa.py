"""
scripts/kaisa.py — Combo da Kai'Sa (Q + W Snipe).
"""
import time
import logging
import math
from typing import Optional

from scripts.base_script import BaseScript
from input.input_simulator import Keyboard, DIK_Q, DIK_W, DIK_R
from vision.entity_classifier import DetectedEntity



logger = logging.getLogger("ExternalOrbwalker.Scripts.Kaisa")

class KaisaScript(BaseScript):
    def __init__(self, riot_api, champ_data):
        super().__init__(riot_api, champ_data)
        
        # ── Cooldowns Estimados ──
        self.last_q_time = 0
        self.q_cooldown = 10.0 # Base Q CD
        
        self.last_w_time = 0
        self.w_cooldown = 14.0 # Base W CD (22 to 14s based on level, let's use 14s for better uptime)
        
        self.last_r_time = 0
        
        # Tracking do E (Supercharge)
        self.e_charge_end_time = 0
        self._e_pressed = False  # debounce: evita spam enquanto tecla está pressionada
        
        # Kai'Sa SEMPRE usa auto-attacks, exceto ao carregar o E
        self.allow_aa = True
        
        logger.info("Kai'Sa Script loaded")

    def execute(self, target: Optional[DetectedEntity], mode: str) -> bool:
        """
        Combo Kai'Sa: Q Inteligente, W longo, e controle de E.
        """
        now = time.perf_counter()
        
        # Se estiver carregando o E (Supercharge), ela GANHA move speed
        # mas NÃO PODE atacar. Precisamos desabilitar o AA para focar no kiting.
        if now < self.e_charge_end_time:
            self.allow_aa = False
        else:
            self.allow_aa = True
            
        if not target or mode != "combo":
            return False
        
        # 1. Tentar conjurar Q (Icathian Rain)
        # Removido limite fixo de distância (pixels) pois falhava se a câmera 
        # não estivesse 100% centralizada. Sendo um orbwalker local, se a visão pegou, atire.
        if now > self.last_q_time + 4.0: # CD Reduzido para testar o spam (mid/late game)
            Keyboard.key_down(DIK_Q)
            Keyboard.key_up(DIK_Q)
            
            self.last_q_time = now
            logger.info("Cast Q (Icathian Rain)")
            # Q não tem cast time, engine não pausa
            
        # 2. Tentar conjurar W (Void Seeker)
        # Range longo. W TEM cast time de 0.25s.
        if now > self.last_w_time + 10.0:
            Keyboard.press_key(DIK_W)
            
            self.last_w_time = now
            logger.info("Cast W (Void Seeker)")
            return True # W tem cast time, avisa o engine para pausar orbwalk
            
        # 3. MODO BERSERKER (Auto R)
        # O bot tenta soltar R sem parar (200ms de intervalo). 
        # Assim que o inimigo ganhar o Plasma, ela pula sozinha.
        if now > self.last_r_time + 0.2:
            Keyboard.press_key(DIK_R, min_delay=0.005, max_delay=0.015) # R spammer needs to be fast
            self.last_r_time = now
            # logger.info("Spamming R...")
            
        return False

    def on_key_event(self, key: str, event_type: str):
        """Track manual casts."""
        if event_type == "down":
            if key == 'q':
                self.last_q_time = time.perf_counter()
            elif key == 'w':
                self.last_w_time = time.perf_counter()
            elif key == 'r':
                self.last_r_time = time.perf_counter()
            elif key == 'e':
                if not self._e_pressed:  # Só registra na primeira pressão (ignora key repeat)
                    self._e_pressed = True
                    self.e_charge_end_time = time.perf_counter() + 1.0
                    logger.info("E (Supercharge) Tracking: AA desativado por 1s.")
        elif event_type == "up":
            if key == 'e':
                self._e_pressed = False  # Libera o debounce ao soltar a tecla
