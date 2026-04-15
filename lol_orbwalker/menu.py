import threading
import time
import os
import keyboard
import win32gui
import win32con
import win32process

try:
    import dearpygui.dearpygui as dpg
except ImportError:
    print("[FATAL] DearPyGui não está instalado! Rode: pip install dearpygui")
    exit()

from config import VisionConfig, OrbwalkerConfig, AutoSummonerConfig
from main import ExternalOrbwalker

# ESP Overlay desativado temporariamente (Tkinter conflita com DearPyGui na main thread).
# Será reimplementado usando Win32 GDI puro.

class HanbotMenu:
    def __init__(self):
        self.bot = None
        self.esp = None
        self.is_visible = True
        
        dpg.create_context()
        self._build_theme()
        
        with dpg.window(label="ORBWALKER SUITE :: VIP BUILD", tag="Main", width=420, height=650, 
                        no_collapse=True, no_close=True, no_move=True, no_resize=True):
            
            dpg.add_text("    /// EXTERNAL NEURAL ORBWALKER ///", color=(100, 255, 100))
            dpg.add_separator()
            
            dpg.add_text("STATUS: AGUARDANDO INJEÇÃO...", tag="lbl_status", color=(255, 100, 100))
            
            with dpg.group(horizontal=True):
                dpg.add_text("Champ:", color=(150,150,150))
                dpg.add_text("Desconhecido", tag="lbl_champ")
                
            with dpg.group(horizontal=True):
                dpg.add_text("Motor Vital:", color=(150,150,150))
                dpg.add_text("HP: 0% | AS: 0.00", tag="lbl_stats")
                
            with dpg.group(horizontal=True):
                dpg.add_text("Radar Visão:", color=(150,150,150))
                dpg.add_text("Nenhum Alvo (Cego)", tag="lbl_aim", color=(200,200,200))
            
            dpg.add_separator()
            
            # O Botão Matrix
            dpg.add_button(label=">>> INJETAR MOTOR <<<", tag="btn_run", width=-1, height=40, callback=self.toggle_bot)
            
            dpg.add_separator()
            
            # --- Collapsing Headers ---
            with dpg.collapsing_header(label="[+] Core Orbwalker", default_open=True):
                dpg.add_slider_int(label="Ping (ms)", default_value=OrbwalkerConfig.PING_OFFSET_MS, max_value=150, callback=self.on_ping)
                dpg.add_slider_int(label="Windup Delay (ms)", default_value=int(OrbwalkerConfig.WINDUP_BUFFER*1000), max_value=150, callback=self.on_windup)
                dpg.add_slider_int(label="Humanizer Lerdeza (ms)", default_value=int(OrbwalkerConfig.HUMANIZER_MAX*1000), max_value=60, callback=self.on_humanizer)
            
            with dpg.collapsing_header(label="[+] Hardware Vision"):
                dpg.add_checkbox(label="Processamento YOLOv8", default_value=VisionConfig.YOLO_ENABLED, callback=self.on_yolo)
                dpg.add_checkbox(label="YOLO como Fallback Secundário", default_value=VisionConfig.YOLO_FALLBACK_ONLY, callback=self.on_fallback)
            
            with dpg.collapsing_header(label="[+] Auto-Summoner & Defesa"):
                dpg.add_checkbox(label="Defesa Rápida de HP", default_value=AutoSummonerConfig.ENABLED, callback=self.on_autosum)
                dpg.add_slider_int(label="Gatilho Vida (%)", default_value=int(AutoSummonerConfig.ACTIVATION_HP_PERCENT*100), min_value=1, max_value=50, callback=self.on_hp)
                
                with dpg.group(horizontal=True):
                    dpg.add_text("Heal Key:")
                    dpg.add_input_text(default_value=AutoSummonerConfig.HEAL_KEY, width=30, tag="inp_heal", callback=self.on_heal_k)
                with dpg.group(horizontal=True):
                    dpg.add_text("Barrier Key:")
                    dpg.add_input_text(default_value=AutoSummonerConfig.BARRIER_KEY, width=30, tag="inp_barr", callback=self.on_barr_k)

            dpg.add_separator()
            dpg.add_text("HOTKEYS DO SISTEMA:", color=(200, 200, 0))
            dpg.add_text("  [SPACE] Segurar: Combo Orbwalk", color=(180, 180, 180))
            dpg.add_text("  [X] Segurar: Last Hit", color=(180, 180, 180))
            dpg.add_text("  [V] Segurar: Lane Clear", color=(180, 180, 180))
            dpg.add_text("  [C] Segurar: Harass (LH + Poke)", color=(180, 180, 180))
            dpg.add_text("  [INSERT] Ativar/Desativar Menu", color=(100, 255, 100))

        # Viewport de Fundo do OS configurado para grudar e parecer nativo
        dpg.create_viewport(title='Hanbot Overlay', width=420, height=650, always_on_top=True, resizable=False, decorated=False)
        dpg.set_viewport_pos([100, 100]) # Ficará fixo perto da ponta do monitor
        
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_primary_window("Main", True)

        # Captura o HWND real da janela deste processo (mais confiável que FindWindow por título)
        self._hwnd = self._find_own_hwnd()

        self.toggle_requested = False  # Deve ser antes do keyboard hook!

        keyboard.on_press_key('insert', self._on_insert_press)
        threading.Thread(target=self.updater_loop, daemon=True).start()

        # Main Thread Custom Loop — toggle de visibilidade é thread-safe aqui
        try:
            while dpg.is_dearpygui_running():
                if self.toggle_requested:
                    if self._hwnd:
                        if self.is_visible:
                            win32gui.ShowWindow(self._hwnd, win32con.SW_HIDE)
                            self.is_visible = False
                        else:
                            win32gui.ShowWindow(self._hwnd, win32con.SW_SHOW)
                            self.is_visible = True
                    self.toggle_requested = False

                dpg.render_dearpygui_frame()
        except KeyboardInterrupt:
            print("[INFO] Interrompido pelo usuário (Ctrl+C). Encerrando...")
        except Exception as e:
            print(f"[ERRO] Exceção no loop de renderização: {e}")
        finally:
            self.shutdown()

    # (..) Outros métodos mantidos
    def _find_own_hwnd(self):
        """Retorna o HWND da janela principal deste processo (PID-based, sem depender do título)."""
        own_pid = os.getpid()
        found = []

        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == own_pid:
                found.append(hwnd)

        win32gui.EnumWindows(_cb, None)
        return found[0] if found else None

    def _on_insert_press(self, event=None):
        self.toggle_requested = True

    def _build_theme(self):
        """Constrói uma estética Clandestina Dark."""
        with dpg.theme() as global_theme:
            with dpg.theme_component(dpg.mvAll):
                # Fundo Sólido Dark ImGui Clássico
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (25, 25, 25))
                dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, (45, 45, 45))
                dpg.add_theme_color(dpg.mvThemeCol_Button, (60, 60, 60))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (100, 100, 100))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (200, 80, 0)) # Redução no Click (Injeção)
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (80, 80, 80))
                
        dpg.bind_theme(global_theme)

    # ── Callbacks de Configuração ──
    def on_ping(self, sender, app_data): OrbwalkerConfig.PING_OFFSET_MS = app_data
    def on_windup(self, sender, app_data): OrbwalkerConfig.WINDUP_BUFFER = app_data / 1000.0
    def on_humanizer(self, sender, app_data):
        OrbwalkerConfig.HUMANIZER_MAX = app_data / 1000.0
        OrbwalkerConfig.HUMANIZER_MIN = max(0, (app_data - 10) / 1000.0)

    def on_yolo(self, sender, app_data): VisionConfig.YOLO_ENABLED = app_data
    def on_fallback(self, sender, app_data): VisionConfig.YOLO_FALLBACK_ONLY = app_data

    def on_autosum(self, sender, app_data): AutoSummonerConfig.ENABLED = app_data
    def on_hp(self, sender, app_data): AutoSummonerConfig.ACTIVATION_HP_PERCENT = app_data / 100.0
    def on_heal_k(self, sender, app_data): 
        if app_data: AutoSummonerConfig.HEAL_KEY = app_data[-1].lower()
    def on_barr_k(self, sender, app_data): 
        if app_data: AutoSummonerConfig.BARRIER_KEY = app_data[-1].lower()

    # ── Máquina de Estados da Injeção ──
    def toggle_visibility(self, event=None):
        if self.is_visible:
            dpg.hide_viewport()
            self.is_visible = False
        else:
            dpg.show_viewport()
            self.is_visible = True

    def toggle_bot(self):
        if self.bot is None or not self.bot.running:
            dpg.configure_item("btn_run", label=">>> DESLIGAR MOTOR <<<")
            dpg.configure_item("lbl_status", default_value="STATUS: VINCULADO À API E OPERANDO", color=(100, 255, 100))
            
            self.bot = ExternalOrbwalker()
            self.bot.running = True
            
            threading.Thread(target=self.bot.start, args=(False,), daemon=True).start()
        else:
            if self.bot: self.bot._shutdown()
                
            dpg.configure_item("btn_run", label=">>> INJETAR MOTOR <<<")
            dpg.configure_item("lbl_status", default_value="STATUS: DESCONECTADO (SEGURO)", color=(255, 100, 100))
            dpg.configure_item("lbl_champ", default_value="Nenhum")
            dpg.configure_item("lbl_stats", default_value="HP: 0% | AS: 0.00")
            dpg.configure_item("lbl_aim", default_value="Nenhum Alvo (Cego)", color=(200,200,200))

    def updater_loop(self):
        while dpg.is_dearpygui_running():
            if self.bot and self.bot.running:
                # Atualizar Riot API status
                if self.bot.riot_api.connected:
                    if self.bot.riot_api.champion_name:
                        dpg.configure_item("lbl_champ", default_value=f"{self.bot.riot_api.champion_name} (Lvl {self.bot.riot_api.level})")
                    
                    hp = self.bot.riot_api.health_percent * 100
                    ats = self.bot.riot_api.attack_speed
                    dpg.configure_item("lbl_stats", default_value=f"HP: {hp:.0f}% | AS: {ats:.2f}")

                # Vida do Engine de Visão
                if self.bot.engine:
                    target, ttype = self.bot.engine.get_vision_target()
                    if target:
                        col = (255, 100, 100) if ttype == "champion" else (100, 255, 255)
                        dpg.configure_item("lbl_aim", default_value=f"[{ttype.upper()}] Mirando X:{target[0]} Y:{target[1]}", color=col)
                    else:
                        dpg.configure_item("lbl_aim", default_value="Buscando na tela...", color=(150,150,150))
                        
            time.sleep(0.066) # 15 FPS refreshes

    def shutdown(self):
        if self.bot: self.bot._shutdown()
        import keyboard
        try: keyboard.unhook_all()
        except: pass
        dpg.destroy_context()

if __name__ == "__main__":
    try:
        app = HanbotMenu()
    except KeyboardInterrupt:
        print("[INFO] Saída pelo Ctrl+C.")
    except Exception as e:
        import traceback
        print(f"[FATAL] Erro ao inicializar o menu: {e}")
        traceback.print_exc()
