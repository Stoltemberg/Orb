"""
input/keyboard.py — Simulação de teclado via DirectInput (SendInput + Scancodes).
Usa a mesma técnica do Auto-Kite Bot para ser reconhecido pelo jogo.
"""
import ctypes
import ctypes.wintypes
import time
import logging

logger = logging.getLogger("ExternalOrbwalker.Keyboard")

# ─────────── Win32 Structures ───────────

ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)
INPUT_KEYBOARD = 1
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("_input", _INPUT),
    ]


# ─────────── Scancode Mapping ───────────

class ScanCode:
    """DirectInput scancodes — mapeamento mais comum."""
    DIK_A = 0x1E
    DIK_S = 0x1F
    DIK_D = 0x20
    DIK_F = 0x21
    DIK_Q = 0x10
    DIK_W = 0x11
    DIK_E = 0x12
    DIK_R = 0x13
    DIK_SPACE = 0x39
    DIK_ESCAPE = 0x01
    DIK_TAB = 0x0F
    DIK_LSHIFT = 0x2A
    DIK_LCONTROL = 0x1D
    DIK_LALT = 0x38
    DIK_1 = 0x02
    DIK_2 = 0x03
    DIK_3 = 0x04
    DIK_4 = 0x05
    DIK_5 = 0x06
    DIK_6 = 0x07
    DIK_7 = 0x08
    DIK_X = 0x2D
    DIK_C = 0x2E
    DIK_V = 0x2F
    DIK_B = 0x30
    DIK_Z = 0x2C


# ─────────── Keyboard Functions ───────────

_SendInput = ctypes.windll.user32.SendInput


def _make_key_input(scan_code: int, flags: int) -> INPUT:
    """Cria uma estrutura INPUT para um evento de teclado."""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = 0
    inp.ki.wScan = scan_code
    inp.ki.dwFlags = flags
    inp.ki.time = 0
    inp.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    return inp


def key_down(scan_code: int):
    """Envia um key down via SendInput com scancode."""
    inp = _make_key_input(scan_code, KEYEVENTF_SCANCODE)
    _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def key_up(scan_code: int):
    """Envia um key up via SendInput com scancode."""
    inp = _make_key_input(scan_code, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP)
    _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def key_press(scan_code: int, hold_time: float = 0.01):
    """Pressiona e solta uma tecla com um tempo de hold."""
    key_down(scan_code)
    time.sleep(hold_time)
    key_up(scan_code)
