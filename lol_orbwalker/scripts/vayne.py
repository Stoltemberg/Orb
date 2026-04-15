"""
scripts/vayne.py — Combo da Vayne.
"""
import time
import logging
import math
from typing import Optional

from scripts.base_script import BaseScript
from input.input_simulator import Keyboard
from vision.entity_classifier import DetectedEntity

DIK_Q = 0x10
DIK_E = 0x12
DIK_R = 0x13

logger = logging.getLogger("ExternalOrbwalker.Scripts.Vayne")

class VayneScript(BaseScript):
    def __init__(self, riot_api, champ_data):
        super().__init__(riot_api, champ_data)
        
        self.last_q_time = 0
        self.q_cooldown = 4.0 # Base Q CD
        
        self.last_e_time = 0
        self.e_cooldown = 20.0 # Base E CD
        
        self.last_r_time = 0
        
        self.allow_aa = True
        
        logger.info("Vayne Script loaded")

    def execute(self, target: Optional[DetectedEntity], mode: str) -> bool:
        """
        Combo Vayne: Q ofensivo/peel, E defensivo (Anti-Dive).
        """
        now = time.perf_counter()
        
        if not target or mode != "combo":
            return False
            
        # Calcular distância estimada
        dx = target.screen_x - 1280
        dy = target.screen_y - 540
        dist_sq = dx**2 + dy**2
        
        # 1. E (Condemn) como Anti-Dive (Peel)
        # Se um campeão inimigo chegar muito perto (ex: Assassino pulando), empurramos.
        # ~250 pixels = muito perto
        if now > self.last_e_time + self.e_cooldown:
            if dist_sq < 250**2:
                Keyboard.press_key(DIK_E)
                self.last_e_time = now
                logger.info("Cast E (Condemn) - Self Peel")
                return True # E tem cast time curto, avisa o engine
                
        # 2. Q (Tumble)
        # O Q reseta o ataque básico, mas como rodamos antes do ataque, 
        # vamos soltar o Q para nos aproximar ou desviar se o inimigo não estiver suicida.
        if now > self.last_q_time + self.q_cooldown:
            if dist_sq > 250**2 and dist_sq < 600**2:
                Keyboard.press_key(DIK_Q)
                self.last_q_time = now
                logger.info("Cast Q (Tumble)")
                # Q rola na direção do mouse. O motor vai andar e no próximo frame atirar.
                return False
                
        return False

    def on_key_event(self, key: str, event_type: str):
        if event_type == "down":
            if key == 'q':
                self.last_q_time = time.perf_counter()
            elif key == 'e':
                self.last_e_time = time.perf_counter()
            elif key == 'r':
                self.last_r_time = time.perf_counter()
