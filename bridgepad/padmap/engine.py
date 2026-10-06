"""The mapping engine: turns controller readings into key/mouse output according to a profile.

Platform-independent. It talks to an Output (real on Windows, a recorder in tests) and is driven by
calling tick() ~100+ times a second with the latest controller reading.
"""
import copy
import math
import threading
import time

from .inputs import STICK_INPUTS, PadState
from .keys import parse_combo, parse_macro

MOUSE_PX_PER_SEC = 1400   # full-tilt pointer speed at speed 1.0
SCROLL_NOTCHES_PER_SEC = 14
MACRO_STEP_GAP = 0.02     # pause between macro steps so apps see distinct key events
_DIRS = {"UP": 1, "DOWN": 1, "LEFT": 0, "RIGHT": 0}


class BaseOutput:
    """Reference-counts held keys and buttons so overlapping bindings can't release each other's keys.
    Subclasses implement the _send_* hooks."""

    def __init__(self):
        self._keys = {}
        self._buttons = {}

    def key_down(self, name):
        n = self._keys.get(name, 0)
        self._keys[name] = n + 1
        if n == 0:
            self._send_key(name, True)

    def key_up(self, name):
        n = self._keys.get(name, 0)
        if n <= 0:
            return
        if n == 1:
            del self._keys[name]
            self._send_key(name, False)
        else:
            self._keys[name] = n - 1

    def mouse_down(self, button):
        n = self._buttons.get(button, 0)
        self._buttons[button] = n + 1
        if n == 0:
            self._send_button(button, True)

    def mouse_up(self, button):
        n = self._buttons.get(button, 0)
        if n <= 0:
            return
        if n == 1:
            del self._buttons[button]
            self._send_button(button, False)
        else:
            self._buttons[button] = n - 1

    def mouse_move(self, dx, dy):
        if dx or dy:
            self._send_move(dx, dy)

    def wheel(self, notches):
        if notches:
            self._send_wheel(notches)

    def release_all(self):
        """Let go of everything still held. Called on pause, focus loss, profile change and exit."""
        for name in reversed(list(self._keys)):
            self._send_key(name, False)
        for button in list(self._buttons):
            self._send_button(button, False)
        self._keys.clear()
        self._buttons.clear()

    def _send_key(self, name, down): raise NotImplementedError
    def _send_button(self, button, down): raise NotImplementedError
    def _send_move(self, dx, dy): raise NotImplementedError
    def _send_wheel(self, notches): raise NotImplementedError


# --- runners: one per input currently held down -----------------------------

class _KeyRunner:
    def __init__(self, out, keys, mode, repeat_ms, delay_ms):
        self.out, self.keys, self.mode = out, keys, mode
        self.repeat, self.delay = repeat_ms / 1000.0, delay_ms / 1000.0
        self.due = None

    def _tap(self):
        for k in self.keys:
            self.out.key_down(k)
        for k in reversed(self.keys):
            self.out.key_up(k)

    def press(self, now):
        if self.mode == "hold":
            for k in self.keys:
                self.out.key_down(k)
        else:
            self._tap()
            if self.mode == "repeat":
                self.due = now + self.delay

    def tick(self, now):
        if self.due is not None and now >= self.due:
            self._tap()
            self.due = now + self.repeat if now - self.due > self.repeat else self.due + self.repeat

    def release(self):
        if self.mode == "hold":
            for k in reversed(self.keys):
                self.out.key_up(k)


class _MouseRunner:
    def __init__(self, out, button, mode):
        self.out, self.button, self.mode = out, button, mode

    def press(self, now):
        self.out.mouse_down(self.button)
        if self.mode != "hold":
            self.out.mouse_up(self.button)

    def tick(self, now):
        pass

    def release(self):
        if self.mode == "hold":
            self.out.mouse_up(self.button)


class _ScrollRunner:
    def __init__(self, out, direction, repeat_ms, delay_ms):
        self.out = out
        self.step = 1 if direction == "up" else -1
        self.repeat, self.delay = repeat_ms / 1000.0, delay_ms / 1000.0
        self.due = None

    def press(self, now):
        self.out.wheel(self.step)
        if self.repeat > 0:
            self.due = now + self.delay

    def tick(self, now):
        if self.due is not None and now >= self.due:
            self.out.wheel(self.step)
            self.due = now + self.repeat if now - self.due > self.repeat else self.due + self.repeat

    def release(self):
        pass


class _MacroRun:
    def __init__(self, out, steps, owner, now):
        self.out, self.steps, self.owner = out, steps, owner
        self.i, self.due = 0, now

    def advance(self, now):
        """Run every step that's due. Returns True once the macro has finished."""
        while self.i < len(self.steps) and now >= self.due:
            kind, arg = self.steps[self.i]
            self.i += 1
            if kind == "wait":
                self.due = now + arg
                continue
            if kind == "combo":
                for k in arg:
                    self.out.key_down(k)
                for k in reversed(arg):
                    self.out.key_up(k)
            elif kind == "click":
                self.out.mouse_down(arg)
                self.out.mouse_up(arg)
            elif kind == "scroll":
                self.out.wheel(arg)
            self.due = now + MACRO_STEP_GAP
        return self.i >= len(self.steps)


# --- compiling profiles -----------------------------------------------------

_BLOCK = object()   # explicit "do nothing": stops a layer inheriting from Main


def _compile(binding):
    kind = binding.get("type", "none")
    if kind == "none":
        return _BLOCK
    try:
        if kind == "key":
            return ("key", parse_combo(binding["keys"]), binding["mode"],
                    binding["repeat_ms"], binding["delay_ms"])
        if kind == "macro":
            return ("macro", parse_macro(binding["steps"]))
        if kind == "mouse":
            return ("mouse", binding["button"], binding["mode"])
        if kind == "scroll":
            return ("scroll", binding["direction"], binding["repeat_ms"], binding["delay_ms"])
    except (KeyError, ValueError):
        pass
    return _BLOCK  # a broken binding does nothing rather than crashing the engine


class Engine:
    def __init__(self, output):
        self.out = output
        self.enabled = True
        self._lock = threading.RLock()
        self._profile = None
        self._layers = []
        self._prev = set()
        self._runners = {}
        self._macros = []
        self._stick_dirs = {"left": set(), "right": set()}
        self._trig = {"LT": False, "RT": False}
        self._frac = {"left": [0.0, 0.0], "right": [0.0, 0.0]}
        self._last_t = None
        # read by the UI via snapshot()
        self.live = False
        self.layer = 0
        self.pad = PadState()

    # -- configuration --
    @property
    def target(self):
        with self._lock:
            return dict(self._profile["target"]) if self._profile else {"only_when_focused": False, "match": ""}

    def set_profile(self, profile):
        with self._lock:
            self._stop_all()
            self._profile = copy.deepcopy(profile)
            self._layers = [
                {"activator": layer["activator"],
                 "specs": {i: _compile(b) for i, b in layer["bindings"].items()}}
                for layer in self._profile["layers"]
            ]
            self.layer = 0

    def set_enabled(self, enabled):
        with self._lock:
            self.enabled = enabled
            if not enabled:
                self._stop_all()

    def release_all(self):
        with self._lock:
            self._stop_all()

    def snapshot(self):
        with self._lock:
            return {"live": self.live, "layer": self.layer, "pad": self.pad, "pressed": frozenset(self._prev)}

    # -- per-tick work --
    def tick(self, pad, focused, now):
        """pad: PadState, or None if no controller. focused: is the target app in front."""
        with self._lock:
            if self._profile is None:
                return
            dt = 0.0 if self._last_t is None else min(now - self._last_t, 0.1)
            self._last_t = now
            pressed = self._derive(pad)
            self.pad = pad or PadState()
            self.live = bool(self.enabled and focused and pad is not None)
            if not self.live:
                # Swallow press/release edges while paused so nothing fires the moment we resume.
                self._stop_all()
                self._prev = pressed
                self.layer = 0
                return

            self.layer = self._active_layer(pressed)
            for input_id in self._prev - pressed:
                self._release(input_id)
            for input_id in sorted(pressed - self._prev):
                self._press(input_id, now)
            self._prev = pressed

            for runner in list(self._runners.values()):
                runner.tick(now)
            self._macros = [m for m in self._macros if not m.advance(now)]
            self._analog(pad, dt)

    def _derive(self, pad):
        """Controller reading -> the set of inputs currently 'down' (including triggers and stick directions)."""
        if pad is None:
            self._trig = {"LT": False, "RT": False}
            self._stick_dirs = {"left": set(), "right": set()}
            return set()
        pressed = set(pad.buttons)
        thr = self._profile["trigger_threshold"]
        for name, value in (("LT", pad.lt), ("RT", pad.rt)):
            on = self._trig[name]
            self._trig[name] = value > max(0.05, thr - 0.12) if on else value >= thr
            if self._trig[name]:
                pressed.add(name)
        for side, (x, y) in (("left", (pad.lx, pad.ly)), ("right", (pad.rx, pad.ry))):
            cfg = self._profile["sticks"][side]
            if cfg["mode"] != "keys":
                self._stick_dirs[side] = set()
                continue
            dirs = self._stick_directions(self._stick_dirs[side], x, y, cfg)
            self._stick_dirs[side] = dirs
            pressed.update(STICK_INPUTS[side][("UP", "DOWN", "LEFT", "RIGHT").index(d)] for d in dirs)
        return pressed

    @staticmethod
    def _stick_directions(prev, x, y, cfg):
        mag = math.hypot(x, y)
        # Hysteresis: need to push past the deadzone to start, but only drop below 80% to stop.
        if mag < cfg["deadzone"] * (0.8 if prev else 1.0):
            return set()
        if cfg["four_way"]:
            # Pick the dominant axis, and favour whatever axis we were already on to avoid flicker.
            if prev & {"LEFT", "RIGHT"}:
                horizontal = abs(x) >= abs(y) * 0.8
            elif prev & {"UP", "DOWN"}:
                horizontal = abs(x) > abs(y) * 1.25
            else:
                horizontal = abs(x) >= abs(y)
            if horizontal:
                return {"RIGHT" if x > 0 else "LEFT"}
            return {"UP" if y > 0 else "DOWN"}
        dirs = set()
        if abs(x) > 0.38 * mag:
            dirs.add("RIGHT" if x > 0 else "LEFT")
        if abs(y) > 0.38 * mag:
            dirs.add("UP" if y > 0 else "DOWN")
        return dirs

    def _active_layer(self, pressed):
        for i in range(len(self._layers) - 1, 0, -1):
            if self._layers[i]["activator"] in pressed:
                return i
        return 0

    def _lookup(self, input_id):
        spec = self._layers[self.layer]["specs"].get(input_id)
        if spec is None and self.layer > 0:
            spec = self._layers[0]["specs"].get(input_id)
        return spec

    def _press(self, input_id, now):
        if any(layer["activator"] == input_id for layer in self._layers[1:]):
            return  # holding a layer button changes layers; it doesn't fire its own binding
        spec = self._lookup(input_id)
        if spec is None or spec is _BLOCK:
            return
        kind = spec[0]
        if kind == "macro":
            if not any(m.owner == input_id for m in self._macros):
                run = _MacroRun(self.out, spec[1], input_id, now)
                if not run.advance(now):
                    self._macros.append(run)
            return
        runner = {
            "key": lambda: _KeyRunner(self.out, *spec[1:]),
            "mouse": lambda: _MouseRunner(self.out, *spec[1:]),
            "scroll": lambda: _ScrollRunner(self.out, *spec[1:]),
        }[kind]()
        runner.press(now)
        self._runners[input_id] = runner

    def _release(self, input_id):
        runner = self._runners.pop(input_id, None)
        if runner:
            runner.release()

    def _analog(self, pad, dt):
        for side, (x, y) in (("left", (pad.lx, pad.ly)), ("right", (pad.rx, pad.ry))):
            cfg = self._profile["sticks"][side]
            frac = self._frac[side]
            mag = math.hypot(x, y)
            if cfg["mode"] == "keys" or mag <= cfg["deadzone"]:
                frac[0] = frac[1] = 0.0
                continue
            strength = min(1.0, (mag - cfg["deadzone"]) / (1.0 - cfg["deadzone"]))
            if cfg["mode"] == "mouse":
                speed = MOUSE_PX_PER_SEC * cfg["speed"] * strength ** 2  # squared: fine control near the centre
                frac[0] += x / mag * speed * dt
                frac[1] -= y / mag * speed * dt
                dx, dy = int(frac[0]), int(frac[1])
                frac[0] -= dx
                frac[1] -= dy
                self.out.mouse_move(dx, dy)
            else:
                frac[0] += y / mag * SCROLL_NOTCHES_PER_SEC * cfg["speed"] * strength * dt
                n = int(frac[0])
                frac[0] -= n
                self.out.wheel(n)

    def _stop_all(self):
        for runner in self._runners.values():
            runner.release()
        self._runners.clear()
        self._macros.clear()
        for f in self._frac.values():
            f[0] = f[1] = 0.0
        self.out.release_all()
