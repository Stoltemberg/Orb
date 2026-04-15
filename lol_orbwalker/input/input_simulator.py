"""
input/input_simulator.py — Réplica EXATA do InputSimulator do auto-kite-bot.
Usa SendInput com GetMessageExtraInfo() — é o que faz o jogo aceitar o input.
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

# DirectInput scancodes
DIK_Q = 0x10
DIK_W = 0x11
DIK_E = 0x12
DIK_R = 0x13
DIK_A = 0x1E
DIK_S = 0x1F  # S para stop ou summoners se necessário


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", wintypes.WPARAM))


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", wintypes.WPARAM))


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD))


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = (("ki", KEYBDINPUT),
                    ("mi", MOUSEINPUT),
                    ("hi", HARDWAREINPUT))
    _anonymous_ = ("_input",)
    _fields_ = (("type", wintypes.DWORD),
                ("_input", _INPUT))


def _send_input(inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    return user32.SendInput(n, arr, ctypes.sizeof(INPUT))


class Keyboard:
    @staticmethod
    def key_down(scan_code):
        extra = user32.GetMessageExtraInfo()
        ii = INPUT(type=INPUT_KEYBOARD,
                   ki=KEYBDINPUT(wVk=0, wScan=scan_code,
                                dwFlags=KEYEVENTF_KEYDOWN | KEYEVENTF_SCANCODE,
                                time=0, dwExtraInfo=extra))
        _send_input([ii])

    @staticmethod
    def key_up(scan_code):
        extra = user32.GetMessageExtraInfo()
        ii = INPUT(type=INPUT_KEYBOARD,
                   ki=KEYBDINPUT(wVk=0, wScan=scan_code,
                                dwFlags=KEYEVENTF_KEYUP | KEYEVENTF_SCANCODE,
                                time=0, dwExtraInfo=extra))
        _send_input([ii])


class Mouse:
    class Buttons:
        Left = 1
        Right = 2

    @staticmethod
    def mouse_down(button):
        flags = MOUSEEVENTF_LEFTDOWN if button == Mouse.Buttons.Left else MOUSEEVENTF_RIGHTDOWN
        extra = user32.GetMessageExtraInfo()
        ii = INPUT(type=INPUT_MOUSE,
                   mi=MOUSEINPUT(dx=0, dy=0, mouseData=0,
                                 dwFlags=flags, time=0, dwExtraInfo=extra))
        _send_input([ii])

    @staticmethod
    def mouse_up(button):
        flags = MOUSEEVENTF_LEFTUP if button == Mouse.Buttons.Left else MOUSEEVENTF_RIGHTUP
        extra = user32.GetMessageExtraInfo()
        ii = INPUT(type=INPUT_MOUSE,
                   mi=MOUSEINPUT(dx=0, dy=0, mouseData=0,
                                 dwFlags=flags, time=0, dwExtraInfo=extra))
        _send_input([ii])

    @staticmethod
    def mouse_click(button, min_delay=0.015, max_delay=0.035):
        """Click com pequeno delay aleatório para evitar heurística de bot."""
        import time
        import random
        Mouse.mouse_down(button)
        if min_delay > 0:
            time.sleep(random.uniform(min_delay, max_delay))
        Mouse.mouse_up(button)

# Adicionando press_key na classe Keyboard
setattr(Keyboard, 'press_key', lambda scan_code, min_delay=0.015, max_delay=0.035: _keyboard_press(scan_code, min_delay, max_delay))

def _keyboard_press(scan_code, min_delay, max_delay):
    import time
    import random
    Keyboard.key_down(scan_code)
    if min_delay > 0:
        time.sleep(random.uniform(min_delay, max_delay))
    Keyboard.key_up(scan_code)

