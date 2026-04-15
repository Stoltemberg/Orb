"""
config.py — Configurações do lol_trainer.
Projeto independente de treinamento YOLO para o orbwalker.
"""
import os

# ── Diretório base deste projeto ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Caminho para a pasta inbox do orbwalker ──
# O bot salva screenshots aqui durante o jogo.
# Ajuste se o orbwalker estiver em outro local.
ORBWALKER_INBOX = r"C:\Users\Administrator\Desktop\lol_orbwalker\captures\inbox"

# ── Caminho para exportar o best.pt para o orbwalker ──
# Após treino, o best.pt é copiado automaticamente para models/ do orbwalker.
ORBWALKER_MODELS_DIR = r"C:\Users\Administrator\Desktop\lol_orbwalker\models"

# ── Dataset ──
DATASET_DIR  = os.path.join(BASE_DIR, "dataset")
DATASET_YAML = os.path.join(DATASET_DIR, "lol_dataset.yaml")
INBOX_DIR    = os.path.join(DATASET_DIR, "inbox")

# ── Runs (saída do YOLO) ──
RUNS_DIR = os.path.join(BASE_DIR, "runs", "detect")

# ── Classes YOLO ──
YOLO_CLASSES = {
    0: "enemy_champion",
    1: "enemy_minion",
    2: "enemy_turret",
    3: "ally_minion",
    4: "jungle_monster",
}

# ── Configurações de treino padrão ──
class TrainDefaults:
    MODEL      = "yolov8s.pt"
    EPOCHS     = 150
    IMGSZ      = 416
    BATCH      = 16
    NAME       = "lol_orbwalker"
    CONFIDENCE = 0.40          # Confiança mínima para auto-label
