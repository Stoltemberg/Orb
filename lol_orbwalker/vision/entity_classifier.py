"""
vision/entity_classifier.py — Classifica health bars detectadas em tipos de entidade.
Usa tamanho da barra, presença de level indicator, e contexto.
"""
import cv2
import numpy as np
import logging
from enum import Enum, auto
from dataclasses import dataclass

from config import VisionConfig
from vision.health_bar_detector import HealthBar

logger = logging.getLogger("ExternalOrbwalker.EntityClassifier")


class EntityType(Enum):
    CHAMPION = auto()
    MINION = auto()
    MINION_SIEGE = auto()
    TURRET = auto()
    MONSTER = auto()
    UNKNOWN = auto()


@dataclass
class DetectedEntity:
    """Entidade detectada e classificada na tela."""
    entity_type: EntityType
    screen_x: int          # Posição X estimada do corpo na tela
    screen_y: int          # Posição Y estimada do corpo na tela
    health_bar: HealthBar  # Health bar original
    confidence: float      # Confiança da classificação (0.0 a 1.0)
    has_level: bool        # Se foi detectado um indicador de nível
    is_ambiguous: bool = False # Se o score OpenCV ficou empatado


class EntityClassifier:
    """
    Classifica health bars em tipos de entidade usando múltiplos sinais:
    1. Tamanho da health bar (principal)
    2. Presença de level indicator (forte)
    3. Presença de barra de mana azul abaixo (forte)
    4. Altura da barra (campeões têm barras ligeiramente mais altas)
    5. Posição na tela (contexto)
    """

    def __init__(self, screen_width: int = 1920, screen_height: int = 1080):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.scale = screen_height / VisionConfig.REFERENCE_HEIGHT

        # ── Thresholds escalados ──
        # NOTA: A largura da health bar VERMELHA encolhe com o HP perdido.
        # Campeão full HP @1080p ≈ 103px, mas com 50% HP a porção vermelha ≈ 52px.
        # Por isso, width sozinha NÃO é suficiente para classificar.
        self.champ_min_w = int(VisionConfig.CHAMPION_BAR_MIN_WIDTH * self.scale)
        self.siege_min_w = int(VisionConfig.MINION_SIEGE_BAR_MIN_WIDTH * self.scale)
        self.minion_max_w = int(VisionConfig.MINION_BAR_MAX_WIDTH * self.scale)
        self.body_offset = int(VisionConfig.BODY_OFFSET_Y * self.scale)

        # ── Level indicator detection params (multi-zone) ──
        self.level_check_size = max(10, int(16 * self.scale))

        # ── Mana bar detection ──
        self.mana_check_height = max(3, int(5 * self.scale))
        self.mana_check_gap = max(1, int(2 * self.scale))  # Gap entre HP bar e mana bar

        logger.info(
            f"EntityClassifier initialized | "
            f"Champion bar >= {self.champ_min_w}px | "
            f"Siege >= {self.siege_min_w}px | "
            f"Minion max = {self.minion_max_w}px"
        )

    def classify(self, frame: np.ndarray, health_bars: list[HealthBar]) -> list[DetectedEntity]:
        """
        Classifica uma lista de health bars detectadas.

        Args:
            frame: Frame BGR original (para análise de level indicator)
            health_bars: Lista de HealthBar do detector

        Returns:
            Lista de DetectedEntity classificadas
        """
        entities = []

        for hb in health_bars:
            # ── Verificar presença de level indicator ──
            has_level = self._check_level_indicator(frame, hb)

            # ── Classificar pelo score ──
            entity_type, confidence, is_ambiguous = self._classify_by_size_and_score(frame, hb, has_level)

            # ── Estimar posição do corpo ──
            body_x = hb.center_x
            body_y = hb.center_y + self.body_offset

            entities.append(DetectedEntity(
                entity_type=entity_type,
                screen_x=body_x,
                screen_y=body_y,
                health_bar=hb,
                confidence=confidence,
                has_level=has_level,
                is_ambiguous=is_ambiguous
            ))

        return entities

    def _classify_by_size_and_score(self, frame: np.ndarray, hb: HealthBar, has_level: bool) -> tuple[EntityType, float, bool]:
        """
        Classificação multi-sinal robusta por SCORES, e não por regras absolutas.
        Retorna (EntityType, Confidence, is_ambiguous).
        """
        w = hb.width
        h = hb.height
        has_resource = self._check_resource_bar(frame, hb)
        
        champ_score = 0.0
        minion_score = 0.0

        if has_level:
            champ_score += 3.0
            
        if has_resource:
            champ_score += 2.5

        if w >= self.champ_min_w:
            champ_score += 2.0
        elif w <= self.minion_max_w:
            minion_score += 2.0

        bar_height_threshold = max(3, int(4 * self.scale))
        if h >= bar_height_threshold:
            champ_score += 0.6
        else:
            minion_score += 0.3

        # Decisão
        if champ_score > minion_score + 1.0:
            return EntityType.CHAMPION, min(0.6 + champ_score * 0.1, 0.99), False
        elif minion_score > champ_score + 1.0:
            if w >= self.siege_min_w:
                return EntityType.MINION_SIEGE, min(0.6 + minion_score * 0.1, 0.99), False
            return EntityType.MINION, min(0.6 + minion_score * 0.1, 0.99), False
        else:
            # Ambiguidade (Score apertado)
            etype = EntityType.MINION_SIEGE if w >= self.siege_min_w else EntityType.MINION
            return etype, 0.50, True

    def _check_level_indicator(self, frame: np.ndarray, hb: HealthBar) -> bool:
        """
        Verifica se existe um indicador de nível ao lado da health bar.
        Campeões inimigos têm um número de nível branco/amarelo à esquerda.
        Minions NUNCA têm isso.
        
        Usa múltiplas zonas de verificação para resistir a variações de
        posição e escala entre campeões diferentes.
        """
        # ── Zona 1: Imediatamente à esquerda da barra ──
        # O level text fica ~3-18px à esquerda da borda da barra
        size = self.level_check_size
        
        check_positions = [
            (hb.x - size - 2, hb.y - 2),      # Posição padrão
            (hb.x - size + 2, hb.y - 4),      # Ligeiramente mais perto/acima
            (hb.x - size - 6, hb.y),          # Mais pra esquerda
            (hb.x - size - 4, hb.y - 6),      # Mais alto
        ]
        
        for check_x, check_y in check_positions:
            if check_x < 0 or check_y < 0:
                continue
            if check_x + size >= frame.shape[1] or check_y + size >= frame.shape[0]:
                continue
            
            roi = frame[check_y:check_y + size, check_x:check_x + size]
            if roi.size == 0:
                continue
            
            # ── Detectar texto branco/amarelo ──
            # Converter para HSV para diferenciar branco/amarelo de ruído
            hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            
            # Branco puro (alto brilho, baixa saturação)
            _, white_thresh = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY)
            white_ratio = cv2.countNonZero(white_thresh) / max(gray.size, 1)
            
            # Amarelo (hue 20-35, alta saturação) — level enemies em alguns skins
            yellow_mask = cv2.inRange(hsv_roi, 
                                      np.array([18, 80, 150], dtype=np.uint8),
                                      np.array([38, 255, 255], dtype=np.uint8))
            yellow_ratio = cv2.countNonZero(yellow_mask) / max(gray.size, 1)
            
            combined_ratio = white_ratio + yellow_ratio
            
            # Level text = limites mais brandos (5% a 60% claros)
            if 0.05 < combined_ratio < 0.60:
                return True
        
        return False
    
    def _check_resource_bar(self, frame: np.ndarray, hb: HealthBar) -> bool:
        """
        Verifica se existe uma barra secundária (mana, energia, fúria, shield) abaixo da health bar.
        Campeões costumam ter; minions NÃO.
        """
        mana_x = hb.x
        mana_y = hb.y + hb.height + self.mana_check_gap
        # Expandir a largura para evitar se limitar à caixa vermelha parcialmente preenchida
        mana_w = max(hb.width, self.champ_min_w)
        mana_h = self.mana_check_height
        
        # Boundary check
        if mana_y + mana_h >= frame.shape[0] or mana_x + mana_w >= frame.shape[1]:
            return False
        if mana_x < 0 or mana_y < 0:
            return False
            
        roi = frame[mana_y:mana_y + mana_h, mana_x:mana_x + mana_w]
        if roi.size == 0:
            return False
        
        hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        
        # Captura barras coloridas (alta saturação e brilho)
        lower = np.array([0, 40, 60], dtype=np.uint8)
        upper = np.array([179, 255, 255], dtype=np.uint8)
        resource_mask = cv2.inRange(hsv_roi, lower, upper)
        
        # Captura barras totalmente claras (shield/fury: baixa saturacao, brilho intenso)
        lower_white = np.array([0, 0, 180], dtype=np.uint8)
        upper_white = np.array([179, 40, 255], dtype=np.uint8)
        white_mask = cv2.inRange(hsv_roi, lower_white, upper_white)
        
        combined = cv2.bitwise_or(resource_mask, white_mask)
        ratio = cv2.countNonZero(combined) / max(mana_w * mana_h, 1)
        
        return ratio > 0.15

    def get_champions(self, entities: list[DetectedEntity]) -> list[DetectedEntity]:
        """Filtra apenas campeões."""
        return [e for e in entities if e.entity_type == EntityType.CHAMPION]

    def get_minions(self, entities: list[DetectedEntity]) -> list[DetectedEntity]:
        """Filtra apenas minions normais e siege."""
        return [e for e in entities
                if e.entity_type in (EntityType.MINION, EntityType.MINION_SIEGE)]

    def get_all_enemies(self, entities: list[DetectedEntity]) -> list[DetectedEntity]:
        """Retorna todas as entidades inimigas detectadas."""
        return [e for e in entities if e.entity_type != EntityType.UNKNOWN]

    def draw_debug(self, frame: np.ndarray, entities: list[DetectedEntity]) -> np.ndarray:
        """Desenha entidades classificadas com cores por tipo."""
        debug = frame.copy()
        colors = {
            EntityType.CHAMPION: (0, 0, 255),     # Vermelho
            EntityType.MINION: (0, 200, 200),      # Amarelo
            EntityType.MINION_SIEGE: (0, 165, 255), # Laranja
            EntityType.TURRET: (255, 0, 255),      # Magenta
            EntityType.MONSTER: (255, 100, 0),     # Azul
            EntityType.UNKNOWN: (128, 128, 128),   # Cinza
        }

        for entity in entities:
            color = colors.get(entity.entity_type, (255, 255, 255))
            hb = entity.health_bar

            # Health bar outline
            cv2.rectangle(debug, (hb.x, hb.y),
                          (hb.x + hb.width, hb.y + hb.height), color, 2)

            # Body position crosshair
            cv2.drawMarker(debug, (entity.screen_x, entity.screen_y),
                           color, cv2.MARKER_CROSS, 15, 2)

            # Label
            label = f"{entity.entity_type.name} ({entity.confidence:.0%})"
            if entity.has_level:
                label += " [LVL]"
            cv2.putText(debug, label, (hb.x, hb.y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

        return debug

    def fuse_entities(self, cv_entities: list[DetectedEntity], yolo_entities: list[DetectedEntity]) -> list[DetectedEntity]:
        import math
        final = []
        
        def is_duplicate(y_ent, current_list):
            for existing in current_list:
                dist = math.hypot(existing.screen_x - y_ent.screen_x, existing.screen_y - y_ent.screen_y)
                if dist < 60:  # Distancia euclidiana razoavel para mesmo objeto
                    return True
            return False

        # Priorizar OpenCV quando os sinais locais forem fortes
        for e in cv_entities:
            if e.has_level or e.confidence >= 0.90:
                final.append(e)

        # Sempre aceitar turret/monster vindos do YOLO, salvo duplicata obvia
        for y in yolo_entities:
            if y.entity_type in (EntityType.TURRET, EntityType.MONSTER):
                if not is_duplicate(y, final):
                    final.append(y)

        # Para champion/minion, usar YOLO apenas quando OpenCV estiver fraco/ausente
        for y in yolo_entities:
            if y.entity_type in (EntityType.CHAMPION, EntityType.MINION, EntityType.MINION_SIEGE):
                if not is_duplicate(y, final):
                    final.append(y)

        return final
