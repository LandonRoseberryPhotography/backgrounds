"""Double-click to start BridgePad (no console window). Errors are saved to bridgepad-error.log."""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    from padmap.app import main
    main()
except Exception:
    detail = traceback.format_exc()
    try:
        with open(os.path.join(HERE, "bridgepad-error.log"), "w", encoding="utf-8") as fh:
            fh.write(detail)
    except OSError:
        pass
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("BridgePad couldn't start", detail[-1500:])
    except Exception:
        pass
