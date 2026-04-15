"""
orbwalker/target_selector.py — Seleção inteligente de alvo baseada no modo de jogo.
Prioriza campeões, minions lastáveis, ou qualquer inimigo dependendo da hotkey ativa.
"""
import math
import logging
from vision.entity_classifier import DetectedEntity, EntityType

logger = logging.getLogger("ExternalOrbwalker.TargetSelector")


class TargetSelector:
    """
    Seleciona o melhor alvo para orbwalking baseado no tipo
    de entidade detectada e no modo ativo.
    """

    # Fator de conversão: unidades de range do LoL → pixels na tela.
    # Em LoL@1080p câmera travada, ~1 unidade ≈ 0.85 pixel na profundidade Y.
    # Usamos 0.85 como base; se ainda flickar, reduzir para 0.75.
    RANGE_TO_PIXEL_FACTOR = 0.85

    # Margem de tolerância além do range (evita dropouts na borda)
    RANGE_BUFFER_PX = 60

    # Hysteresis: alvo selecionado só é descartado quando sai do range * HYSTERESIS_FACTOR
    # Evita flickering quando o alvo fica oscilando na borda do range
    HYSTERESIS_FACTOR = 1.20

    def __init__(self, screen_width: int = 1920, screen_height: int = 1080):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.screen_center_x = screen_width // 2
        # O player fica ligeiramente abaixo do centro vertical (UI na base da tela)
        self.screen_center_y = int(screen_height * 0.52)
        self.attack_range_px = 550.0 * self.RANGE_TO_PIXEL_FACTOR
        self._last_target: DetectedEntity | None = None  # Hysteresis state

    def update_attack_range(self, game_range: float):
        """Atualiza o raio de ataque em pixels. Chamado pelo main loop."""
        self.attack_range_px = (game_range * self.RANGE_TO_PIXEL_FACTOR) + self.RANGE_BUFFER_PX

    def _distance_to_center(self, entity: DetectedEntity) -> float:
        """Distância do alvo ao centro da tela (onde o player está ~sempre)."""
        dx = entity.screen_x - self.screen_center_x
        # Health bars ficam acima do corpo: compensar descendo ~30px para o centro do corpo
        dy = (entity.screen_y + 30) - self.screen_center_y
        return math.hypot(dx, dy)

    def _is_in_range(self, entity: DetectedEntity) -> bool:
        """Verifica se a entidade está dentro do attack range (+buffer)."""
        return self._distance_to_center(entity) <= self.attack_range_px

    def _is_in_hysteresis_range(self, entity: DetectedEntity) -> bool:
        """
        Verifica se o alvo atualmente selecionado ainda está dentro do range
        com margem de hysteresis. Só desseleciona quando sair CLARAMENTE.
        """
        return self._distance_to_center(entity) <= self.attack_range_px * self.HYSTERESIS_FACTOR

    def _filter_in_range(self, entities: list[DetectedEntity]) -> list[DetectedEntity]:
        """Filtra apenas entidades dentro do attack range do nosso campeão."""
        return [e for e in entities if self._is_in_range(e)]

    def _distance_to_cursor(self, entity: DetectedEntity, cursor_x: int, cursor_y: int) -> float:
        """Distância do alvo ao cursor do mouse."""
        dx = entity.screen_x - cursor_x
        dy = entity.screen_y - cursor_y
        return math.hypot(dx, dy)

    # ─────────────────────────── Modos de Seleção ───────────────────────────

    def select_combo(self, entities: list[DetectedEntity],
                     cursor_x: int = None, cursor_y: int = None) -> DetectedEntity | None:
        """
        Modo COMBO (Orbwalk): Prioriza campeões inimigos.

        Hysteresis: se o último alvo ainda está no range (com margem), mantém ele
        antes de buscar um novo — evita flickering na borda do range.
        """
        # ── Hysteresis: verificar se o alvo anterior ainda está válido ──
        if self._last_target is not None:
            # Checar se ele ainda existe na lista atual e está em range (com margem)
            matching = [e for e in entities
                       if e.entity_type == EntityType.CHAMPION
                       and abs(e.screen_x - self._last_target.screen_x) < 80
                       and abs(e.screen_y - self._last_target.screen_y) < 80]
            if matching and self._is_in_hysteresis_range(matching[0]):
                self._last_target = matching[0]
                return self._last_target

        # ── Busca novo alvo ──
        champions = [e for e in self._filter_in_range(entities) if e.entity_type == EntityType.CHAMPION]

        if not champions:
            self._last_target = None
            return None

        if cursor_x is not None and cursor_y is not None:
            best = min(champions, key=lambda e: self._distance_to_cursor(e, cursor_x, cursor_y))
        else:
            best = min(champions, key=self._distance_to_center)

        self._last_target = best
        return best

    def select_lasthit(self, entities: list[DetectedEntity],
                       cursor_x: int = None, cursor_y: int = None) -> DetectedEntity | None:
        """
        Modo LASTHIT (X): Prioriza estritamente minions lastáveis.
        Se não hover nenhum lastável na vista, NÃO ataca.
        """
        in_range = self._filter_in_range(entities)
        minions = [e for e in in_range
                   if e.entity_type in (EntityType.MINION, EntityType.MINION_SIEGE)]

        if not minions:
            return None

        # Filtrar apenas minions de fato matáveis (fill_ratio < 0.35)
        # O orbwalker NO LAST HIT MODE não deve atacar minion cheio sob hipótese alguma.
        low_hp_minions = [m for m in minions if m.health_bar.fill_ratio < 0.35]

        if not low_hp_minions:
            return None

        # Ordenar os matáveis por HP (menor vida primeiro) e depois por distância
        if cursor_x is not None and cursor_y is not None:
            return min(low_hp_minions,
                       key=lambda e: (e.health_bar.fill_ratio,
                                      self._distance_to_cursor(e, cursor_x, cursor_y)))
        return min(low_hp_minions, key=lambda e: e.health_bar.fill_ratio)

    def select_laneclear(self, entities: list[DetectedEntity],
                         cursor_x: int = None, cursor_y: int = None) -> DetectedEntity | None:
        """
        Modo LANECLEAR: Ataca qualquer inimigo, prioridade mista.

        Prioridade:
        1. Minions lastáveis (fill < 30%)
        2. Minion siege
        3. Minion normal mais próximo
        4. Campeão (se não há minions)
        """
        in_range = self._filter_in_range(entities)
        minions = [e for e in in_range
                   if e.entity_type in (EntityType.MINION, EntityType.MINION_SIEGE)]
        champions = [e for e in in_range if e.entity_type == EntityType.CHAMPION]

        # Prioridade 1: minions lastáveis
        lasthittable = [m for m in minions if m.health_bar.fill_ratio < 0.30]
        if lasthittable:
            return min(lasthittable, key=lambda e: e.health_bar.fill_ratio)

        # Prioridade 2: siege minions
        sieges = [m for m in minions if m.entity_type == EntityType.MINION_SIEGE]
        if sieges:
            if cursor_x is not None and cursor_y is not None:
                return min(sieges, key=lambda e: self._distance_to_cursor(e, cursor_x, cursor_y))
            return min(sieges, key=self._distance_to_center)

        # Prioridade 3: qualquer minion
        if minions:
            if cursor_x is not None and cursor_y is not None:
                return min(minions, key=lambda e: self._distance_to_cursor(e, cursor_x, cursor_y))
            return min(minions, key=self._distance_to_center)

        # Prioridade 4: campeão (fallback)
        if champions:
            return min(champions, key=self._distance_to_center)

        return None

    def select_harass(self, entities: list[DetectedEntity],
                      cursor_x: int = None, cursor_y: int = None) -> DetectedEntity | None:
        """
        Modo HARASS/MIXED (C): Ataca simultaneamente de forma mista.
        
        Prioridade Exata:
        1. Last hit explícito em minions morrendo (não perde farm)
        2. Campeão inimigo que ouse entrar no attack range
        3. Se não houver farm nem campeão, NÃO ataca (não fica avançando push à toa)
        """
        in_range = self._filter_in_range(entities)
        
        # 1. Tentar farmar primeiro para não perder gold
        minions = [e for e in in_range if e.entity_type in (EntityType.MINION, EntityType.MINION_SIEGE)]
        lasthit_minions = [m for m in minions if m.health_bar.fill_ratio < 0.35]
        if lasthit_minions:
            return min(lasthit_minions, key=lambda e: e.health_bar.fill_ratio)
            
        # 2. Sem minion morrendo? Punir campeão invasor
        champions = [e for e in in_range if e.entity_type == EntityType.CHAMPION]
        if champions:
            if cursor_x is not None and cursor_y is not None:
                return min(champions, key=lambda e: self._distance_to_cursor(e, cursor_x, cursor_y))
            return min(champions, key=self._distance_to_center)
            
        # 3. Nada a fazer, não desperdiçar DPS
        return None

    def select_nearest(self, entities: list[DetectedEntity],
                       cursor_x: int = None, cursor_y: int = None) -> DetectedEntity | None:
        """Seleciona a entidade inimiga mais próxima do cursor, independente do tipo."""
        entities = self._filter_in_range(entities)
        if not entities:
            return None

        if cursor_x is not None and cursor_y is not None:
            return min(entities, key=lambda e: self._distance_to_cursor(e, cursor_x, cursor_y))
        return min(entities, key=self._distance_to_center)
