"""The background loop: read the controller, check the focused window, drive the engine."""
import sys
import threading
import time

from .engine import BaseOutput
from .profile import target_matches

POLL_HZ = 125
PROBE_EVERY = 0.1   # seconds between focused-window checks


class NullPad:
    """Stand-in on systems without XInput (everything except Windows)."""
    available = False
    name = None

    def read(self):
        return None


class NullOutput(BaseOutput):
    """Stand-in output that discards everything (so the editor can be tried on a non-Windows machine)."""
    def _send_key(self, name, down): pass
    def _send_button(self, button, down): pass
    def _send_move(self, dx, dy): pass
    def _send_wheel(self, notches): pass


def build_backends():
    """-> (pad, output, probe, note). note explains a degraded setup, or is ''."""
    if sys.platform == "win32":
        from .winio import ForegroundProbe, WinOutput, XInputPad
        pad = XInputPad()
        note = "" if pad.available else "XInput isn't available on this PC, so the controller can't be read."
        return pad, WinOutput(), ForegroundProbe(), note
    return NullPad(), NullOutput(), (lambda: ("", "")), "Preview mode: controller input and key sending only work on Windows."


class Runtime:
    def __init__(self, engine, pad, probe):
        self.engine, self.pad, self.probe = engine, pad, probe
        self.foreground = ("", "")
        self.focused = False
        self.connected = False
        self.error = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="padmap-poll", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=1.0)
        self.engine.release_all()   # whatever happened, never leave a key stuck down

    def _loop(self):
        period = 1.0 / POLL_HZ
        next_probe = 0.0
        next_t = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                if now >= next_probe:
                    next_probe = now + PROBE_EVERY
                    self.foreground = self.probe()
                    self.focused = target_matches(self.engine.target, *self.foreground)
                pad = self.pad.read()
                self.connected = pad is not None
                self.engine.tick(pad, self.focused, now)
                self.error = ""
            except Exception as exc:  # keep running; surface it in the UI instead of dying silently
                self.error = f"{type(exc).__name__}: {exc}"
                try:
                    self.engine.release_all()
                except Exception:
                    pass
            next_t += period
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.monotonic()
