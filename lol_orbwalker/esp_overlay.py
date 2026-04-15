import tkinter as tk
import win32gui
import win32con
import math
import logging

logger = logging.getLogger("ExternalOrbwalker.ESP")

class EspOverlay:
    """
    Roda como um Toplevel sobre o CustomTkinter, criando uma tela transparente 
    clicável que desenha elementos do bot em tempo real via Canvas.
    """
    def __init__(self, bot_ref):
        self.bot = bot_ref
        
        self.window = tk.Tk()
        self.window.title("ESP Overlay")
        self.window.attributes("-fullscreen", True)
        self.window.attributes("-topmost", True)
        
        # Transparent Color: Preto puro.
        self.transparent_color = 'black'
        self.window.attributes("-transparentcolor", self.transparent_color)
        self.window.config(bg=self.transparent_color)
        
        # Faz a janela não bloquear cliques do mouse (Click-Through)
        self.window.update()
        hwnd = self.window.winfo_id()
        try: 
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)
        except Exception as e:
            pass

        self.canvas = tk.Canvas(self.window, bg=self.transparent_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.width = self.window.winfo_screenwidth()
        self.height = self.window.winfo_screenheight()
        
        self.running = False

    def start(self):
        self.running = True
        self.window.deiconify()
        self.window.update()

    def stop(self):
        self.running = False
        self.window.withdraw()
        self.canvas.delete("all")
        self.window.update()

    def draw_frame(self):
        """Metódo manual síncrono para ser chamado no loop de outra UI."""
        if not self.running or not self.bot or not self.bot.running:
            return
            
        self.canvas.delete("all") 
        cx, cy = self.width // 2, self.height // 2
        
        if self.bot.champion_data and self.bot.champion_data.attack_range > 0:
            pixel_radius = int(self.bot.champion_data.attack_range * 0.9)
            circle_color = "#2ecc71" if (self.bot.engine and self.bot.engine.active) else "white"
            self.canvas.create_oval(
                cx - pixel_radius, cy - pixel_radius, cx + pixel_radius, cy + pixel_radius,
                outline=circle_color, width=1, dash=(5, 5)
            )
        
        if self.bot.engine:
            target, ttype = self.bot.engine.get_vision_target()
            if target:
                tx, ty = target
                color = "red" if ttype.name == "CHAMPION" else "cyan"
                self.canvas.create_rectangle(tx - 25, ty - 25, tx + 25, ty + 25, outline=color, width=2)
                self.canvas.create_line(cx, cy, tx, ty, fill=color, width=1, dash=(2, 4))

        self.window.update()

