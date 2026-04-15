"""
input/mouse.py — Simulação de mouse via SendInput (DirectInput-compatible).
Suporta click esquerdo, click direito, e movimentação.
"""
import ctypes
import ctypes.wintypes
import time
import logging

logger = logging.getLogger("ExternalOrbwalker.Mouse")

# ─────────── Win32 Constants ───────────

INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000

ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("_input", _INPUT),
    ]


# ─────────── Internal ───────────

_SendInput = ctypes.windll.user32.SendInput
_user32 = ctypes.windll.user32


def _make_mouse_input(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    """Cria uma estrutura INPUT para um evento de mouse."""
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx = dx
    inp.mi.dy = dy
    inp.mi.mouseData = 0
    inp.mi.dwFlags = flags
    inp.mi.time = 0
    inp.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    return inp


# ─────────── Public API ───────────

def get_cursor_pos() -> tuple[int, int]:
    """Retorna a posição atual do cursor (x, y)."""
    point = ctypes.wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def set_cursor_pos(x: int, y: int):
    """Move o cursor para uma posição absoluta."""
    _user32.SetCursorPos(x, y)


def left_click(hold_time: float = 0.005):
    """Click esquerdo na posição atual do cursor."""
    inp_down = _make_mouse_input(MOUSEEVENTF_LEFTDOWN)
    _SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
    time.sleep(hold_time)
    inp_up = _make_mouse_input(MOUSEEVENTF_LEFTUP)
    _SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))


def right_click(hold_time: float = 0.005):
    """Click direito na posição atual do cursor."""
    inp_down = _make_mouse_input(MOUSEEVENTF_RIGHTDOWN)
    _SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
    time.sleep(hold_time)
    inp_up = _make_mouse_input(MOUSEEVENTF_RIGHTUP)
    _SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))


def click_at(x: int, y: int, button: str = "left", restore: bool = True):
    """
    Move o cursor para (x, y), dá click, e opcionalmente restaura posição.

    Args:
        x, y: Posição do click
        button: "left" ou "right"
        restore: Se True, restaura a posição original do cursor
    """
    original_pos = get_cursor_pos() if restore else None

    set_cursor_pos(x, y)
    time.sleep(0.002)  # Pequeno delay para o SetCursorPos registrar

    if button == "left":
        left_click()
    else:
        right_click()

    if restore and original_pos:
        time.sleep(0.002)
        set_cursor_pos(*original_pos)


def attack_move_click(x: int, y: int, restore: bool = True):
    """
    Executa Attack Move Click na posição (x, y).
    Equivale a: mover cursor → A + Left Click → restaurar cursor.

    Esta é a ação principal do orbwalker para atacar um alvo específico.
    """
    from input.keyboard import key_down, key_up, ScanCode

    original_pos = get_cursor_pos() if restore else None

    # 1. Mover cursor para o alvo
    set_cursor_pos(x, y)
    time.sleep(0.002)

    # 2. A + Left Click (Attack Move)
    key_down(ScanCode.DIK_A)
    left_click()
    key_up(ScanCode.DIK_A)

    # 3. Restaurar cursor
    if restore and original_pos:
        time.sleep(0.002)
        set_cursor_pos(*original_pos)
