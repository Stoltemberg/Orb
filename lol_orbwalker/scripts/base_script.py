"""
scripts/base_script.py — Interface base para combos de campeões.
"""
from abc import ABC, abstractmethod
from typing import Optional
from vision.entity_classifier import DetectedEntity

class BaseScript(ABC):
    """
    Classe base para todos os scripts de campeões.
    Define o contrato que o engine espera.
    """
    
    def __init__(self, riot_api, champ_data):
        self.riot_api = riot_api
        self.champ = champ_data
        self.last_execute_time = 0
        self.allow_aa = True    # Se False, o engine não vai tentar dar Auto-Attack
        
    @abstractmethod
    def execute(self, target: Optional[DetectedEntity], mode: str) -> bool:
        """
        Executa a lógica de habilidades do campeão.
        
        Args:
            target: Entidade detectada pela visão (pode ser None)
            mode: Modo atual (combo, lasthit, etc.)
            
        Returns:
            True se uma habilidade foi conjurada (deve pausar orbwalk brevemente se houver cast time)
        """
        pass
    
    def on_key_event(self, key: str, event_type: str):
        """Hook para rastrear uso manual de habilidades (cooldowns)."""
        pass
