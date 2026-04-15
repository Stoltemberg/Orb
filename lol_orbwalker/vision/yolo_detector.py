"""
vision/yolo_detector.py — Detecção de entidades via YOLOv8 (fallback do pipeline híbrido).
Ativado quando o detector OpenCV falha ou retorna 0 entidades.
O caminho do modelo é definido em config.py (VisionConfig.YOLO_MODEL_PATH).
"""
import numpy as np
import logging
import os

from config import VisionConfig
from vision.entity_classifier import EntityType, DetectedEntity
from vision.health_bar_detector import HealthBar

logger = logging.getLogger("ExternalOrbwalker.YOLODetector")


class YOLODetector:
    """
    Detector de entidades baseado em YOLOv8-nano.
    Serve como fallback para o pipeline OpenCV em frames difíceis.

    Para treinar o modelo:
    1. Capturar ~2000-5000 screenshots do jogo
    2. Rotular com LabelImg/CVAT as classes: enemy_champion, enemy_minion, enemy_turret, etc.
    3. Treinar com: yolo detect train data=lol_dataset.yaml model=yolov8n.pt epochs=100
    4. Salvar o best.pt em models/orbwalker_yolo.pt
    """

    # Mapeamento de classe YOLO para EntityType
    CLASS_MAP = {
        0: EntityType.CHAMPION,
        1: EntityType.MINION,
        2: EntityType.TURRET,
        3: EntityType.UNKNOWN,     # ally_minion (não mirar, evita falsos positivos na wave)
        4: EntityType.MONSTER,
    }

    def __init__(self):
        self._model = None
        self._available = False
        self._load_model()

    @property
    def available(self) -> bool:
        return self._available

    def _load_model(self):
        """Tenta carregar o modelo YOLO."""
        model_path = VisionConfig.YOLO_MODEL_PATH

        if not os.path.exists(model_path):
            logger.info(
                f"YOLO model not found at '{model_path}'. "
                f"YOLO fallback disabled. Train a model to enable."
            )
            return

        try:
            from ultralytics import YOLO
            self._model = YOLO(model_path)
            self._available = True
            logger.info(f"YOLO model loaded from '{model_path}'")
        except ImportError:
            logger.warning("ultralytics not installed. YOLO fallback disabled.")
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}")

    def detect(self, frame: np.ndarray) -> list[DetectedEntity]:
        """
        Detecta entidades no frame usando YOLO.

        Args:
            frame: Frame BGR

        Returns:
            Lista de DetectedEntity, ou lista vazia se modelo indisponível
        """
        if not self._available or self._model is None:
            return []

        try:
            results = self._model.predict(
                frame,
                conf=VisionConfig.YOLO_CONFIDENCE,
                verbose=False
            )
        except Exception as e:
            logger.debug(f"YOLO inference failed: {e}")
            return []

        entities = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            for box in boxes:
                # Extrair coordenadas
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                conf = float(box.conf[0])
                cls = int(box.cls[0])

                # Mapear classe
                entity_type = self.CLASS_MAP.get(cls, EntityType.UNKNOWN)

                # Criar HealthBar sintético para compatibilidade
                w = x2 - x1
                h = y2 - y1
                health_bar = HealthBar(
                    x=x1, y=y1,
                    width=w, height=min(h, 10),
                    center_x=(x1 + x2) // 2,
                    center_y=y1,
                    fill_ratio=1.0,  # YOLO não sabe a vida
                    area=w * h
                )

                # Posição estimada do corpo = centro do bounding box
                body_x = (x1 + x2) // 2
                body_y = (y1 + y2) // 2

                entities.append(DetectedEntity(
                    entity_type=entity_type,
                    screen_x=body_x,
                    screen_y=body_y,
                    health_bar=health_bar,
                    confidence=conf,
                    has_level=(entity_type == EntityType.CHAMPION)
                ))

        return entities
