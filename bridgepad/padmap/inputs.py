"""The Xbox controller, input by input."""
from dataclasses import dataclass

# (id, label) in the order they appear in the mapping table.
INPUTS = [
    ("A", "A button"),
    ("B", "B button"),
    ("X", "X button"),
    ("Y", "Y button"),
    ("LB", "Left bumper (LB)"),
    ("RB", "Right bumper (RB)"),
    ("LT", "Left trigger (LT)"),
    ("RT", "Right trigger (RT)"),
    ("DPAD_UP", "D-pad up"),
    ("DPAD_DOWN", "D-pad down"),
    ("DPAD_LEFT", "D-pad left"),
    ("DPAD_RIGHT", "D-pad right"),
    ("LS_UP", "Left stick up"),
    ("LS_DOWN", "Left stick down"),
    ("LS_LEFT", "Left stick left"),
    ("LS_RIGHT", "Left stick right"),
    ("L3", "Left stick click (L3)"),
    ("RS_UP", "Right stick up"),
    ("RS_DOWN", "Right stick down"),
    ("RS_LEFT", "Right stick left"),
    ("RS_RIGHT", "Right stick right"),
    ("R3", "Right stick click (R3)"),
    ("VIEW", "View (Back)"),
    ("MENU", "Menu (Start)"),
    ("GUIDE", "Xbox button"),
]

LABELS = dict(INPUTS)
IDS = [i for i, _ in INPUTS]

# Inputs that arrive as plain on/off buttons from the controller.
DIGITAL = {
    "A", "B", "X", "Y", "LB", "RB", "L3", "R3", "VIEW", "MENU", "GUIDE",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
}
STICK_INPUTS = {
    "left": ("LS_UP", "LS_DOWN", "LS_LEFT", "LS_RIGHT"),
    "right": ("RS_UP", "RS_DOWN", "RS_LEFT", "RS_RIGHT"),
}
# Inputs that can be held to switch layers (stick directions can't).
ACTIVATORS = [i for i in IDS if i in DIGITAL or i in ("LT", "RT")]


@dataclass
class PadState:
    """One reading of the controller. Sticks are -1..1 with up/right positive; triggers 0..1."""
    buttons: frozenset = frozenset()
    lt: float = 0.0
    rt: float = 0.0
    lx: float = 0.0
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
