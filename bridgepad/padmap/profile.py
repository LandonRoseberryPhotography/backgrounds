"""Profiles: what every controller input does. Plain dicts so they round-trip through JSON."""
import copy
import json
import os
import re

from .inputs import ACTIVATORS, IDS, LABELS
from .keys import format_combo, parse_combo, parse_macro

STICK_DEFAULTS = {"mode": "keys", "deadzone": 0.35, "four_way": True, "speed": 1.0}
STICK_MODES = ("keys", "mouse", "scroll")
KEY_MODES = ("tap", "hold", "repeat")
BINDING_TYPES = ("none", "key", "macro", "mouse", "scroll")
DEFAULT_REPEAT_MS = 150
DEFAULT_DELAY_MS = 350


# --- bindings ---------------------------------------------------------------

def key(keys, mode="tap", repeat_ms=DEFAULT_REPEAT_MS, delay_ms=DEFAULT_DELAY_MS):
    return {"type": "key", "keys": keys, "mode": mode, "repeat_ms": repeat_ms, "delay_ms": delay_ms}


def _num(value, default, lo, hi, cast=float):
    try:
        v = cast(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def clean_binding(raw):
    """Validate one binding and fill in defaults. Raises ValueError if it can't work."""
    if not isinstance(raw, dict):
        raise ValueError("binding must be an object")
    kind = raw.get("type", "none")
    if kind == "none":
        return {"type": "none"}
    if kind == "key":
        keys = str(raw.get("keys", "")).strip()
        parse_combo(keys)
        mode = raw.get("mode", "tap")
        return {
            "type": "key", "keys": keys, "mode": mode if mode in KEY_MODES else "tap",
            "repeat_ms": _num(raw.get("repeat_ms"), DEFAULT_REPEAT_MS, 20, 5000, int),
            "delay_ms": _num(raw.get("delay_ms"), DEFAULT_DELAY_MS, 0, 5000, int),
        }
    if kind == "macro":
        steps = str(raw.get("steps", "")).strip()
        parse_macro(steps)
        return {"type": "macro", "steps": steps}
    if kind == "mouse":
        button = raw.get("button", "left")
        mode = raw.get("mode", "tap")
        return {
            "type": "mouse", "button": button if button in ("left", "right", "middle") else "left",
            "mode": mode if mode in ("tap", "hold") else "tap",
        }
    if kind == "scroll":
        direction = raw.get("direction", "down")
        return {
            "type": "scroll", "direction": direction if direction in ("up", "down") else "down",
            "repeat_ms": _num(raw.get("repeat_ms"), 80, 0, 5000, int),
            "delay_ms": _num(raw.get("delay_ms"), DEFAULT_DELAY_MS, 0, 5000, int),
        }
    raise ValueError(f"unknown binding type '{kind}'")


def describe(binding):
    """Short human-readable summary for the mapping table."""
    if binding is None:
        return ""
    kind = binding.get("type", "none")
    if kind == "none":
        return "Do nothing (blocked)"
    if kind == "key":
        try:
            text = format_combo(parse_combo(binding["keys"]))
        except ValueError:
            return f"{binding['keys']} (invalid)"
        mode = binding.get("mode", "tap")
        if mode == "hold":
            return f"{text}  (hold)"
        if mode == "repeat":
            return f"{text}  (repeat {binding.get('repeat_ms', DEFAULT_REPEAT_MS)} ms)"
        return text
    if kind == "macro":
        try:
            n = len(parse_macro(binding["steps"]))
        except ValueError:
            return "Macro (invalid)"
        return f"Macro, {n} step{'s' if n != 1 else ''}"
    if kind == "mouse":
        hold = "  (hold)" if binding.get("mode") == "hold" else ""
        return f"{binding.get('button', 'left').capitalize()} click{hold}"
    if kind == "scroll":
        rep = "  (repeat)" if binding.get("repeat_ms", 0) else ""
        return f"Scroll {binding.get('direction', 'down')}{rep}"
    return "?"


# --- profiles ---------------------------------------------------------------

def new_profile(name="New profile"):
    return {
        "name": name,
        "target": {"only_when_focused": True, "match": "bridge"},
        "sticks": {"left": dict(STICK_DEFAULTS), "right": dict(STICK_DEFAULTS)},
        "trigger_threshold": 0.5,
        "layers": [{"name": "Main", "activator": None, "bindings": {}}],
    }


def bridge_profile():
    """Starter profile: step through backgrounds with the D-pad/stick/bumpers, Space and Esc for preview."""
    p = new_profile("Bridge Backgrounds")
    main = p["layers"][0]["bindings"]
    for input_id, name in [
        ("DPAD_UP", "up"), ("DPAD_DOWN", "down"), ("DPAD_LEFT", "left"), ("DPAD_RIGHT", "right"),
        ("LS_UP", "up"), ("LS_DOWN", "down"), ("LS_LEFT", "left"), ("LS_RIGHT", "right"),
        ("LB", "left"), ("RB", "right"),
    ]:
        main[input_id] = key(name, "repeat")
    main["A"] = key("space")      # full-screen preview on/off
    main["B"] = key("esc")        # back out of full screen / slideshow
    p["sticks"]["right"]["mode"] = "scroll"
    p["sticks"]["right"]["deadzone"] = 0.25
    # Hold LT for a second layer: jump to the start/end, or page through a big folder.
    shift = {"name": "Shift (hold LT)", "activator": "LT", "bindings": {
        "DPAD_LEFT": key("home"), "DPAD_RIGHT": key("end"),
        "DPAD_UP": key("pageup", "repeat", 250), "DPAD_DOWN": key("pagedown", "repeat", 250),
    }}
    p["layers"].append(shift)
    return p


def clean_profile(raw):
    """Validate a profile loaded from disk. Returns (profile, warnings); bad parts are dropped, not fatal."""
    warnings = []
    base = new_profile(str(raw.get("name", "Untitled")) if isinstance(raw, dict) else "Untitled")
    if not isinstance(raw, dict):
        return base, ["Profile file is not a JSON object; started blank."]

    target = raw.get("target") if isinstance(raw.get("target"), dict) else {}
    base["target"] = {
        "only_when_focused": bool(target.get("only_when_focused", True)),
        "match": str(target.get("match", "bridge")),
    }
    for side in ("left", "right"):
        src = raw.get("sticks", {}).get(side, {}) if isinstance(raw.get("sticks"), dict) else {}
        mode = src.get("mode", "keys")
        base["sticks"][side] = {
            "mode": mode if mode in STICK_MODES else "keys",
            "deadzone": _num(src.get("deadzone"), STICK_DEFAULTS["deadzone"], 0.05, 0.9),
            "four_way": bool(src.get("four_way", True)),
            "speed": _num(src.get("speed"), 1.0, 0.1, 5.0),
        }
    base["trigger_threshold"] = _num(raw.get("trigger_threshold"), 0.5, 0.1, 0.95)

    layers, used = [], set()
    for n, layer in enumerate(raw.get("layers") or []):
        if not isinstance(layer, dict):
            continue
        activator = None
        if layers:  # layer 0 is always Main and has no activator
            activator = layer.get("activator")
            if activator not in ACTIVATORS or activator in used:
                warnings.append(f"Layer '{layer.get('name', n)}' dropped: bad or duplicate hold-button.")
                continue
            used.add(activator)
        bindings = {}
        for input_id, b in (layer.get("bindings") or {}).items():
            if input_id not in IDS:
                warnings.append(f"Ignored unknown input '{input_id}'.")
                continue
            try:
                bindings[input_id] = clean_binding(b)
            except ValueError as exc:
                warnings.append(f"{LABELS[input_id]}: {exc}. Binding removed.")
        layers.append({"name": str(layer.get("name", f"Layer {n + 1}")) if layers else "Main",
                       "activator": activator, "bindings": bindings})
    base["layers"] = layers or base["layers"]
    return base, warnings


# --- storage ----------------------------------------------------------------

def safe_filename(name):
    cleaned = re.sub(r"[^\w\- ().]+", "_", name).strip(" .")
    return cleaned or "profile"


class ProfileStore:
    """One JSON file per profile in a folder. The file name is the profile name."""

    def __init__(self, directory):
        self.dir = directory
        os.makedirs(directory, exist_ok=True)
        if not self.names():
            self.save(bridge_profile())

    def _path(self, name):
        return os.path.join(self.dir, safe_filename(name) + ".json")

    def names(self):
        return sorted(f[:-5] for f in os.listdir(self.dir) if f.endswith(".json") and f != "settings.json")

    def load(self, name):
        with open(self._path(name), encoding="utf-8") as fh:
            profile, warnings = clean_profile(json.load(fh))
        profile["name"] = name
        return profile, warnings

    def save(self, profile):
        path = self._path(profile["name"])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(profile, fh, indent=2)
        os.replace(tmp, path)  # never leave a half-written profile behind

    def delete(self, name):
        os.remove(self._path(name))

    def unique_name(self, base):
        taken = {n.lower() for n in self.names()}
        name, n = base, 2
        while safe_filename(name).lower() in taken:
            name, n = f"{base} {n}", n + 1
        return name

    # remembered across launches
    def last_used(self):
        try:
            with open(os.path.join(self.dir, "settings.json"), encoding="utf-8") as fh:
                return json.load(fh).get("last_profile")
        except (OSError, ValueError):
            return None

    def remember(self, name):
        with open(os.path.join(self.dir, "settings.json"), "w", encoding="utf-8") as fh:
            json.dump({"last_profile": name}, fh)


def clone(profile):
    return copy.deepcopy(profile)


def target_matches(target, exe, title):
    """Is the focused window one we should send input to? 'match' is a comma-separated list of substrings."""
    if not target.get("only_when_focused", True):
        return True
    haystack = f"{exe} {title}".lower()
    needles = [n.strip().lower() for n in str(target.get("match", "")).split(",") if n.strip()]
    return any(n in haystack for n in needles) if needles else True
