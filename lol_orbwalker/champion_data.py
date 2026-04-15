"""
champion_data.py — Busca dados estáticos do campeão via CommunityDragon.
Fornece: attack speed ratio, windup percent, delay scaling, cast time.
"""
import requests
import logging

from config import CDragonConfig

logger = logging.getLogger("ExternalOrbwalker.ChampionData")


class ChampionData:
    """
    Dados estáticos de um campeão, necessários para calcular windup.
    Busca do CommunityDragon uma vez na inicialização.
    """

    def __init__(self):
        self.champion_name: str = ""
        self.attack_speed_ratio: float = 0.625
        self.attack_cast_time: float = 0.625
        self.attack_total_time: float = 0.625
        self.attack_delay_percent: float = 0.3
        self.attack_delay_scaling: float = 1.0
        self._loaded: bool = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self, raw_champion_name: str) -> bool:
        """
        Fetch dos dados do campeão da CommunityDragon.
        Replica exatamente a lógica do Auto-Kite Bot (Program.cs).

        Args:
            raw_champion_name: Nome interno do campeão (e.g., "Jinx", "KogMaw")

        Returns:
            True se carregou com sucesso
        """
        lower_name = raw_champion_name.lower()
        url = f"{CDragonConfig.BASE_URL}/{lower_name}/{lower_name}.bin.json"

        try:
            resp = requests.get(url, timeout=CDragonConfig.TIMEOUT)
            resp.raise_for_status()
            champ_data = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch champion data for '{raw_champion_name}': {e}")
            return False

        # Buscar root stats
        root_key = f"Characters/{raw_champion_name}/CharacterRecords/Root"
        if root_key not in champ_data:
            # Tentar case-insensitive
            for key in champ_data:
                if key.lower() == root_key.lower():
                    root_key = key
                    break
            else:
                logger.error(f"Root key '{root_key}' not found in champion data")
                return False

        root_stats = champ_data[root_key]
        self.attack_speed_ratio = root_stats.get("attackSpeedRatio", 0.625)

        basic_attack = root_stats.get("basicAttack", {})

        # ── mAttackDelayCastOffsetPercentAttackSpeedRatio ──
        delay_scaling = basic_attack.get("mAttackDelayCastOffsetPercentAttackSpeedRatio")
        if delay_scaling is not None:
            self.attack_delay_scaling = float(delay_scaling)

        # ── mAttackDelayCastOffsetPercent ──
        delay_offset = basic_attack.get("mAttackDelayCastOffsetPercent")

        if delay_offset is None:
            # Fallback: buscar mAttackTotalTime e mAttackCastTime
            total_time = basic_attack.get("mAttackTotalTime")
            cast_time = basic_attack.get("mAttackCastTime")

            if total_time is None and cast_time is None:
                # Último fallback: buscar do spell data
                attack_name = basic_attack.get("mAttackName", "")
                if "BasicAttack" in attack_name:
                    base = attack_name.split("BasicAttack")[0]
                else:
                    base = attack_name
                spell_key = f"Characters/{base}/Spells/{attack_name}"

                # Tentar case-insensitive
                spell_data = None
                for key in champ_data:
                    if key.lower() == spell_key.lower():
                        spell_data = champ_data[key]
                        break

                if spell_data:
                    m_spell = spell_data.get("mSpell", {})
                    offset = m_spell.get("delayCastOffsetPercent", 0.0)
                    self.attack_delay_percent += float(offset)
                    logger.info(f"Used spell fallback for windup: +{offset}")
            else:
                if total_time:
                    self.attack_total_time = float(total_time)
                if cast_time:
                    self.attack_cast_time = float(cast_time)
                if self.attack_total_time != 0:
                    self.attack_delay_percent = self.attack_cast_time / self.attack_total_time
        else:
            self.attack_delay_percent += float(delay_offset)

        self.champion_name = raw_champion_name
        self._loaded = True

        logger.info(
            f"Champion data loaded: {raw_champion_name} | "
            f"AS Ratio: {self.attack_speed_ratio:.4f} | "
            f"Delay%: {self.attack_delay_percent:.4f} | "
            f"Scaling: {self.attack_delay_scaling:.4f} | "
            f"CastTime: {self.attack_cast_time:.4f}"
        )
        return True
