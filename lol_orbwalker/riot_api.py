"""
riot_api.py — Wrapper para a Riot Live Client Data API (porta 2999).
Fornece attack speed em tempo real, nome do campeão, e stats do jogador.
Roda em thread separada para não bloquear o loop principal.
"""
import requests
import urllib3
import threading
import time
import logging

from config import RiotAPIConfig

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("ExternalOrbwalker.RiotAPI")


class RiotAPI:
    """
    Cache thread-safe dos dados da Riot Live Client API.
    Faz polling em background e expõe os dados via properties.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

        # ── Cached data ──
        self._attack_speed: float = 0.625
        self._summoner_name: str = ""
        self._champion_name: str = ""
        self._raw_champion_name: str = ""
        self._current_health: float = 0.0
        self._max_health: float = 1.0
        self._attack_range: float = 550.0
        self._level: int = 1
        self._connected: bool = False

        # ── Session com connection pooling ──
        self._session = requests.Session()
        self._session.verify = False
        self._session.headers.update({"Accept": "application/json"})

    # ─────────── Properties (thread-safe reads) ───────────

    @property
    def attack_speed(self) -> float:
        with self._lock:
            return self._attack_speed

    @property
    def summoner_name(self) -> str:
        with self._lock:
            return self._summoner_name

    @property
    def champion_name(self) -> str:
        with self._lock:
            return self._champion_name

    @property
    def raw_champion_name(self) -> str:
        with self._lock:
            return self._raw_champion_name

    @property
    def current_health(self) -> float:
        with self._lock:
            return self._current_health

    @property
    def max_health(self) -> float:
        with self._lock:
            return self._max_health

    @property
    def health_percent(self) -> float:
        with self._lock:
            if self._max_health <= 0:
                return 1.0
            return self._current_health / self._max_health

    @property
    def level(self) -> int:
        with self._lock:
            return self._level

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def attack_range(self) -> float:
        with self._lock:
            return self._attack_range

    # ─────────── Lifecycle ───────────

    def start(self):
        """Inicia o thread de polling em background."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Riot API polling thread started")

    def stop(self):
        """Para o thread de polling."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Riot API polling thread stopped")

    # ─────────── Internal ───────────

    def _poll_loop(self):
        """Loop principal de polling — roda em thread daemon."""
        initialized = False

        while self._running:
            try:
                # ── Fetch active player data ──
                resp = self._session.get(
                    RiotAPIConfig.ACTIVE_PLAYER,
                    timeout=RiotAPIConfig.TIMEOUT
                )
                active_player = resp.json()

                stats = active_player.get("championStats", {})

                with self._lock:
                    self._attack_speed = float(stats.get("attackSpeed", 0.625))
                    self._current_health = float(stats.get("currentHealth", 0.0))
                    self._max_health = float(stats.get("maxHealth", 1.0))
                    self._attack_range = float(stats.get("attackRange", 550.0))
                    self._level = int(active_player.get("level", 1))
                    self._connected = True

                # ── Initialize champion name (only once) ──
                if not initialized:
                    summoner = active_player.get("summonerName", "") or active_player.get("riotId", "")

                    with self._lock:
                        self._summoner_name = summoner

                    # Fetch player list to get champion name
                    try:
                        resp_list = self._session.get(
                            RiotAPIConfig.PLAYER_LIST,
                            timeout=RiotAPIConfig.TIMEOUT
                        )
                        player_list = resp_list.json()

                        for player in player_list:
                            player_name = player.get("summonerName", "") or player.get("riotId", "")
                            if player_name == summoner:
                                champ_name = player.get("championName", "")
                                raw_name_full = player.get("rawChampionName", "")
                                # rawChampionName format: "game_character_displayname_ChampName"
                                parts = [p for p in raw_name_full.split("_") if p]
                                raw_name = parts[-1] if parts else champ_name

                                with self._lock:
                                    self._champion_name = champ_name
                                    self._raw_champion_name = raw_name

                                logger.info(f"Champion identified: {champ_name} ({raw_name})")
                                initialized = True
                                break
                    except Exception:
                        pass  # Retry next loop

            except requests.exceptions.ConnectionError:
                with self._lock:
                    self._connected = False
            except Exception as e:
                logger.debug(f"Riot API poll error: {e}")
                with self._lock:
                    self._connected = False

            time.sleep(RiotAPIConfig.POLL_INTERVAL)

    def fetch_all_game_data(self) -> dict | None:
        """Fetch completo de allgamedata — uso pontual, não para polling."""
        try:
            resp = self._session.get(
                RiotAPIConfig.ALL_GAME_DATA,
                timeout=RiotAPIConfig.TIMEOUT
            )
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch allgamedata: {e}")
            return None
