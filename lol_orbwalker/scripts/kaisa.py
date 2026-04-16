"""
scripts/kaisa.py — Combo da Kai'Sa (Q priorizado, W contextual, R conservador).
"""
import time
import logging
from typing import Optional

from scripts.base_script import BaseScript
from input.input_simulator import Keyboard, DIK_Q, DIK_W, DIK_R
from vision.entity_classifier import DetectedEntity

logger = logging.getLogger("ExternalOrbwalker.Scripts.Kaisa")


class KaisaScript(BaseScript):
    # Só são usados se sua engine expuser distância real em units.
    Q_RANGE = 600.0
    AA_RANGE = 525.0
    W_RANGE = 3000.0

    # Heurísticas conservadoras.
    GLOBAL_CAST_GAP = 0.075
    W_MIN_DIST = 650.0       # evita W colado sem necessidade
    W_MAX_DIST = 2500.0      # evita snipe sem prediction no limite
    E_FALLBACK_CHANNEL = 0.90

    def __init__(self, riot_api, champ_data):
        super().__init__(riot_api, champ_data)

        self.last_q_time = 0.0
        self.last_w_time = 0.0
        self.last_r_time = 0.0
        self.last_any_cast = 0.0

        # Fallbacks se a engine não expuser rank da spell.
        self.q_cooldown = 8.0
        self.w_cooldown = 18.0

        self.q_cooldowns = [10.0, 9.0, 8.0, 7.0, 6.0]
        self.w_cooldowns = [22.0, 20.0, 18.0, 16.0, 14.0]

        # Tracking do E (Supercharge)
        self.e_charge_end_time = 0.0
        self._e_pressed = False

        # Kai'Sa usa AA normalmente, exceto durante a carga do E.
        self.allow_aa = True

        # Auto-R desligado por padrão: sem plasma/range/segurança do dash,
        # ele tende a piorar a tomada.
        self.auto_r_enabled = False
        self.r_min_plasma_stacks = 1
        self.r_min_dist = 575.0
        self.r_max_dist = 2500.0

        logger.info("Kai'Sa Script loaded")

    def execute(self, target: Optional[DetectedEntity], mode: str) -> bool:
        now = time.perf_counter()

        # Durante a carga do E, bloqueia AA e também evita enfileirar casts ruins.
        if now < self.e_charge_end_time:
            self.allow_aa = False
            return False

        self.allow_aa = True

        if mode != "combo" or not self._is_target_valid(target):
            return False

        # Evita double-cast no mesmo tick / buffer estranho do input.
        if now < self.last_any_cast + self.GLOBAL_CAST_GAP:
            return False

        dist = self._get_target_distance(target)

        # 1) Q primeiro: curto alcance, baixo compromisso.
        if self._should_cast_q(now, target, dist):
            self._tap(DIK_Q)
            self.last_q_time = now
            self.last_any_cast = now
            logger.info("Cast Q (Icathian Rain)")
            return False

        # 2) W contextual: melhor em target travado, já marcado ou fora do AA.
        if self._should_cast_w(now, target, dist):
            self._tap(DIK_W)
            self.last_w_time = now
            self.last_any_cast = now
            logger.info("Cast W (Void Seeker)")
            return True  # W tem cast time; pausa o orbwalker

        # 3) R conservador: desligado por padrão.
        if self.auto_r_enabled and self._should_cast_r(now, target, dist):
            self._tap(DIK_R, fast=True)
            self.last_r_time = now
            self.last_any_cast = now
            logger.info("Cast R (Killer Instinct)")
            return True

        return False

    def _should_cast_q(
        self,
        now: float,
        target: DetectedEntity,
        dist: Optional[float],
    ) -> bool:
        if not self._is_ready(now, self.last_q_time, self._current_q_cooldown()):
            return False

        # Se houver distância confiável, respeita range.
        if dist is not None and dist > self.Q_RANGE:
            return False

        return self._is_visible(target)

    def _should_cast_w(
        self,
        now: float,
        target: DetectedEntity,
        dist: Optional[float],
    ) -> bool:
        if not self._is_ready(now, self.last_w_time, self._current_w_cooldown()):
            return False

        if not self._is_visible(target):
            return False

        plasma = self._get_plasma_stacks(target)
        immobilized = self._is_immobilized(target)

        if dist is not None:
            if dist > self.W_RANGE:
                return False

            # Evita W colado sem motivo.
            if dist < self.W_MIN_DIST and not immobilized and plasma < 2:
                return False

            # Sem prediction, não vale forçar no extremo do range.
            if dist > self.W_MAX_DIST and not immobilized:
                return False

        # Janelas ideais do W.
        if immobilized or plasma >= 2:
            return True

        # Sem distância confiável, mantém fallback permissivo.
        if dist is None:
            return True

        # Fora do range confortável de AA, o W vira gap tool / pick tool.
        return dist > self.AA_RANGE * 1.15

    def _should_cast_r(
        self,
        now: float,
        target: DetectedEntity,
        dist: Optional[float],
    ) -> bool:
        # Mesmo no auto-R, nada de spam de 200 ms.
        if not self._is_ready(now, self.last_r_time, 0.35):
            return False

        plasma = self._get_plasma_stacks(target)
        if plasma < self.r_min_plasma_stacks and not self._has_recent_plasma_mark(target):
            return False

        if dist is not None and not (self.r_min_dist <= dist <= self.r_max_dist):
            return False

        hp_pct = self._get_health_pct(target)
        if hp_pct is not None and hp_pct > 0.55 and plasma < 4:
            return False

        return True

    def _current_q_cooldown(self) -> float:
        level = self._get_spell_level("q")
        if level is None:
            return self.q_cooldown
        return self.q_cooldowns[level - 1]

    def _current_w_cooldown(self) -> float:
        level = self._get_spell_level("w")
        if level is None:
            return self.w_cooldown
        return self.w_cooldowns[level - 1]

    def _get_spell_level(self, spell: str) -> Optional[int]:
        candidates = []

        for owner in (self.champ, self.riot_api):
            if owner is None:
                continue

            for fn_name in ("get_spell_level", "get_ability_level"):
                fn = getattr(owner, fn_name, None)
                if callable(fn):
                    candidates.append((fn, spell))
                    candidates.append((fn, spell.upper()))

            data = getattr(owner, "spell_levels", None)
            if isinstance(data, dict):
                for key in (spell, spell.upper()):
                    value = data.get(key)
                    if isinstance(value, int) and 1 <= value <= 5:
                        return value

        for fn, arg in candidates:
            try:
                value = int(fn(arg))
                if 1 <= value <= 5:
                    return value
            except Exception:
                pass

        return None

    def _is_target_valid(self, target: Optional[DetectedEntity]) -> bool:
        if target is None:
            return False

        if getattr(target, "is_dead", False):
            return False

        health = getattr(target, "health", None)
        if isinstance(health, (int, float)) and health <= 0:
            return False

        return True

    def _is_visible(self, target: DetectedEntity) -> bool:
        for attr in ("visible", "is_visible", "on_screen", "is_on_screen"):
            value = getattr(target, attr, None)
            if value is not None:
                return bool(value)
        return True

    def _is_immobilized(self, target: DetectedEntity) -> bool:
        for attr in ("is_immobilized", "immobilized", "is_cced", "rooted", "stunned"):
            value = getattr(target, attr, None)
            if value is not None:
                return bool(value)
        return False

    def _get_target_distance(self, target: DetectedEntity) -> Optional[float]:
        # Intencionalmente NÃO uso screen_distance/pixels:
        # você mesmo já notou que isso quebra com câmera fora do centro.
        for attr in (
            "distance",
            "distance_to_player",
            "player_distance",
            "world_distance",
        ):
            value = getattr(target, attr, None)
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
        return None

    def _get_health_pct(self, target: DetectedEntity) -> Optional[float]:
        for attr in ("health_percent", "hp_percent", "hp_pct", "health_pct"):
            value = getattr(target, attr, None)
            if isinstance(value, (int, float)):
                if value > 1.0:
                    value = value / 100.0
                return max(0.0, min(1.0, float(value)))

        health = getattr(target, "health", None)
        max_health = getattr(target, "max_health", None)
        if (
            isinstance(health, (int, float))
            and isinstance(max_health, (int, float))
            and max_health > 0
        ):
            return max(0.0, min(1.0, health / max_health))

        return None

    def _get_plasma_stacks(self, target: DetectedEntity) -> int:
        for attr in (
            "plasma_stacks",
            "kaisa_plasma_stacks",
            "passive_stacks",
            "kai_sa_marks",
        ):
            value = getattr(target, attr, None)
            if isinstance(value, int):
                return max(0, value)
        return 0

    def _has_recent_plasma_mark(self, target: DetectedEntity) -> bool:
        for attr in ("has_kaisa_mark", "has_plasma", "is_marked"):
            value = getattr(target, attr, None)
            if value is not None:
                return bool(value)

        last_mark_time = getattr(target, "last_plasma_time", None)
        if isinstance(last_mark_time, (int, float)):
            return (time.perf_counter() - float(last_mark_time)) <= 4.0

        return False

    @staticmethod
    def _is_ready(now: float, last_cast: float, cooldown: float) -> bool:
        return now >= last_cast + cooldown

    @staticmethod
    def _tap(key, fast: bool = False):
        if fast:
            Keyboard.press_key(key, min_delay=0.005, max_delay=0.015)
        else:
            Keyboard.press_key(key)

    def on_key_event(self, key: str, event_type: str):
        now = time.perf_counter()

        if event_type == "down":
            if key == "q":
                self.last_q_time = now
                self.last_any_cast = now
            elif key == "w":
                self.last_w_time = now
                self.last_any_cast = now
            elif key == "r":
                self.last_r_time = now
                self.last_any_cast = now
            elif key == "e" and not self._e_pressed:
                self._e_pressed = True
                self.e_charge_end_time = now + self.E_FALLBACK_CHANNEL
                logger.info("E (Supercharge): AA e casts suspensos durante a carga.")
        elif event_type == "up":
            if key == "e":
                self._e_pressed = False
