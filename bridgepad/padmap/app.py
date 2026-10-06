"""Start-up: pick a data folder, wire the pieces together, open the window. Also --diagnose."""
import os
import sys
import time

from .engine import Engine
from .inputs import LABELS
from .profile import ProfileStore
from .runtime import Runtime, build_backends


def data_dir():
    """Profiles live next to the program (easy to find and back up); fall back to the home folder if read-only."""
    override = os.environ.get("BRIDGEPAD_HOME")
    if override:
        return override
    beside = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profiles")
    try:
        os.makedirs(beside, exist_ok=True)
        probe = os.path.join(beside, ".write-test")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return beside
    except OSError:
        return os.path.join(os.path.expanduser("~"), "BridgePad", "profiles")


def _enable_dpi_awareness():
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def run_gui():
    import tkinter as tk
    from .gui import App

    _enable_dpi_awareness()
    pad, output, probe, note = build_backends()
    engine = Engine(output)
    runtime = Runtime(engine, pad, probe)
    store = ProfileStore(data_dir())
    root = tk.Tk()
    app = App(root, store, engine, runtime, note)
    runtime.start()
    try:
        root.mainloop()
    finally:
        runtime.stop()
    return app


def diagnose(seconds=20):
    """Prints what the program can see. Run this and send the output if something doesn't work."""
    print(f"BridgePad diagnostics ({sys.platform}, Python {sys.version.split()[0]})")
    pad, output, probe, note = build_backends()
    if note:
        print("NOTE:", note)
    print("XInput library:", getattr(pad, "dll_name", None) or "none")
    if sys.platform == "win32":
        output.key_down("shift")
        output.key_up("shift")
        print("Sending test keystroke (Shift):", "FAILED" if output.failures else "ok")
    print(f"\nWatching for {seconds}s. Press buttons on the controller and switch between windows.\n")
    last_pad, last_fg, end = None, None, time.monotonic() + seconds
    while time.monotonic() < end:
        state = pad.read()
        fg = probe()
        if fg != last_fg:
            last_fg = fg
            print(f"in front: exe={fg[0]!r} title={fg[1]!r}")
        if state is None:
            if last_pad is not False:
                print("controller: none found")
            last_pad = False
        else:
            summary = (sorted(state.buttons), round(state.lt, 1), round(state.rt, 1),
                       round(state.lx, 1), round(state.ly, 1), round(state.rx, 1), round(state.ry, 1))
            if summary != last_pad:
                if last_pad is False or last_pad is None:
                    print(f"controller: connected ({pad.name})")
                last_pad = summary
                print("  buttons:", ", ".join(LABELS[b] for b in summary[0]) or "-",
                      f"| LT {summary[1]} RT {summary[2]} | L ({summary[3]}, {summary[4]}) R ({summary[5]}, {summary[6]})")
        time.sleep(0.02)
    print("\nDone.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--diagnose" in argv:
        diagnose()
    else:
        run_gui()
