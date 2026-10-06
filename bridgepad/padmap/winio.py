"""Windows backends: XInput for reading the controller, SendInput for typing, user32 for the focused window.

The ctypes structures are defined with explicit sizes so they import (and can be size-checked) on any OS;
the DLLs are only touched when a backend is constructed, which only happens on Windows.
"""
import ctypes
import time
from ctypes import POINTER, Structure, Union, c_int, c_int16, c_int32, c_size_t, c_uint8, c_uint16, c_uint32, c_void_p

from .engine import BaseOutput
from .inputs import PadState
from .keys import KEYS

# --- SendInput structures ---------------------------------------------------

ULONG_PTR = c_size_t  # pointer-sized unsigned, like the Win32 type


class MOUSEINPUT(Structure):
    _fields_ = [("dx", c_int32), ("dy", c_int32), ("mouseData", c_uint32),
                ("dwFlags", c_uint32), ("time", c_uint32), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(Structure):
    _fields_ = [("wVk", c_uint16), ("wScan", c_uint16), ("dwFlags", c_uint32),
                ("time", c_uint32), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(Structure):
    _fields_ = [("uMsg", c_uint32), ("wParamL", c_uint16), ("wParamH", c_uint16)]


class _INPUTUNION(Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", c_uint32), ("u", _INPUTUNION)]


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002
MOUSEEVENTF_MOVE, MOUSEEVENTF_WHEEL = 0x0001, 0x0800
_BUTTON_FLAGS = {  # button -> (down, up)
    "left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040),
}
WHEEL_DELTA = 120


class WinOutput(BaseOutput):
    def __init__(self):
        super().__init__()
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.SendInput.argtypes = (ctypes.c_uint, POINTER(INPUT), c_int)
        self._user32.SendInput.restype = ctypes.c_uint
        self._user32.MapVirtualKeyW.argtypes = (ctypes.c_uint, ctypes.c_uint)
        self._user32.MapVirtualKeyW.restype = ctypes.c_uint
        try:  # ask Windows for 1 ms timer resolution so the 125 Hz polling loop is accurate
            ctypes.WinDLL("winmm").timeBeginPeriod(1)
        except OSError:
            pass
        self.failures = 0

    def _send(self, item):
        sent = self._user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))
        if sent != 1:
            self.failures += 1  # typically a blocked-by-elevation or secure-desktop situation

    def _send_key(self, name, down):
        vk, extended = KEYS[name]
        flags = (KEYEVENTF_EXTENDEDKEY if extended else 0) | (0 if down else KEYEVENTF_KEYUP)
        item = INPUT(type=INPUT_KEYBOARD)
        item.ki = KEYBDINPUT(vk, self._user32.MapVirtualKeyW(vk, 0), flags, 0, 0)
        self._send(item)

    def _send_button(self, button, down):
        item = INPUT(type=INPUT_MOUSE)
        item.mi = MOUSEINPUT(0, 0, 0, _BUTTON_FLAGS[button][0 if down else 1], 0, 0)
        self._send(item)

    def _send_move(self, dx, dy):
        item = INPUT(type=INPUT_MOUSE)
        item.mi = MOUSEINPUT(int(dx), int(dy), 0, MOUSEEVENTF_MOVE, 0, 0)
        self._send(item)

    def _send_wheel(self, notches):
        item = INPUT(type=INPUT_MOUSE)
        item.mi = MOUSEINPUT(0, 0, (int(notches) * WHEEL_DELTA) & 0xFFFFFFFF, MOUSEEVENTF_WHEEL, 0, 0)
        self._send(item)


# --- XInput -----------------------------------------------------------------

class XINPUT_GAMEPAD(Structure):
    _fields_ = [("wButtons", c_uint16), ("bLeftTrigger", c_uint8), ("bRightTrigger", c_uint8),
                ("sThumbLX", c_int16), ("sThumbLY", c_int16), ("sThumbRX", c_int16), ("sThumbRY", c_int16)]


class XINPUT_STATE(Structure):
    _fields_ = [("dwPacketNumber", c_uint32), ("Gamepad", XINPUT_GAMEPAD)]


_XINPUT_BUTTONS = {
    0x0001: "DPAD_UP", 0x0002: "DPAD_DOWN", 0x0004: "DPAD_LEFT", 0x0008: "DPAD_RIGHT",
    0x0010: "MENU", 0x0020: "VIEW", 0x0040: "L3", 0x0080: "R3", 0x0100: "LB", 0x0200: "RB",
    0x0400: "GUIDE", 0x1000: "A", 0x2000: "B", 0x4000: "X", 0x8000: "Y",
}


class XInputPad:
    """Reads the first connected Xbox controller. read() returns a PadState, or None if nothing's plugged in."""

    def __init__(self):
        self._get = None
        self.dll_name = None
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                dll = ctypes.WinDLL(name)
            except OSError:
                continue
            self.dll_name = name
            # Ordinal 100 is the undocumented XInputGetStateEx, the only way to see the Xbox/Guide button.
            for getter in (lambda d=dll: d[100], lambda d=dll: d.XInputGetState):
                try:
                    fn = getter()
                except (AttributeError, OSError):
                    continue
                fn.argtypes = (c_uint32, POINTER(XINPUT_STATE))
                fn.restype = c_uint32
                self._get = fn
                break
            break
        self.index = None
        self._next_scan = 0.0

    @property
    def available(self):
        return self._get is not None

    @property
    def name(self):
        return None if self.index is None else f"Xbox controller {self.index + 1}"

    def _query(self, index):
        state = XINPUT_STATE()
        if self._get(index, ctypes.byref(state)) != 0:
            return None
        g = state.Gamepad
        buttons = frozenset(n for bit, n in _XINPUT_BUTTONS.items() if g.wButtons & bit)

        def axis(v):
            return max(-1.0, v / 32767.0)

        return PadState(buttons, g.bLeftTrigger / 255.0, g.bRightTrigger / 255.0,
                        axis(g.sThumbLX), axis(g.sThumbLY), axis(g.sThumbRX), axis(g.sThumbRY))

    def read(self):
        if self._get is None:
            return None
        if self.index is not None:
            state = self._query(self.index)
            if state is not None:
                return state
            self.index = None
        now = time.monotonic()
        if now < self._next_scan:  # polling empty slots is slow on some drivers; look again once a second
            return None
        self._next_scan = now + 1.0
        for i in range(4):
            state = self._query(i)
            if state is not None:
                self.index = i
                return state
        return None


# --- focused window ---------------------------------------------------------

class ForegroundProbe:
    """Which app is in front? Returns (exe file name, window title)."""

    def __init__(self):
        u, k = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
        u.GetForegroundWindow.restype = c_void_p
        u.GetWindowTextW.argtypes = (c_void_p, ctypes.c_wchar_p, c_int)
        u.GetWindowThreadProcessId.argtypes = (c_void_p, POINTER(c_uint32))
        k.OpenProcess.argtypes = (c_uint32, c_int, c_uint32)
        k.OpenProcess.restype = c_void_p
        k.QueryFullProcessImageNameW.argtypes = (c_void_p, c_uint32, ctypes.c_wchar_p, POINTER(c_uint32))
        k.CloseHandle.argtypes = (c_void_p,)
        self._u, self._k = u, k

    def __call__(self):
        hwnd = self._u.GetForegroundWindow()
        if not hwnd:
            return "", ""
        title = ctypes.create_unicode_buffer(256)
        self._u.GetWindowTextW(hwnd, title, 256)
        pid = c_uint32()
        self._u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        handle = self._k.OpenProcess(0x1000, 0, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            buf, size = ctypes.create_unicode_buffer(1024), c_uint32(1024)
            if self._k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                exe = buf.value.replace("/", "\\").rsplit("\\", 1)[-1]
            self._k.CloseHandle(handle)
        return exe, title.value
