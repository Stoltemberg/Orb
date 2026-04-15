"""
vision/health_bar_detector.py — Detecção de health bars inimigas via OpenCV.
Passo 1 do pipeline de visão: encontra todas as barras de vida vermelhas na tela.
"""
import cv2
import numpy as np
import logging
from dataclasses import dataclass

from config import VisionConfig

logger = logging.getLogger("ExternalOrbwalker.HealthBarDetector")


@dataclass
class HealthBar:
    """Representa uma health bar detectada na tela."""
    x: int              # Canto esquerdo da barra
    y: int              # Topo da barra
    width: int          # Largura em pixels
    height: int         # Altura em pixels
    center_x: int       # Centro X da barra
    center_y: int       # Centro Y da barra
    fill_ratio: float   # % da barra preenchida (0.0 a 1.0)
    area: int           # Área do contorno


class HealthBarDetector:
    """
    Detecta health bars inimigas (vermelhas) usando processamento HSV.
    Otimizado para rodar a ~200+ FPS em CPU.
    """

    def __init__(self, screen_width: int = 1920, screen_height: int = 1080):
        self.screen_width = screen_width
        self.screen_height = screen_height

        # ── Calcular fator de escala em relação a 1080p ──
        # LoL UI escala pela ALTURA, não pela largura!
        # Em ultrawide (2560x1080), health bars são do mesmo tamanho que 1920x1080
        self.scale_factor = screen_height / VisionConfig.REFERENCE_HEIGHT

        # ── Pré-computar ranges HSV ──
        self.red_lower_1 = np.array(VisionConfig.ENEMY_RED_LOWER_1, dtype=np.uint8)
        self.red_upper_1 = np.array(VisionConfig.ENEMY_RED_UPPER_1, dtype=np.uint8)
        self.red_lower_2 = np.array(VisionConfig.ENEMY_RED_LOWER_2, dtype=np.uint8)
        self.red_upper_2 = np.array(VisionConfig.ENEMY_RED_UPPER_2, dtype=np.uint8)

        # ── Kernel para morphological operations (eliminar ruído) ──
        self._kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1))
        self._kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 2))

        # ── Thresholds escalados ──
        self.min_bar_width = int(VisionConfig.MINION_BAR_MIN_WIDTH * self.scale_factor)
        self.max_bar_width = int(200 * self.scale_factor)  # Limitar para evitar falsos positivos
        self.min_bar_height = max(2, int(3 * self.scale_factor))
        self.max_bar_height = int(12 * self.scale_factor)

        logger.info(
            f"HealthBarDetector initialized @ {screen_width}x{screen_height} "
            f"(scale: {self.scale_factor:.2f})"
        )

    def detect(self, frame: np.ndarray) -> list[HealthBar]:
        """
        Detecta health bars inimigas no frame.

        Args:
            frame: Frame BGR capturado da tela

        Returns:
            Lista de HealthBar detectadas, ordenadas por posição Y
        """
        # ── 1. Converter para HSV ──
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # ── 2. Criar máscara para vermelho (2 ranges porque hue wrapa) ──
        mask1 = cv2.inRange(hsv, self.red_lower_1, self.red_upper_1)
        mask2 = cv2.inRange(hsv, self.red_lower_2, self.red_upper_2)
        red_mask = cv2.bitwise_or(mask1, mask2)

        # ── 3. Morphological ops para limpar ruído ──
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, self._kernel_open)
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, self._kernel_close)

        # ── 4. Encontrar contornos ──
        contours, _ = cv2.findContours(
            red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # ── 5. Filtrar e classificar contornos como health bars ──
        health_bars = []

        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)

            # Filtro de tamanho absoluto
            if w < self.min_bar_width or w > self.max_bar_width:
                continue
            if h < self.min_bar_height or h > self.max_bar_height:
                continue

            # Filtro de aspect ratio (barras são horizontais)
            aspect = w / max(h, 1)
            if aspect < VisionConfig.MIN_ASPECT_RATIO or aspect > VisionConfig.MAX_ASPECT_RATIO:
                continue

            # ── 6. Filtrar por posição: EXCLUIR zonas do HUD ──
            # KDA/Timer (Top Center) e Team Stats (Top Right)
            if y < 60 * self.scale_factor:
                # Cobre do meio da tela (Timers) até a ponta direita (KDA Stats)
                if x > (self.screen_width / 2) - (200 * self.scale_factor):
                    continue
                    
            # Interface central inferior (Habilidades, Vida, Itens)
            if y > self.screen_height - (220 * self.scale_factor):
                # Ancorado no centro inferior (~550px pra cada lado do centro)
                center_x = self.screen_width / 2
                if center_x - (550 * self.scale_factor) < x < center_x + (550 * self.scale_factor):
                    continue

            # Minimap (canto inferior direito)
            if x > self.screen_width - (350 * self.scale_factor) and y > self.screen_height - (350 * self.scale_factor):
                continue

            # Retrato do campeão + stats laterais (canto inferior esquerdo)
            if x < (350 * self.scale_factor) and y > self.screen_height - (300 * self.scale_factor):
                continue

            # Calcular fill ratio (quanta vida restante)
            bar_region = red_mask[y:y+h, x:x+w]
            filled_pixels = cv2.countNonZero(bar_region)
            total_pixels = w * h
            fill_ratio = filled_pixels / max(total_pixels, 1)

            area = cv2.contourArea(contour)

            health_bars.append(HealthBar(
                x=x,
                y=y,
                width=w,
                height=h,
                center_x=x + w // 2,
                center_y=y + h // 2,
                fill_ratio=min(fill_ratio, 1.0),
                area=area
            ))

        # Ordenar por Y (mais perto do topo = mais distante no jogo)
        health_bars.sort(key=lambda hb: hb.y)

        return health_bars

    def draw_debug(self, frame: np.ndarray, health_bars: list[HealthBar]) -> np.ndarray:
        """
        Desenha retângulos ao redor das health bars detectadas para debug.

        Args:
            frame: Frame original
            health_bars: Lista de HealthBar

        Returns:
            Frame com anotações
        """
        debug_frame = frame.copy()
        for hb in health_bars:
            color = (0, 255, 0)  # Verde para debug
            cv2.rectangle(debug_frame, (hb.x, hb.y), (hb.x + hb.width, hb.y + hb.height), color, 2)
            # Label com largura
            label = f"w={hb.width} fill={hb.fill_ratio:.0%}"
            cv2.putText(debug_frame, label, (hb.x, hb.y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        return debug_frame
