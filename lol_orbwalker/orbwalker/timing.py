"""
orbwalker/timing.py — Cálculos precisos de timing para orbwalking.
Replica as fórmulas validadas do Auto-Kite Bot e VakScript.
"""
import logging

from config import OrbwalkerConfig
from champion_data import ChampionData

logger = logging.getLogger("ExternalOrbwalker.Timing")


class AttackTimer:
    """
    Calcula tempos de ataque e windup com base nos dados do champion
    e no attack speed atual reportado pela Riot API.
    """

    def __init__(self, champion_data: ChampionData):
        self.champ = champion_data

    def get_seconds_per_attack(self, current_attack_speed: float) -> float:
        """
        Tempo total de um ciclo de ataque.

        Args:
            current_attack_speed: Attack speed atual (da Riot API)

        Returns:
            Tempo em segundos para completar um auto-attack cycle
        """
        if current_attack_speed <= 0:
            return 1.0
        return 1.0 / current_attack_speed

    def get_windup_duration(self, current_attack_speed: float) -> float:
        """
        Duração do windup do auto-attack (tempo antes de soltar o projétil).
        Esta é a fórmula exata usada pelo Auto-Kite Bot e pelo game engine.

        Fórmula:
            windup = ((seconds_per_attack * delay_percent) - cast_time) * delay_scaling + cast_time

        Args:
            current_attack_speed: Attack speed atual

        Returns:
            Duração do windup em segundos
        """
        seconds_per_attack = self.get_seconds_per_attack(current_attack_speed)
        delay_percent = self.champ.attack_delay_percent
        cast_time = self.champ.attack_cast_time
        delay_scaling = self.champ.attack_delay_scaling

        windup = ((seconds_per_attack * delay_percent) - cast_time) * delay_scaling + cast_time
        return max(windup, 0.01)  # Safety floor

    def get_buffered_windup_duration(self, current_attack_speed: float, ping_offset_ms: float = 0) -> float:
        """
        Windup com buffer de segurança + compensação de ping.
        Este é o tempo que devemos esperar ANTES de poder dar move command.

        Args:
            current_attack_speed: Attack speed atual
            ping_offset_ms: Compensação de ping em ms

        Returns:
            Duração total em segundos
        """
        windup = self.get_windup_duration(current_attack_speed)
        buffer = OrbwalkerConfig.WINDUP_BUFFER
        ping_s = ping_offset_ms / 1000.0
        capture_comp = OrbwalkerConfig.SCREEN_CAPTURE_COMPENSATION

        return windup + buffer + ping_s + capture_comp

    def get_move_window(self, current_attack_speed: float, ping_offset_ms: float = 0) -> float:
        """
        Duração da janela de movimento entre ataques.
        = seconds_per_attack - buffered_windup

        Args:
            current_attack_speed: Attack speed atual
            ping_offset_ms: Compensação de ping em ms

        Returns:
            Tempo disponível para movement em segundos
        """
        total = self.get_seconds_per_attack(current_attack_speed)
        windup = self.get_buffered_windup_duration(current_attack_speed, ping_offset_ms)
        return max(total - windup, 0.01)

    def debug_info(self, current_attack_speed: float, ping_offset_ms: float = 0) -> str:
        """Retorna string com todas as informações de timing para debug."""
        spa = self.get_seconds_per_attack(current_attack_speed)
        windup = self.get_windup_duration(current_attack_speed)
        buffered = self.get_buffered_windup_duration(current_attack_speed, ping_offset_ms)
        window = self.get_move_window(current_attack_speed, ping_offset_ms)

        return (
            f"AS: {current_attack_speed:.3f} | "
            f"SecPerAtk: {spa:.3f}s | "
            f"Windup: {windup:.3f}s | "
            f"Buffered: {buffered:.3f}s | "
            f"MoveWindow: {window:.3f}s | "
            f"Delay%: {self.champ.attack_delay_percent:.3f} | "
            f"Scaling: {self.champ.attack_delay_scaling:.3f}"
        )
