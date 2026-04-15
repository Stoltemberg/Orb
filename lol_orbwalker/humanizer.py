"""
humanizer.py — Variação pseudo-aleatória nos timings para evitar detecção de padrões.
"""
import random
import time
import logging

from config import OrbwalkerConfig

logger = logging.getLogger("ExternalOrbwalker.Humanizer")


class Humanizer:
    """
    Adiciona variação randomizada aos timings do orbwalker
    para evitar padrões repetitivos detectáveis por análise server-side.
    """

    def __init__(self,
                 min_delay: float = None,
                 max_delay: float = None):
        self.min_delay = min_delay or OrbwalkerConfig.HUMANIZER_MIN
        self.max_delay = max_delay or OrbwalkerConfig.HUMANIZER_MAX

        # ── Estado interno para variação progressiva ──
        self._last_delays = []
        self._max_history = 20

    def get_attack_delay(self) -> float:
        """
        Retorna um delay randomizado para adicionar ao timing de ataque.
        Usa distribuição triangular para favorecer valores medianos.

        Returns:
            Delay em segundos
        """
        delay = random.triangular(self.min_delay, self.max_delay)

        # Evitar repetição exata dos últimos delays
        if self._last_delays and abs(delay - self._last_delays[-1]) < 0.001:
            delay += random.uniform(0.001, 0.005)

        self._record_delay(delay)
        return delay

    def get_move_delay(self) -> float:
        """
        Retorna um delay randomizado para o movimento (ligeiramente diferente do ataque).
        Movimentos podem ser um pouco mais espaçados.

        Returns:
            Delay em segundos
        """
        return random.uniform(self.min_delay * 0.5, self.max_delay * 1.5)

    def get_cursor_offset(self, max_px: int = 5) -> tuple[int, int]:
        """
        Retorna um offset randomizado para a posição do cursor.
        Simula imprecisão natural do mouse.

        Args:
            max_px: Desvio máximo em pixels

        Returns:
            (offset_x, offset_y) em pixels
        """
        # Distribuição normal centrada em 0 com std=max_px/3
        # ~99.7% dos valores ficam dentro de max_px
        ox = int(random.gauss(0, max_px / 3))
        oy = int(random.gauss(0, max_px / 3))
        return (
            max(-max_px, min(max_px, ox)),
            max(-max_px, min(max_px, oy))
        )

    def should_skip_move(self, probability: float = 0.05) -> bool:
        """
        Ocasionalmente pula um comando de movimento para parecer humano.
        Jogadores reais nem sempre dão right-click perfeitamente entre ataques.

        Args:
            probability: Chance de pular (0.0 a 1.0)

        Returns:
            True se deve pular o move command neste tick
        """
        return random.random() < probability

    def _record_delay(self, delay: float):
        """Registra delay para análise de padrão."""
        self._last_delays.append(delay)
        if len(self._last_delays) > self._max_history:
            self._last_delays.pop(0)

    @staticmethod
    def _bezier_point(t: float, p0: tuple[int, int], p1: tuple[int, int], p2: tuple[int, int], p3: tuple[int, int]) -> tuple[int, int]:
        """Calcula um ponto na curva de Bézier cúbica de 4 pontos no instante t (0.0 a 1.0)."""
        u = 1 - t
        tt = t * t
        uu = u * u
        uuu = uu * u
        ttt = tt * t

        p = [uuu * p0[0], uuu * p0[1]]
        p[0] += 3 * uu * t * p1[0]
        p[1] += 3 * uu * t * p1[1]
        p[0] += 3 * u * tt * p2[0]
        p[1] += 3 * u * tt * p2[1]
        p[0] += ttt * p3[0]
        p[1] += ttt * p3[1]

        return int(p[0]), int(p[1])

    def move_cursor_bezier(self, start_x: int, start_y: int, end_x: int, end_y: int, steps: int = 15):
        """
        Move o cursor do mouse do ponto inicial ao final formando uma curva de Bézier humana.
        :param steps: Número de passos na curva (maior = mais lento e mais suave).
        """
        import ctypes
        import math
        
        # Gerar pontos de controle aleatórios baseados na distância
        dist = math.hypot(end_x - start_x, end_y - start_y)
        
        # Se estiver muito perto, vai direto
        if dist < 10:
            ctypes.windll.user32.SetCursorPos(end_x, end_y)
            return

        # Controle 1: 1/3 do caminho + offset aleatório (suavizado pela distância)
        cp1_x = int(start_x + (end_x - start_x) / 3.0 + random.gauss(0, dist * 0.15))
        cp1_y = int(start_y + (end_y - start_y) / 3.0 + random.gauss(0, dist * 0.15))
        
        # Controle 2: 2/3 do caminho + offset
        cp2_x = int(start_x + (end_x - start_x) * 2.0 / 3.0 + random.gauss(0, dist * 0.15))
        cp2_y = int(start_y + (end_y - start_y) * 2.0 / 3.0 + random.gauss(0, dist * 0.15))
        
        p0 = (start_x, start_y)
        p1 = (cp1_x, cp1_y)
        p2 = (cp2_x, cp2_y)
        p3 = (end_x, end_y)
        
        user32 = ctypes.windll.user32
        
        # Executar movimento
        for i in range(1, steps + 1):
            t = i / float(steps)
            # Função ease-out para desacelerar perto do alvo
            t_ease = math.sin(t * math.pi / 2)
            
            x, y = self._bezier_point(t_ease, p0, p1, p2, p3)
            user32.SetCursorPos(x, y)
            
            # Pequeno delay em loop (~1 ms por tick)
            time.sleep(random.uniform(0.0005, 0.0015))

