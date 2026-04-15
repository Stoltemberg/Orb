"""
scripts/cassiopeia.py — Combo da Cassiopeia (Q + E Spam).
"""
import time
import logging
from typing import Optional

from scripts.base_script import BaseScript
from input.input_simulator import Keyboard, DIK_Q, DIK_E
from vision.entity_classifier import DetectedEntity, EntityType

logger = logging.getLogger("ExternalOrbwalker.Scripts.Cassiopeia")

class CassiopeiaScript(BaseScript):
    def __init__(self, riot_api, champ_data):
        super().__init__(riot_api, champ_data)
        
        # ── Timers de Cooldown (Estimados) ──
        self.last_q_time = 0
        self.q_cooldown = 3.5
        
        # ── Timer de Envenenamento ──
        # Como não sabemos quem está envenenado, assumimos que o alvo 
        # atual fica envenenado por 3s após o Q.
        self.target_poisoned_until = 0
        self.poison_duration = 3.0
        
        # ── Throttling do E ──
        self.last_e_time = 0
        self.e_cooldown = 0.75 # Cooldown base do E
        
        logger.info("Cassiopeia Script loaded")

    def execute(self, target: Optional[DetectedEntity], mode: str) -> bool:
        """
        Combo: Q -> E Spam.
        """
        self.allow_aa = (mode != "combo") # Desabilitar AA no combo da Cassio
        
        if not target or mode != "combo":
            return False
            
        now = time.perf_counter()
        
        # 1. Tentar conjurar Q se pronto (3.5s CD)
        if now > self.last_q_time + self.q_cooldown:
            # Q cast: Noxious Blast
            Keyboard.press_key(DIK_Q)
            
            self.last_q_time = now
            self.target_poisoned_until = now + 0.4 + self.poison_duration 
            logger.info("Cast Q (Noxious Blast)")
            return True # Q tem cast time
            
        # 2. Spammar E o mais rápido possível (0.1s throttling p/ não inundar)
        if now > self.last_e_time + 0.10: 
            Keyboard.press_key(DIK_E, min_delay=0.005, max_delay=0.015) # fast press
            self.last_e_time = now
            return False # E não tem cast time
            
        return False

    def on_key_event(self, key: str, event_type: str):
        """Track manual casts to sync cooldowns."""
        if event_type == "down":
            if key == 'q':
                self.last_q_time = time.perf_counter()
                self.target_poisoned_until = self.last_q_time + 3.4
            elif key == 'e':
                self.last_e_time = time.perf_counter()
