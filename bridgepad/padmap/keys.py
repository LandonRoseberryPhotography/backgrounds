"""Key names the mapper understands, their Windows virtual-key codes, and the combo/macro syntax."""

# name -> (virtual-key code, is_extended_key)
KEYS = {}


def _add(name, vk, ext=False):
    KEYS[name] = (vk, ext)


for _i in range(26):
    _add(chr(ord("a") + _i), 0x41 + _i)
for _i in range(10):
    _add(str(_i), 0x30 + _i)
for _i in range(1, 25):
    _add(f"f{_i}", 0x6F + _i)

for _name, _vk, _ext in [
    ("left", 0x25, True), ("up", 0x26, True), ("right", 0x27, True), ("down", 0x28, True),
    ("home", 0x24, True), ("end", 0x23, True), ("pageup", 0x21, True), ("pagedown", 0x22, True),
    ("insert", 0x2D, True), ("delete", 0x2E, True),
    ("space", 0x20, False), ("enter", 0x0D, False), ("esc", 0x1B, False), ("tab", 0x09, False),
    ("backspace", 0x08, False), ("capslock", 0x14, False), ("printscreen", 0x2C, True),
    ("scrolllock", 0x91, False), ("pause", 0x13, False), ("numlock", 0x90, True),
    ("menu", 0x5D, True),
    ("ctrl", 0xA2, False), ("shift", 0xA0, False), ("alt", 0xA4, False), ("win", 0x5B, True),
    ("rctrl", 0xA3, True), ("rshift", 0xA1, False), ("ralt", 0xA5, True),
    (";", 0xBA, False), ("=", 0xBB, False), (",", 0xBC, False), ("-", 0xBD, False),
    (".", 0xBE, False), ("/", 0xBF, False), ("`", 0xC0, False), ("[", 0xDB, False),
    ("\\", 0xDC, False), ("]", 0xDD, False), ("'", 0xDE, False),
    ("nummul", 0x6A, False), ("numadd", 0x6B, False), ("numsub", 0x6D, False),
    ("numdec", 0x6E, False), ("numdiv", 0x6F, True),
    ("volumemute", 0xAD, False), ("volumedown", 0xAE, False), ("volumeup", 0xAF, False),
    ("medianext", 0xB0, False), ("mediaprev", 0xB1, False), ("mediastop", 0xB2, False),
    ("mediaplay", 0xB3, False),
]:
    _add(_name, _vk, _ext)
for _i in range(10):
    _add(f"num{_i}", 0x60 + _i)

ALIASES = {
    "control": "ctrl", "lctrl": "ctrl", "lshift": "shift", "lalt": "alt", "option": "alt",
    "windows": "win", "cmd": "win", "super": "win", "meta": "win",
    "return": "enter", "escape": "esc", "spacebar": "space", "bksp": "backspace",
    "del": "delete", "ins": "insert", "pgup": "pageup", "pgdn": "pagedown",
    "page_up": "pageup", "page_down": "pagedown", "prior": "pageup", "next": "pagedown",
    "arrowleft": "left", "arrowright": "right", "arrowup": "up", "arrowdown": "down",
    "apps": "menu", "prtsc": "printscreen",
}

MODIFIERS = ("ctrl", "shift", "alt", "win")

_PRETTY = {
    "pageup": "Page Up", "pagedown": "Page Down", "esc": "Esc", "ctrl": "Ctrl",
    "printscreen": "Print Screen", "capslock": "Caps Lock", "numlock": "Num Lock",
    "scrolllock": "Scroll Lock", "backspace": "Backspace", "win": "Win",
}


def normalize_key(token):
    t = token.strip().lower()
    t = ALIASES.get(t, t)
    if t not in KEYS:
        raise ValueError(f"Unknown key '{token.strip()}'")
    return t


def parse_combo(text):
    """'Ctrl+Shift+S' -> ['ctrl', 'shift', 's']"""
    text = str(text).strip()
    if not text:
        raise ValueError("No key chosen")
    return [normalize_key(t) for t in text.split("+")]


def pretty_key(name):
    if name in _PRETTY:
        return _PRETTY[name]
    return name.upper() if len(name) == 1 else name.capitalize()


def format_combo(keys):
    return "+".join(pretty_key(k) for k in keys)


def split_combo(text):
    """Split a stored combo into (modifiers, main key text) for the editor widgets."""
    parts = [p.strip() for p in str(text).split("+") if p.strip()]
    mods = [m for m in MODIFIERS if m in [ALIASES.get(p.lower(), p.lower()) for p in parts]]
    rest = [p for p in parts if ALIASES.get(p.lower(), p.lower()) not in MODIFIERS]
    if not rest and mods:
        # A bare modifier ("ctrl") is a valid binding: keep it as the key.
        return [], "+".join(mods)
    return mods, "+".join(rest)


def join_combo(mods, key):
    key = key.strip()
    return "+".join([m for m in MODIFIERS if m in mods] + ([key] if key else []))


# --- macros -----------------------------------------------------------------
#   "ctrl+a; wait 150; delete"      one step per ';' or newline
#   steps: <combo> | wait <ms> | click <left|right|middle> | scroll <up|down> [notches]

def parse_macro(text):
    steps = []
    for raw in str(text).replace("\n", ";").split(";"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        words = line.lower().split()
        head = words[0]
        try:
            if head in ("wait", "delay", "sleep"):
                arg = words[1]
                if arg.endswith("ms"):
                    ms = float(arg[:-2])
                elif arg.endswith("s"):
                    ms = float(arg[:-1]) * 1000
                else:
                    ms = float(arg)
                if not 0 <= ms <= 60000:
                    raise ValueError
                steps.append(("wait", ms / 1000.0))
            elif head == "click":
                if words[1] not in ("left", "right", "middle"):
                    raise ValueError
                steps.append(("click", words[1]))
            elif head == "scroll":
                if words[1] not in ("up", "down"):
                    raise ValueError
                n = int(words[2]) if len(words) > 2 else 1
                steps.append(("scroll", n if words[1] == "up" else -n))
            else:
                steps.append(("combo", parse_combo(line)))
        except (IndexError, ValueError) as exc:
            detail = exc.args[0] if exc.args and isinstance(exc.args[0], str) else None
            raise ValueError(detail or f"Can't read macro step: '{line}'") from None
    if not steps:
        raise ValueError("Macro is empty")
    return steps
