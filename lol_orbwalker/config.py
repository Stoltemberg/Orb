"""
config.py — Configurações do lol_orbwalker.
Bot de gameplay externo baseado em visão computacional.
"""
import os

# ── Diretório base deste projeto ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────── Orbwalker ───────────────────────────
class OrbwalkerConfig:
    PING_OFFSET_MS  = 65       # Compensação de latência (ms)
    WINDUP_BUFFER   = 0.05     # Buffer extra no windup (segundos)
    HUMANIZER_MIN   = 0.0      # Delay mínimo de humanização (segundos)
    HUMANIZER_MAX   = 0.03     # Delay máximo de humanização (segundos)
    ATTACK_KEY      = "a"      # Tecla de attack-move

# ─────────────────────────── Vision ───────────────────────────
class VisionConfig:
    REFERENCE_WIDTH  = 2560
    REFERENCE_HEIGHT = 1080
    TARGET_FPS       = 30

    # Tamanhos de health bar (calibrados para 1080p)
    MIN_HP_WIDTH  = 30
    MAX_HP_WIDTH  = 200
    MIN_HP_HEIGHT = 4
    MAX_HP_HEIGHT = 14

    CHAMP_MIN_WIDTH = 75    # px mínimo para ser campeão
    LEVEL_CHECK_SIZE = 14

    # ── Ranges HSV da health bar vermelha inimiga ──
    # O vermelho no HSV wrapa: [0-10] e [160-180]
    ENEMY_RED_LOWER_1 = [0,   120,  70]   # Faixa baixa do vermelho
    ENEMY_RED_UPPER_1 = [10,  255, 255]
    ENEMY_RED_LOWER_2 = [160, 120,  70]   # Faixa alta do vermelho
    ENEMY_RED_UPPER_2 = [180, 255, 255]

    # ── Filtro de aspect ratio (barras são sempre horizontais) ──
    MIN_ASPECT_RATIO = 3.0    # Mínimo: largura/altura
    MAX_ASPECT_RATIO = 60.0   # Máximo: evita linhas horizontais do HUD

    # ── Tamanho mínimo de barra de minion ──
    MINION_BAR_MIN_WIDTH = 20   # px (em 1080p)

    # ── Thresholds de largura para classificação de entidade (em 1080p) ──
    # Campeão full HP ≈ 103px de barra vermelha (encolhe com HP perdido)
    CHAMPION_BAR_MIN_WIDTH    = 62   # px — acima disso = campeão certo
    MINION_SIEGE_BAR_MIN_WIDTH = 42  # px — zona cinza: siege ou campeão com HP baixo
    MINION_BAR_MAX_WIDTH      = 61   # px — abaixo disso = minion comum

    # ── Offset Y do corpo (abaixo da health bar) ──
    # Usado para estimar onde clicar no corpo da unidade
    BODY_OFFSET_Y = 35  # px (em 1080p) — body fica ~35px abaixo do centro da barra

    # best.pt é copiado pelo lol_trainer automaticamente após treino
    YOLO_MODEL_PATH   = os.path.join(BASE_DIR, "models", "best.pt")
    YOLO_CONFIDENCE   = 0.50
    YOLO_ENABLED      = True
    YOLO_FALLBACK_ONLY = False

    # ── Classes ──
    YOLO_CLASSES = {
        0: "enemy_champion",
        1: "enemy_minion",
        2: "enemy_turret",
        3: "ally_minion",
        4: "jungle_monster",
    }

# ─────────────────────────── Shadow Capture ───────────────────────────
class CaptureConfig:
    # Screenshots capturadas durante o jogo → enviadas ao lol_trainer
    INBOX_DIR        = os.path.join(BASE_DIR, "captures", "inbox")
    CAPTURE_PROB     = 0.01   # 1% das frames quando YOLO ativo
    CAPTURE_PROB_RAW = 0.05   # 5% das frames quando sem YOLO

# ─────────────────────────── CommunityDragon ───────────────────────────
class CDragonConfig:
    BASE_URL = "https://raw.communitydragon.org/latest/game/data/characters"
    TIMEOUT  = 5.0   # Timeout para requisições HTTP (segundos)

# ─────────────────────────── Riot API ───────────────────────────
class RiotAPIConfig:
    BASE_URL     = "https://127.0.0.1:2999"
    ACTIVE_PLAYER = f"{BASE_URL}/liveclientdata/activeplayer"
    PLAYER_LIST   = f"{BASE_URL}/liveclientdata/playerlist"
    ALL_GAME_DATA = f"{BASE_URL}/liveclientdata/allgamedata"
    TIMEOUT       = 0.5
    POLL_INTERVAL = 1.0

# ─────────────────────────── Auto Summoner ───────────────────────────
class AutoSummonerConfig:
    ENABLED             = False
    ACTIVATION_HP_PERCENT = 0.30
    HEAL_KEY            = "d"
    BARRIER_KEY         = "f"
