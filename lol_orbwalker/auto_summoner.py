import time
import threading
import logging
import random
import keyboard
from config import AutoSummonerConfig

logger = logging.getLogger("ExternalOrbwalker.AutoSummoner")

class AutoSummoner:
    """
    Monitora a saúde do jogador via Riot API e aperta botões de pânico
    quando a vida cai pra menos do threshold.
    """
    def __init__(self, riot_api):
        self.riot_api = riot_api
        self.running = False
        self.thread = None
        
        self.last_heal_time = 0.0
        self.last_barrier_time = 0.0

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.thread.start()
            logger.info("Auto-Summoner module ativado!")

    def stop(self):
        self.running = False

    def _monitor_loop(self):
        while self.running:
            try:
                if not AutoSummonerConfig.ENABLED:
                    time.sleep(0.5)
                    continue
                    
                if not self.riot_api.connected:
                    time.sleep(0.5)
                    continue
                    
                hp_percent = self.riot_api.health_percent
                now = time.time()
                
                # Cuidado: hp_percent pode ser 0 se estiver morto (aumentamos threshold morto se hp > 0)
                if hp_percent > 0.0 and hp_percent <= AutoSummonerConfig.ACTIVATION_HP_PERCENT:
                    
                    # Checar cooldown do Heal
                    if (now - self.last_heal_time) > AutoSummonerConfig.COOLDOWN:
                        logger.warning(f"CRÍTICO: HP em {hp_percent*100:.1f}%. Ativando HEAL ({AutoSummonerConfig.HEAL_KEY})!")
                        self.input_sim.press_key(AutoSummonerConfig.HEAL_KEY)
                        self.last_heal_time = now
                        time.sleep(random.uniform(0.1, 0.2)) # Atraso pequeno entre spells se precisar
                        
                    # Checar cooldown de Barrier
                    if (now - self.last_barrier_time) > AutoSummonerConfig.COOLDOWN:
                        logger.warning(f"CRÍTICO: HP em {hp_percent*100:.1f}%. Ativando BARRIER ({AutoSummonerConfig.BARRIER_KEY})!")
                        self.input_sim.press_key(AutoSummonerConfig.BARRIER_KEY)
                        self.last_barrier_time = now

            except Exception as e:
                logger.error(f"Erro no AutoSummoner: {e}")
                
            time.sleep(0.01) # Check de 10ms
