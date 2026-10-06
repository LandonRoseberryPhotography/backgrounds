"""The editor window: a clickable map of the controller, the mapping table, and the binding editor."""
import copy
import sys
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .inputs import ACTIVATORS, IDS, LABELS, STICK_INPUTS
from .keys import KEYS, MODIFIERS, join_combo, normalize_key, pretty_key, split_combo
from .profile import ProfileStore, bridge_profile, clean_binding, describe, new_profile

C = dict(bg="#1A1A1A", panel="#242424", panel2="#2E2E2E", line="#3C3C3C", fg="#EDEAE4", muted="#8E8A84",
         gold="#C4952A", slate="#4A6F88", slate_dim="#33505F", good="#6FA37A", warn="#D6A23A", bad="#C0594F",
         body="#2A2A2A", body_line="#454545", ctl="#383838", ctl_line="#5C5C5C")
FONT = "Segoe UI" if sys.platform == "win32" else "TkDefaultFont"

TYPE_LABELS = {  # editor dropdown text -> internal type
    "inherit": "Same as Main layer", "none": "Nothing", "block": "Block (do nothing)",
    "key": "Keyboard key / shortcut", "macro": "Macro (a sequence of steps)",
    "mouse": "Mouse click", "scroll": "Mouse wheel",
}
MODE_HELP = {
    "tap": "Presses the key once each time you press the button.",
    "hold": "Holds the key down for as long as you hold the button.",
    "repeat": "Taps once, then keeps tapping while you hold the button.",
}
STICK_MODE_LABELS = {"keys": "Direction keys (set the four directions)", "mouse": "Mouse pointer", "scroll": "Scroll wheel"}

_COMMON = (["left", "right", "up", "down", "space", "enter", "esc", "tab", "backspace", "delete",
            "home", "end", "pageup", "pagedown", "insert"]
           + [chr(c) for c in range(97, 123)] + [str(d) for d in range(10)] + [f"f{i}" for i in range(1, 13)]
           + [";", "=", ",", "-", ".", "/", "`", "[", "\\", "]", "'"]
           + [f"num{i}" for i in range(10)] + ["numadd", "numsub", "nummul", "numdiv", "numdec"]
           + ["volumeup", "volumedown", "volumemute", "mediaplay", "medianext", "mediaprev", "ctrl", "shift", "alt", "win"])
KEY_CHOICES = [pretty_key(k) for k in _COMMON]
_PRETTY_TO_NAME = {pretty_key(k).lower(): k for k in KEYS}

# --- turning Tk key events into our key names (for the Record button) --------
_MOD_VK = {16: "shift", 17: "ctrl", 18: "alt", 160: "shift", 161: "shift", 162: "ctrl", 163: "ctrl",
           164: "alt", 165: "alt", 91: "win", 92: "win"}
_VK_NAME = {}
for _n, (_vk, _e) in KEYS.items():
    _VK_NAME.setdefault(_vk, _n)
_KEYSYM = {
    "Left": "left", "Right": "right", "Up": "up", "Down": "down", "Home": "home", "End": "end",
    "Prior": "pageup", "Next": "pagedown", "Insert": "insert", "Delete": "delete", "space": "space",
    "Return": "enter", "KP_Enter": "enter", "Escape": "esc", "Tab": "tab", "BackSpace": "backspace",
    "minus": "-", "equal": "=", "comma": ",", "period": ".", "slash": "/", "semicolon": ";",
    "apostrophe": "'", "grave": "`", "bracketleft": "[", "bracketright": "]", "backslash": "\\",
    "Control_L": "ctrl", "Control_R": "ctrl", "Shift_L": "shift", "Shift_R": "shift",
    "Alt_L": "alt", "Alt_R": "alt", "Super_L": "win", "Super_R": "win", "Meta_L": "alt", "Meta_R": "alt",
    "Caps_Lock": "capslock", "Menu": "menu",
}


def event_key_name(event):
    if sys.platform == "win32":  # on Windows Tk's keycode is the virtual-key code
        if event.keycode in _MOD_VK:
            return _MOD_VK[event.keycode]
        if event.keycode in _VK_NAME:
            return _VK_NAME[event.keycode]
    sym = event.keysym
    if sym in _KEYSYM:
        return _KEYSYM[sym]
    return sym.lower() if sym.lower() in KEYS else None


def key_from_text(text):
    """What's typed in the key box -> stored key name (accepts 'Page Up', 'pgup', 'a', ...)."""
    t = text.strip()
    if t.lower() in _PRETTY_TO_NAME:
        return _PRETTY_TO_NAME[t.lower()]
    return t


class KeyRecorder(tk.Toplevel):
    """Small modal: press the key or shortcut you want, it's captured."""

    def __init__(self, master, on_done):
        super().__init__(master, bg=C["panel"], padx=24, pady=18)
        self.title("Record a key")
        self.transient(master)
        self.resizable(False, False)
        self._on_done, self._mods, self._finished = on_done, [], False
        tk.Label(self, text="Press the key or shortcut you want", bg=C["panel"], fg=C["fg"],
                 font=(FONT, 12, "bold")).pack()
        self._hint = tk.Label(self, text="e.g. Space, or Ctrl+Shift+S", bg=C["panel"], fg=C["muted"])
        self._hint.pack(pady=(4, 12))
        ttk.Button(self, text="Cancel", command=self.destroy).pack()
        self.bind("<KeyPress>", self._down)
        self.bind("<KeyRelease>", self._up)
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{x}+{y}")
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass  # modal grab is a nicety; recording still works without it
        self.focus_force()

    def _finish(self, mods, key):
        if self._finished:
            return
        self._finished = True
        self.destroy()
        self._on_done(mods, key)

    def _down(self, e):
        name = event_key_name(e)
        if name is None:
            return "break"
        if name in MODIFIERS:
            if name not in self._mods:
                self._mods.append(name)
            self._hint.config(text="+".join(pretty_key(m) for m in self._mods) + "+ ...")
        else:
            self._finish(list(self._mods), name)
        return "break"

    def _up(self, e):
        name = event_key_name(e)
        if name in MODIFIERS and self._mods:  # released a modifier without pressing anything else
            self._finish([], "+".join(self._mods))
        return "break"


class ControllerMap(tk.Canvas):
    """Drawing of an Xbox controller. Every control is clickable and lights up live."""
    W, H = 760, 470
    FACE = {"A": "#7FC48A", "B": "#E0786E", "X": "#6FA7D6", "Y": "#E3C063"}

    def __init__(self, master, on_select, scale):
        super().__init__(master, width=int(self.W * scale), height=int(self.H * scale), bg=C["panel"],
                         highlightthickness=0)
        self._on_select = on_select
        self._shapes = {}      # input id -> [canvas ids that take the fill/outline]
        self._glyphs = {}      # input id -> [text ids]
        self._glyph_color = {}
        self._dots = {}        # stick -> (dot id, centre x, centre y)
        self._look = {}        # input id -> last applied look (so we only touch the canvas on change)
        self._bound = {}
        self._selected = None
        self._draw()
        self.scale("all", 0, 0, scale, scale)

    # -- drawing --
    def _hot(self, input_id, *items):
        for item in items:
            self.tag_bind(item, "<Button-1>", lambda e, i=input_id: self._on_select(i))
            self.tag_bind(item, "<Enter>", lambda e: self.config(cursor="hand2"))
            self.tag_bind(item, "<Leave>", lambda e: self.config(cursor=""))

    def _reg(self, input_id, shape, glyph=None, glyph_color=None):
        self._shapes.setdefault(input_id, []).append(shape)
        if glyph:
            self._glyphs.setdefault(input_id, []).append(glyph)
            self._glyph_color[input_id] = glyph_color or C["fg"]
        self._hot(input_id, *([shape] + ([glyph] if glyph else [])))

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
               x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _button(self, input_id, cx, cy, r, text, color=None, size=12):
        shape = self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=C["ctl"], outline=C["ctl_line"], width=2)
        glyph = self.create_text(cx, cy, text=text, fill=color or C["fg"], font=(FONT, size, "bold"))
        self._reg(input_id, shape, glyph, color or C["fg"])

    def _draw(self):
        # body and shoulders
        body = [(175, 128), (585, 128), (655, 148), (712, 205), (742, 305), (748, 390), (722, 438), (682, 444),
                (646, 418), (612, 372), (566, 350), (516, 358), (244, 358), (194, 350), (148, 372), (114, 418),
                (78, 444), (38, 438), (12, 390), (18, 305), (48, 205), (105, 148)]
        self.create_polygon([c for p in body for c in p], smooth=True, fill=C["body"], outline=C["body_line"], width=3)
        for side, x1, x2 in (("L", 112, 225), ("R", 535, 648)):
            trig = self._round_rect(x1, 30, x2, 86, 18, fill=C["ctl"], outline=C["ctl_line"], width=2)
            glyph = self.create_text((x1 + x2) / 2, 58, text=f"{side}T", fill=C["fg"], font=(FONT, 12, "bold"))
            self._reg(f"{side}T", trig, glyph)
            bx1, bx2 = (100, 245) if side == "L" else (515, 660)
            bump = self._round_rect(bx1, 94, bx2, 122, 12, fill=C["ctl"], outline=C["ctl_line"], width=2)
            glyph = self.create_text((bx1 + bx2) / 2, 108, text=f"{side}B", fill=C["fg"], font=(FONT, 11, "bold"))
            self._reg(f"{side}B", bump, glyph)

        # face buttons
        for name, (cx, cy) in {"Y": (595, 165), "A": (595, 245), "X": (555, 205), "B": (635, 205)}.items():
            self._button(name, cx, cy, 21, name, self.FACE[name], 13)

        # centre cluster
        guide = self.create_oval(363, 138, 397, 172, fill=C["ctl"], outline=C["ctl_line"], width=2)
        ring = self.create_oval(371, 146, 389, 164, outline=C["muted"], width=2)
        self._reg("GUIDE", guide, ring, C["muted"])
        view = self.create_oval(318, 194, 342, 218, fill=C["ctl"], outline=C["ctl_line"], width=2)
        v1 = self.create_rectangle(325, 202, 333, 208, outline=C["muted"], width=1)
        self._reg("VIEW", view, v1, C["muted"])
        menu = self.create_oval(418, 194, 442, 218, fill=C["ctl"], outline=C["ctl_line"], width=2)
        lines = [self.create_line(425, y, 435, y, fill=C["muted"], width=2) for y in (201, 206, 211)]
        self._reg("MENU", menu, lines[0], C["muted"])
        self._glyphs["MENU"].extend(lines[1:])
        self._hot("MENU", *lines[1:])

        # sticks
        self._stick("LS", "L3", 165, 205)
        self._stick("RS", "R3", 475, 285)

        # d-pad
        cx, cy, a, b = 285, 285, 13, 37
        self.create_rectangle(cx - a, cy - a, cx + a, cy + a, fill=C["ctl"], outline="")
        arms = {"DPAD_UP": (cx - a, cy - b, cx + a, cy - a + 2), "DPAD_DOWN": (cx - a, cy + a - 2, cx + a, cy + b),
                "DPAD_LEFT": (cx - b, cy - a, cx - a + 2, cy + a), "DPAD_RIGHT": (cx + a - 2, cy - a, cx + b, cy + a)}
        tris = {"DPAD_UP": (cx, cy - 31, cx - 6, cy - 21, cx + 6, cy - 21),
                "DPAD_DOWN": (cx, cy + 31, cx - 6, cy + 21, cx + 6, cy + 21),
                "DPAD_LEFT": (cx - 31, cy, cx - 21, cy - 6, cx - 21, cy + 6),
                "DPAD_RIGHT": (cx + 31, cy, cx + 21, cy - 6, cx + 21, cy + 6)}
        for name, box in arms.items():
            arm = self.create_rectangle(*box, fill=C["ctl"], outline=C["ctl_line"], width=2)
            tri = self.create_polygon(*tris[name], fill=C["muted"], outline="")
            self._reg(name, arm, None)
            self._hot(name, tri)
            self._shapes[name].append(tri)  # the arrow glyph takes the pressed colour too

    def _stick(self, prefix, click_id, cx, cy):
        self.create_oval(cx - 46, cy - 46, cx + 46, cy + 46, fill="#202020", outline=C["body_line"], width=2)
        cap = self.create_oval(cx - 30, cy - 30, cx + 30, cy + 30, fill=C["ctl"], outline=C["ctl_line"], width=2)
        label = self.create_text(cx, cy, text=click_id, fill=C["muted"], font=(FONT, 10, "bold"))
        self._reg(click_id, cap, label, C["muted"])
        dot = self.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, fill=C["gold"], outline="")
        self._hot(click_id, dot)
        self._dots["left" if prefix == "LS" else "right"] = (dot, cx, cy)
        for name, (dx, dy, pts) in {
            f"{prefix}_UP": (0, -59, (0, -11, -11, 5, 11, 5)), f"{prefix}_DOWN": (0, 59, (0, 11, -11, -5, 11, -5)),
            f"{prefix}_LEFT": (-59, 0, (-11, 0, 5, -11, 5, 11)), f"{prefix}_RIGHT": (59, 0, (11, 0, -5, -11, -5, 11)),
        }.items():
            x, y = cx + dx, cy + dy
            tri = self.create_polygon(x + pts[0], y + pts[1], x + pts[2], y + pts[3], x + pts[4], y + pts[5],
                                      fill=C["ctl"], outline=C["ctl_line"], width=2)
            self._reg(name, tri)

    # -- state --
    def set_bindings(self, states):
        """states: input id -> 'bound' | 'inherit' | 'none'"""
        self._bound = states
        self._look.clear()

    def set_selected(self, input_id):
        self._selected = input_id
        self._look.clear()

    def update_live(self, pressed, pad):
        for input_id, shapes in self._shapes.items():
            down = input_id in pressed
            key = (down, self._bound.get(input_id), input_id == self._selected)
            if self._look.get(input_id) == key:
                continue
            self._look[input_id] = key
            state = self._bound.get(input_id, "none")
            outline = {"bound": C["slate"], "inherit": C["slate_dim"]}.get(state, C["ctl_line"])
            width = 3 if state == "bound" else 2
            if input_id == self._selected:
                outline, width = C["gold"], 4
            for item in shapes:
                kind = self.type(item)
                if kind == "polygon" and input_id.startswith("DPAD"):
                    self.itemconfigure(item, fill=C["gold"] if down else C["muted"])
                    continue
                self.itemconfigure(item, fill=C["gold"] if down else C["ctl"], outline=outline, width=width)
            for g in self._glyphs.get(input_id, []):
                color = "#1A1A1A" if down else self._glyph_color[input_id]
                if self.type(g) in ("rectangle", "oval"):
                    self.itemconfigure(g, outline=color)
                else:
                    self.itemconfigure(g, fill=color)
        for side, (dot, cx, cy) in self._dots.items():
            x, y = (pad.lx, pad.ly) if side == "left" else (pad.rx, pad.ry)
            self.coords(dot, *(v * self._scale_factor() for v in (cx + x * 16 - 7, cy - y * 16 - 7, cx + x * 16 + 7, cy - y * 16 + 7)))

    def _scale_factor(self):
        return int(self["width"]) / self.W


class App:
    def __init__(self, root, store, engine, runtime, note=""):
        self.root, self.store, self.engine, self.runtime, self.note = root, store, engine, runtime, note
        self.profile = None
        self.layer_idx = 0
        self.selected = "A"
        self._loading = False
        self._save_job = None
        self._ui_job = None
        self._build_style()

        root.title("BridgePad: Xbox controller to Adobe Bridge")
        root.configure(bg=C["bg"])
        root.minsize(960, 560)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self._build_top()
        body = tk.Frame(root, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=14)
        left = tk.Frame(body, bg=C["bg"])
        left.pack(side="left", fill="both")
        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        # Size things for the screen: fits 1366x768 laptops, and stays sharp on high-DPI displays.
        self.px_scale = float(root.tk.call("tk", "scaling")) / (96 / 72)
        logical_h = root.winfo_screenheight() / self.px_scale - 48          # minus a taskbar's worth
        map_scale = self.px_scale * max(0.6, min(0.9, (logical_h - 380) / ControllerMap.H))
        self.table_rows = max(8, min(len(IDS), int((logical_h - 450) / 24)))
        ttk.Style(root).configure("Treeview", rowheight=int(24 * self.px_scale))
        self.map = ControllerMap(left, self.select, map_scale)
        self.map.pack()
        self._build_layers(left)
        self._build_target(left)
        self._build_feel(left)
        self._build_table(right)
        self._build_editor(right)
        self._build_status()

        names = self.store.names()
        last = self.store.last_used()
        self.load_profile(last if last in names else names[0])
        self._tick_ui()

    # ---------- styling ----------
    def _build_style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=C["bg"], foreground=C["fg"], fieldbackground=C["panel2"], bordercolor=C["line"],
                    lightcolor=C["panel2"], darkcolor=C["panel2"], troughcolor=C["panel2"], focuscolor=C["bg"],
                    font=(FONT, 10))
        s.configure("TButton", background=C["panel2"], padding=(10, 5), borderwidth=1)
        s.map("TButton", background=[("active", "#3A3A3A")])
        s.configure("TCombobox", fieldbackground=C["panel2"], background=C["panel2"], arrowcolor=C["fg"], padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", C["panel2"])], foreground=[("readonly", C["fg"])],
              selectbackground=[("readonly", C["panel2"])], selectforeground=[("readonly", C["fg"])])
        s.configure("TEntry", fieldbackground=C["panel2"], padding=4)
        s.configure("TSpinbox", fieldbackground=C["panel2"], arrowcolor=C["fg"], padding=3)
        s.configure("TCheckbutton", background=C["bg"], indicatorbackground=C["panel2"], indicatorcolor=C["panel2"])
        s.map("TCheckbutton", indicatorcolor=[("selected", C["gold"])], indicatorforeground=[("selected", C["gold"])],
              background=[("active", C["bg"])])
        s.configure("TRadiobutton", background=C["bg"], indicatorbackground=C["panel2"])
        s.map("TRadiobutton", indicatorcolor=[("selected", C["gold"])], indicatorforeground=[("selected", C["gold"])],
              background=[("active", C["bg"])])
        s.configure("Layer.Toolbutton", background=C["panel2"], padding=(14, 6), borderwidth=0)
        s.map("Layer.Toolbutton", background=[("selected", C["gold"]), ("active", "#3A3A3A")],
              foreground=[("selected", "#1A1A1A")])
        s.configure("Treeview", background=C["panel"], fieldbackground=C["panel"], rowheight=24, borderwidth=0)
        s.map("Treeview", background=[("selected", C["slate"])], foreground=[("selected", "#FFFFFF")])
        s.configure("Treeview.Heading", background=C["panel2"], foreground=C["muted"], relief="flat", padding=4)
        s.configure("Horizontal.TScale", background=C["gold"], troughcolor=C["panel2"], bordercolor=C["line"])
        s.configure("Card.TCheckbutton", background=C["panel"], indicatorbackground=C["panel2"])
        s.map("Card.TCheckbutton", background=[("active", C["panel"])], indicatorcolor=[("selected", C["gold"])],
              indicatorforeground=[("selected", C["gold"])])
        s.configure("Card.TRadiobutton", background=C["panel"], indicatorbackground=C["panel2"])
        s.map("Card.TRadiobutton", background=[("active", C["panel"])], indicatorcolor=[("selected", C["gold"])],
              indicatorforeground=[("selected", C["gold"])])
        s.configure("Hint.TLabel", foreground=C["muted"])
        self.root.option_add("*TCombobox*Listbox.background", C["panel2"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["slate"])

    # ---------- layout pieces ----------
    def _build_top(self):
        bar = tk.Frame(self.root, bg=C["bg"])
        bar.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(bar, text="BridgePad", bg=C["bg"], fg=C["gold"], font=("Georgia", 18, "bold")).pack(side="left")
        tk.Label(bar, text="  profile", bg=C["bg"], fg=C["muted"]).pack(side="left", padx=(18, 4))
        self.v_profile = tk.StringVar()
        self.cb_profile = ttk.Combobox(bar, textvariable=self.v_profile, state="readonly", width=26)
        self.cb_profile.pack(side="left")
        self.cb_profile.bind("<<ComboboxSelected>>", lambda e: self.load_profile(self.v_profile.get()))
        for text, cmd in (("New", self.new_profile), ("Duplicate", self.duplicate_profile),
                          ("Rename", self.rename_profile), ("Delete", self.delete_profile)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(6, 0))
        self.v_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Controller is on", variable=self.v_enabled,
                        command=lambda: self.engine.set_enabled(self.v_enabled.get())).pack(side="right")

    def _build_layers(self, parent):
        self.layer_card = tk.Frame(parent, bg=C["bg"])
        self.layer_card.pack(fill="x", pady=(12, 0))
        self.layer_bar = tk.Frame(self.layer_card, bg=C["bg"])
        self.layer_bar.pack(fill="x")
        self.layer_opts = tk.Frame(self.layer_card, bg=C["bg"])
        self.layer_opts.pack(fill="x", pady=(8, 0))
        self.v_layer = tk.IntVar(value=0)
        self.v_activator = tk.StringVar()
        tk.Label(self.layer_opts, text="This layer is active while you hold", bg=C["bg"], fg=C["muted"]).pack(side="left")
        self.cb_activator = ttk.Combobox(self.layer_opts, textvariable=self.v_activator, state="readonly", width=20)
        self.cb_activator.pack(side="left", padx=6)
        self.cb_activator.bind("<<ComboboxSelected>>", self._set_activator)
        self.btn_rename_layer = ttk.Button(self.layer_opts, text="Rename", command=self.rename_layer)
        self.btn_rename_layer.pack(side="left", padx=(6, 0))
        self.btn_remove_layer = ttk.Button(self.layer_opts, text="Remove layer", command=self.remove_layer)
        self.btn_remove_layer.pack(side="left", padx=(6, 0))

    def _build_target(self, parent):
        box = tk.Frame(parent, bg=C["bg"])
        box.pack(fill="x", pady=(14, 0))
        self.v_only_focused = tk.BooleanVar(value=True)
        self.v_match = tk.StringVar()
        ttk.Checkbutton(box, text="Only send input while this app is in front:", variable=self.v_only_focused,
                        command=self._on_target).pack(side="left")
        entry = ttk.Entry(box, textvariable=self.v_match, width=18)
        entry.pack(side="left", padx=8)
        self.v_match.trace_add("write", lambda *_: self._on_target())

    def _build_table(self, parent):
        wrap = tk.Frame(parent, bg=C["bg"])
        wrap.pack(fill="both", expand=True)
        self.lbl_layer = tk.Label(wrap, text="", bg=C["bg"], fg=C["muted"], anchor="w")
        self.lbl_layer.pack(fill="x", pady=(0, 4))
        inner = tk.Frame(wrap, bg=C["panel"])
        inner.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(inner, columns=("input", "action"), show="headings", height=self.table_rows, selectmode="browse")
        self.tree.heading("input", text="Controller input")
        self.tree.heading("action", text="What it does")
        self.tree.column("input", width=int(165 * self.px_scale), stretch=False, anchor="w")
        self.tree.column("action", width=int(215 * self.px_scale), anchor="w")
        self.tree.tag_configure("inherit", foreground=C["muted"])
        self.tree.tag_configure("none", foreground="#6A6762")
        scroll = ttk.Scrollbar(inner, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for input_id in IDS:
            self.tree.insert("", "end", iid=input_id, values=(LABELS[input_id], ""))
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _build_editor(self, parent):
        ed = tk.Frame(parent, bg=C["panel"], padx=14, pady=12)
        ed.pack(fill="x", pady=(10, 0))
        self.ed = ed
        self.lbl_ed_title = tk.Label(ed, text="", bg=C["panel"], fg=C["fg"], font=(FONT, 12, "bold"), anchor="w")
        self.lbl_ed_title.grid(row=0, column=0, columnspan=4, sticky="we")
        self.v_type = tk.StringVar()
        self.cb_type = ttk.Combobox(ed, textvariable=self.v_type, state="readonly", width=34)
        self.cb_type.grid(row=1, column=0, columnspan=4, sticky="we", pady=(8, 8))
        self.cb_type.bind("<<ComboboxSelected>>", lambda e: (self._show_frames(), self._on_edit()))

        # keyboard
        self.f_key = tk.Frame(ed, bg=C["panel"])
        self.v_mods = {m: tk.BooleanVar() for m in MODIFIERS}
        mods = tk.Frame(self.f_key, bg=C["panel"])
        mods.grid(row=0, column=0, columnspan=4, sticky="w")
        for m in MODIFIERS:
            ttk.Checkbutton(mods, text=pretty_key(m), variable=self.v_mods[m], style="Card.TCheckbutton",
                            command=self._on_edit).pack(side="left", padx=(0, 12))
        tk.Label(self.f_key, text="Key", bg=C["panel"], fg=C["muted"]).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.v_key = tk.StringVar()
        self.cb_key = ttk.Combobox(self.f_key, textvariable=self.v_key, values=KEY_CHOICES, width=14)
        self.cb_key.grid(row=1, column=1, sticky="w", padx=8, pady=(8, 0))
        self.cb_key.bind("<<ComboboxSelected>>", lambda e: self._on_edit())
        self.cb_key.bind("<FocusOut>", lambda e: self._on_edit())
        self.cb_key.bind("<Return>", lambda e: self._on_edit())
        ttk.Button(self.f_key, text="Record…", command=self.record_key).grid(row=1, column=2, pady=(8, 0))
        self.v_mode = tk.StringVar(value="tap")
        modes = tk.Frame(self.f_key, bg=C["panel"])
        modes.grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))
        for value, text in (("tap", "Tap"), ("hold", "Hold"), ("repeat", "Repeat")):
            ttk.Radiobutton(modes, text=text, value=value, variable=self.v_mode, style="Card.TRadiobutton",
                            command=self._on_edit).pack(side="left", padx=(0, 14))
        self.lbl_mode = tk.Label(self.f_key, text="", bg=C["panel"], fg=C["muted"], anchor="w")
        self.lbl_mode.grid(row=3, column=0, columnspan=4, sticky="w")
        self.f_repeat = tk.Frame(self.f_key, bg=C["panel"])
        self.f_repeat.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.v_delay, self.v_repeat = tk.StringVar(value="350"), tk.StringVar(value="150")
        tk.Label(self.f_repeat, text="Start repeating after", bg=C["panel"], fg=C["muted"]).pack(side="left")
        self._spin(self.f_repeat, self.v_delay, 0, 5000, 50).pack(side="left", padx=4)
        tk.Label(self.f_repeat, text="ms, then every", bg=C["panel"], fg=C["muted"]).pack(side="left")
        self._spin(self.f_repeat, self.v_repeat, 20, 5000, 10).pack(side="left", padx=4)
        tk.Label(self.f_repeat, text="ms", bg=C["panel"], fg=C["muted"]).pack(side="left")

        # macro
        self.f_macro = tk.Frame(ed, bg=C["panel"])
        self.t_macro = tk.Text(self.f_macro, height=4, width=40, bg=C["panel2"], fg=C["fg"], insertbackground=C["fg"],
                               relief="flat", font=("Consolas" if sys.platform == "win32" else "TkFixedFont", 10))
        self.t_macro.pack(fill="x")
        self.t_macro.bind("<KeyRelease>", lambda e: self._on_edit())
        tk.Label(self.f_macro, text="One step per line (or separated by ;)   e.g.  ctrl+a   wait 200   click left   scroll down 3",
                 bg=C["panel"], fg=C["muted"], anchor="w", wraplength=380, justify="left").pack(fill="x", pady=(4, 0))

        # mouse click
        self.f_mouse = tk.Frame(ed, bg=C["panel"])
        self.v_mbutton, self.v_mmode = tk.StringVar(value="left"), tk.StringVar(value="tap")
        ttk.Combobox(self.f_mouse, textvariable=self.v_mbutton, values=("left", "right", "middle"), state="readonly",
                     width=9).pack(side="left")
        for value, text in (("tap", "Click"), ("hold", "Hold down")):
            ttk.Radiobutton(self.f_mouse, text=text, value=value, variable=self.v_mmode, style="Card.TRadiobutton",
                            command=self._on_edit).pack(side="left", padx=(14, 0))
        self.f_mouse.winfo_children()[0].bind("<<ComboboxSelected>>", lambda e: self._on_edit())

        # mouse wheel
        self.f_scroll = tk.Frame(ed, bg=C["panel"])
        self.v_sdir, self.v_srepeat = tk.StringVar(value="down"), tk.StringVar(value="80")
        cb = ttk.Combobox(self.f_scroll, textvariable=self.v_sdir, values=("up", "down"), state="readonly", width=7)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_edit())
        tk.Label(self.f_scroll, text="  repeat every", bg=C["panel"], fg=C["muted"]).pack(side="left")
        self._spin(self.f_scroll, self.v_srepeat, 0, 5000, 20).pack(side="left", padx=4)
        tk.Label(self.f_scroll, text="ms (0 = once)", bg=C["panel"], fg=C["muted"]).pack(side="left")

        self.v_error = tk.StringVar()
        tk.Label(ed, textvariable=self.v_error, bg=C["panel"], fg=C["bad"], anchor="w", wraplength=380,
                 justify="left").grid(row=3, column=0, columnspan=4, sticky="we", pady=(6, 0))

        self.f_key.grid(row=2, column=0, columnspan=4, sticky="we")
        for f in (self.f_macro, self.f_mouse, self.f_scroll):
            f.grid(row=2, column=0, columnspan=4, sticky="we")
        ed.columnconfigure(0, weight=1)

    def _build_feel(self, parent):
        """Stick and trigger settings. They belong to the controller, not to one binding, so they live
        beside the map and only appear when you select a stick or trigger."""
        self.feel = tk.Frame(parent, bg=C["panel"], padx=14, pady=10)
        self.f_stick = tk.Frame(self.feel, bg=C["panel"])
        self.v_smode, self.v_sdead, self.v_sspeed = tk.StringVar(), tk.DoubleVar(), tk.DoubleVar()
        self.v_four = tk.BooleanVar()
        self.lbl_stick = tk.Label(self.f_stick, text="", bg=C["panel"], fg=C["fg"], font=(FONT, 10, "bold"), anchor="w")
        self.lbl_stick.grid(row=0, column=0, columnspan=3, sticky="we")
        self.cb_smode = ttk.Combobox(self.f_stick, textvariable=self.v_smode, state="readonly", width=36,
                                     values=list(STICK_MODE_LABELS.values()))
        self.cb_smode.grid(row=1, column=0, columnspan=3, sticky="we", pady=(4, 6))
        self.cb_smode.bind("<<ComboboxSelected>>", lambda e: self._on_stick())
        self._slider(self.f_stick, 2, "Deadzone", self.v_sdead, 0.05, 0.8)
        self.row_speed = self._slider(self.f_stick, 3, "Speed", self.v_sspeed, 0.2, 3.0)
        self.chk_four = ttk.Checkbutton(self.f_stick, text="Snap to 4 directions (no diagonals)", variable=self.v_four,
                                        style="Card.TCheckbutton", command=self._on_stick)
        self.chk_four.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # triggers
        self.f_trig = tk.Frame(self.feel, bg=C["panel"])
        self.v_thr = tk.DoubleVar()
        self._slider(self.f_trig, 0, "Press point", self.v_thr, 0.1, 0.95, self._on_trigger)

        self.f_stick.grid(row=0, column=0, sticky="we")
        self.f_trig.grid(row=1, column=0, sticky="we")
        self.feel.columnconfigure(0, weight=1)

    def _spin(self, parent, var, lo, hi, step):
        sp = ttk.Spinbox(parent, textvariable=var, from_=lo, to=hi, increment=step, width=6, command=self._on_edit)
        sp.bind("<FocusOut>", lambda e: self._on_edit())
        sp.bind("<Return>", lambda e: self._on_edit())
        return sp

    def _slider(self, parent, row, text, var, lo, hi, command=None):
        label = tk.Label(parent, text=text, bg=C["panel"], fg=C["muted"], width=10, anchor="w")
        label.grid(row=row, column=0, sticky="w")
        value = tk.Label(parent, text="", bg=C["panel"], fg=C["fg"], width=5)
        value.grid(row=row, column=2)
        cmd = command or self._on_stick

        def changed(_=None):
            value.config(text=f"{var.get():.2f}")
            if not self._loading:
                cmd()

        scale = ttk.Scale(parent, from_=lo, to=hi, variable=var, command=changed)
        scale.grid(row=row, column=1, sticky="we", padx=6)
        parent.columnconfigure(1, weight=1)
        var.trace_add("write", lambda *_: value.config(text=f"{var.get():.2f}"))
        return (label, scale, value)

    def _build_status(self):
        bar = tk.Frame(self.root, bg=C["panel"])
        bar.pack(fill="x", side="bottom", pady=(10, 0))
        self.dot = tk.Canvas(bar, width=14, height=14, bg=C["panel"], highlightthickness=0)
        self.dot.pack(side="left", padx=(14, 6), pady=8)
        self.dot_item = self.dot.create_oval(2, 2, 12, 12, fill=C["muted"], outline="")
        self.lbl_status = tk.Label(bar, text="", bg=C["panel"], fg=C["fg"], anchor="w")
        self.lbl_status.pack(side="left")
        self.lbl_note = tk.Label(bar, text=self.note, bg=C["panel"], fg=C["warn"], anchor="e")
        self.lbl_note.pack(side="right", padx=(0, 14))
        self.lbl_front = tk.Label(bar, text="", bg=C["panel"], fg=C["muted"], anchor="e")
        self.lbl_front.pack(side="right", padx=14)

    # ---------- profiles ----------
    def load_profile(self, name):
        self._flush_save()
        try:
            profile, warnings = self.store.load(name)
        except (OSError, ValueError) as exc:
            messagebox.showerror("BridgePad", f"Couldn't open profile '{name}':\n{exc}")
            profile, warnings = bridge_profile(), []
        self.profile = profile
        self.store.remember(name)
        self.v_profile.set(name)
        self.cb_profile.configure(values=self.store.names())
        self.layer_idx = 0
        self.engine.set_profile(self.profile)
        self._loading = True
        self.v_only_focused.set(profile["target"]["only_when_focused"])
        self.v_match.set(profile["target"]["match"])
        self._loading = False
        self._rebuild_layers()
        self.select(self.selected if self.selected in IDS else "A")
        if warnings:
            messagebox.showwarning("BridgePad", "Some parts of this profile couldn't be used:\n\n" + "\n".join(warnings[:8]))

    def new_profile(self):
        name = simpledialog.askstring("New profile", "Name for the new (empty) profile:", parent=self.root)
        if name and name.strip():
            name = self.store.unique_name(name.strip())
            self.store.save(new_profile(name))
            self.load_profile(name)

    def duplicate_profile(self):
        name = self.store.unique_name(self.profile["name"] + " copy")
        copied = copy.deepcopy(self.profile)
        copied["name"] = name
        self.store.save(copied)
        self.load_profile(name)

    def rename_profile(self):
        old = self.profile["name"]
        name = simpledialog.askstring("Rename profile", "New name:", initialvalue=old, parent=self.root)
        if name and name.strip() and name.strip() != old:
            self._flush_save()
            name = self.store.unique_name(name.strip())
            self.profile["name"] = name
            self.store.save(self.profile)
            self.store.delete(old)
            self.load_profile(name)

    def delete_profile(self):
        names = self.store.names()
        if len(names) < 2:
            messagebox.showinfo("BridgePad", "That's your only profile, so it can't be deleted.")
            return
        old = self.profile["name"]
        if messagebox.askyesno("Delete profile", f"Delete '{old}'? This can't be undone."):
            if self._save_job:
                self.root.after_cancel(self._save_job)
                self._save_job = None
            self.store.delete(old)
            self.profile = None   # so load_profile doesn't write the old file back
            self.load_profile(self.store.names()[0])

    def _changed(self):
        """The profile was edited: apply it to the running engine now, save shortly after."""
        self.engine.set_profile(self.profile)
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(400, self._flush_save)

    def _flush_save(self):
        if self._save_job:
            self.root.after_cancel(self._save_job)
            self._save_job = None
        if self.profile:
            try:
                self.store.save(self.profile)
            except OSError as exc:
                messagebox.showerror("BridgePad", f"Couldn't save your profile:\n{exc}")

    # ---------- layers ----------
    @property
    def layer(self):
        return self.profile["layers"][self.layer_idx]

    def _rebuild_layers(self):
        for child in self.layer_bar.winfo_children():
            child.destroy()
        for i, layer in enumerate(self.profile["layers"]):
            ttk.Radiobutton(self.layer_bar, text=layer["name"], value=i, variable=self.v_layer,
                            style="Layer.Toolbutton", command=self._pick_layer).pack(side="left", padx=(0, 6))
        ttk.Button(self.layer_bar, text="+ Add layer", command=self.add_layer).pack(side="left")
        self.v_layer.set(self.layer_idx)
        is_main = self.layer_idx == 0
        for w in (self.cb_activator, self.btn_rename_layer, self.btn_remove_layer):
            w.configure(state="disabled" if is_main else ("readonly" if w is self.cb_activator else "normal"))
        if is_main:
            self.v_activator.set("(always on)")
        else:
            used = {l["activator"] for i, l in enumerate(self.profile["layers"]) if i != self.layer_idx}
            self.cb_activator.configure(values=[LABELS[a] for a in ACTIVATORS if a not in used])
            self.v_activator.set(LABELS[self.layer["activator"]])
        self._refresh_table()

    def _pick_layer(self):
        self.layer_idx = self.v_layer.get()
        self._rebuild_layers()
        self.select(self.selected)

    def _set_activator(self, _=None):
        chosen = next((a for a in ACTIVATORS if LABELS[a] == self.v_activator.get()), None)
        if chosen:
            self.layer["activator"] = chosen
            self._changed()

    def add_layer(self):
        name = simpledialog.askstring("New layer", "Name for this layer (e.g. Shift, Ratings):", parent=self.root)
        if not name or not name.strip():
            return
        used = {l["activator"] for l in self.profile["layers"]}
        activator = next((a for a in ("LT", "RT", "RB", "LB", "VIEW", "MENU") if a not in used), None)
        if activator is None:
            messagebox.showinfo("BridgePad", "Every possible layer button is already in use.")
            return
        self.profile["layers"].append({"name": name.strip(), "activator": activator, "bindings": {}})
        self.layer_idx = len(self.profile["layers"]) - 1
        self._changed()
        self._rebuild_layers()
        self.select(self.selected)
        messagebox.showinfo("BridgePad", f"'{name.strip()}' is active while you hold {LABELS[activator]}.\n"
                                         "Change the button with the dropdown under the layer tabs.")

    def rename_layer(self):
        name = simpledialog.askstring("Rename layer", "New name:", initialvalue=self.layer["name"], parent=self.root)
        if name and name.strip():
            self.layer["name"] = name.strip()
            self._changed()
            self._rebuild_layers()

    def remove_layer(self):
        if self.layer_idx and messagebox.askyesno("Remove layer", f"Remove '{self.layer['name']}' and its bindings?"):
            del self.profile["layers"][self.layer_idx]
            self.layer_idx = 0
            self._changed()
            self._rebuild_layers()
            self.select(self.selected)

    # ---------- table + selection ----------
    def _binding_state(self, input_id):
        own = self.layer["bindings"].get(input_id)
        if own is not None:
            return "bound" if own["type"] != "none" else "none", own
        if self.layer_idx:
            main = self.profile["layers"][0]["bindings"].get(input_id)
            if main is not None and main["type"] != "none":
                return "inherit", main
        return "none", None

    def _refresh_row(self, input_id):
        state, binding = self._binding_state(input_id)
        text = describe(binding) if binding else ""
        own = self.layer["bindings"].get(input_id)
        if state == "inherit":
            text = "(Main)  " + text
        tags = ("inherit",) if state == "inherit" else (("none",) if state == "none" and not text else ())
        self.tree.item(input_id, values=(LABELS[input_id], text), tags=tags)

    def _refresh_table(self):
        for input_id in IDS:
            self._refresh_row(input_id)
        self.map.set_bindings({i: self._binding_state(i)[0] for i in IDS})
        self.lbl_layer.config(text=f"Showing layer: {self.layer['name']}"
                              + ("" if self.layer_idx == 0 else "   (grey rows fall back to the Main layer)"))

    def _on_tree_select(self, _=None):
        sel = self.tree.selection()
        if sel and sel[0] != self.selected:
            self.select(sel[0])

    def select(self, input_id):
        self.selected = input_id
        self.map.set_selected(input_id)
        if self.tree.selection() != (input_id,):
            self.tree.selection_set(input_id)
            self.tree.see(input_id)
        self._load_editor()

    # ---------- editor ----------
    def _type_options(self):
        keys = ["inherit", "block"] if self.layer_idx else ["none"]
        return keys + ["key", "macro", "mouse", "scroll"]

    def _load_editor(self):
        self._loading = True
        input_id = self.selected
        self.lbl_ed_title.config(text=f"{LABELS[input_id]}   ·   {self.layer['name']}")
        options = self._type_options()
        self.cb_type.configure(values=[TYPE_LABELS[o] for o in options])
        own = self.layer["bindings"].get(input_id)
        if own is None:
            current = "inherit" if self.layer_idx else "none"
        elif own["type"] == "none":
            current = "block" if self.layer_idx else "none"
        else:
            current = own["type"]
        self.v_type.set(TYPE_LABELS[current])
        self.v_error.set("")
        b = own or {}
        mods, main = split_combo(b.get("keys", "")) if b.get("type") == "key" else ([], "")
        for m, var in self.v_mods.items():
            var.set(m in mods)
        try:
            self.v_key.set(pretty_key(normalize_key(main)) if main else "")
        except ValueError:
            self.v_key.set(main)
        self.v_mode.set(b.get("mode", "tap") if b.get("type") == "key" else "tap")
        self.v_delay.set(str(b.get("delay_ms", 350)))
        self.v_repeat.set(str(b.get("repeat_ms", 150)))
        self.t_macro.delete("1.0", "end")
        self.t_macro.insert("1.0", b.get("steps", "") if b.get("type") == "macro" else "")
        self.v_mbutton.set(b.get("button", "left"))
        self.v_mmode.set(b.get("mode", "tap") if b.get("type") == "mouse" else "tap")
        self.v_sdir.set(b.get("direction", "down"))
        self.v_srepeat.set(str(b.get("repeat_ms", 80)) if b.get("type") == "scroll" else "80")

        side = next((s for s, ids in STICK_INPUTS.items() if input_id in ids), None)
        side = side or {"L3": "left", "R3": "right"}.get(input_id)
        self._stick_side = side
        if side:
            cfg = self.profile["sticks"][side]
            self.lbl_stick.config(text=f"{side.capitalize()} stick settings (apply to every layer)")
            self.v_smode.set(STICK_MODE_LABELS[cfg["mode"]])
            self.v_sdead.set(cfg["deadzone"])
            self.v_sspeed.set(cfg["speed"])
            self.v_four.set(cfg["four_way"])
        self.v_thr.set(self.profile["trigger_threshold"])
        self._loading = False
        self._show_frames()

    def _current_type(self):
        label = self.v_type.get()
        return next((k for k, v in TYPE_LABELS.items() if v == label), "none")

    def _show_frames(self):
        kind = self._current_type()
        frames = {"key": self.f_key, "macro": self.f_macro, "mouse": self.f_mouse, "scroll": self.f_scroll}
        for name, frame in frames.items():
            (frame.grid if name == kind else frame.grid_remove)()
        self.lbl_mode.config(text=MODE_HELP[self.v_mode.get()])
        (self.f_repeat.grid if self.v_mode.get() == "repeat" else self.f_repeat.grid_remove)()
        side = self._stick_side
        is_trigger = self.selected in ("LT", "RT")
        (self.f_stick.grid if side else self.f_stick.grid_remove)()
        (self.f_trig.grid if is_trigger else self.f_trig.grid_remove)()
        if side or is_trigger:
            self.feel.pack(fill="x", pady=(14, 0))
        else:
            self.feel.pack_forget()
        if side:
            mode = self.profile["sticks"][side]["mode"]
            for widget in self.row_speed:
                (widget.grid if mode != "keys" else widget.grid_remove)()
            (self.chk_four.grid if mode == "keys" else self.chk_four.grid_remove)()
            if mode != "keys":
                self.v_error.set("")

    def _int(self, var, default):
        try:
            return int(float(var.get()))
        except (ValueError, tk.TclError):
            return default

    def _build_binding(self):
        """-> (binding or None for 'inherit', error text). Error text means 'don't save yet'."""
        kind = self._current_type()
        if kind in ("inherit",):
            return None, ""
        if kind in ("none", "block"):
            return {"type": "none"}, ""
        if kind == "key":
            combo = join_combo({m for m, v in self.v_mods.items() if v.get()}, key_from_text(self.v_key.get()))
            raw = {"type": "key", "keys": combo, "mode": self.v_mode.get(),
                   "repeat_ms": self._int(self.v_repeat, 150), "delay_ms": self._int(self.v_delay, 350)}
        elif kind == "macro":
            raw = {"type": "macro", "steps": self.t_macro.get("1.0", "end").strip()}
        elif kind == "mouse":
            raw = {"type": "mouse", "button": self.v_mbutton.get(), "mode": self.v_mmode.get()}
        else:
            raw = {"type": "scroll", "direction": self.v_sdir.get(), "repeat_ms": self._int(self.v_srepeat, 80)}
        try:
            return clean_binding(raw), ""
        except ValueError as exc:
            message = str(exc)
            return None, ("Pick a key to finish this binding." if message == "No key chosen" else message)

    def _on_edit(self, *_):
        if self._loading:
            return
        self.lbl_mode.config(text=MODE_HELP[self.v_mode.get()])
        (self.f_repeat.grid if self.v_mode.get() == "repeat" else self.f_repeat.grid_remove)()
        binding, error = self._build_binding()
        self.v_error.set(error)
        if error:
            return
        bindings = self.layer["bindings"]
        if binding is None or (binding["type"] == "none" and self.layer_idx == 0):
            bindings.pop(self.selected, None)
        else:
            bindings[self.selected] = binding
        self._changed()
        self._refresh_row(self.selected)
        self.map.set_bindings({i: self._binding_state(i)[0] for i in IDS})

    def record_key(self):
        def done(mods, key):
            self._loading = True
            for m, var in self.v_mods.items():
                var.set(m in mods)
            self.v_key.set(pretty_key(key) if key in KEYS else key)
            self._loading = False
            if self._current_type() != "key":
                self.v_type.set(TYPE_LABELS["key"])
                self._show_frames()
            self._on_edit()
        KeyRecorder(self.root, done)

    def _on_stick(self, *_):
        if self._loading or not self._stick_side:
            return
        cfg = self.profile["sticks"][self._stick_side]
        cfg["mode"] = next((k for k, v in STICK_MODE_LABELS.items() if v == self.v_smode.get()), "keys")
        cfg["deadzone"] = round(self.v_sdead.get(), 2)
        cfg["speed"] = round(self.v_sspeed.get(), 2)
        cfg["four_way"] = bool(self.v_four.get())
        self._show_frames()
        self._changed()

    def _on_trigger(self, *_):
        if not self._loading:
            self.profile["trigger_threshold"] = round(self.v_thr.get(), 2)
            self._changed()

    def _on_target(self):
        if self._loading or not self.profile:
            return
        self.profile["target"] = {"only_when_focused": bool(self.v_only_focused.get()), "match": self.v_match.get()}
        self._changed()

    # ---------- live updates ----------
    def _tick_ui(self):
        snap = self.engine.snapshot()
        self.map.update_live(snap["pressed"], snap["pad"])
        rt = self.runtime
        exe, title = rt.foreground
        self.lbl_front.config(text=f"In front: {exe or '(unknown)'}" + (f"  “{title[:36]}”" if title else ""))
        if not getattr(rt.pad, "available", True):
            text, color = "Can't read controllers on this computer", C["bad"]
        elif rt.error:
            text, color = f"Problem: {rt.error}", C["bad"]
        elif not rt.connected:
            text, color = "No controller found. Plug in or wake your Xbox controller.", C["bad"]
        elif not self.engine.enabled:
            text, color = "Paused. The controller isn't sending anything.", C["muted"]
        elif not rt.focused:
            text, color = "Waiting. The app you chose isn't in front, so nothing is being sent.", C["warn"]
        else:
            text, color = f"Active  ·  layer: {self.profile['layers'][min(snap['layer'], len(self.profile['layers']) - 1)]['name']}", C["good"]
        self.lbl_status.config(text=text)
        self.dot.itemconfigure(self.dot_item, fill=color)
        if self._ui_job:
            self.root.after_cancel(self._ui_job)   # never run two refresh chains at once
        self._ui_job = self.root.after(33, self._tick_ui)

    def stop_timers(self):
        for job in (self._ui_job, self._save_job):
            if job:
                self.root.after_cancel(job)
        self._ui_job = self._save_job = None

    def close(self):
        self._flush_save()
        self.stop_timers()
        self.runtime.stop()
        self.root.destroy()
