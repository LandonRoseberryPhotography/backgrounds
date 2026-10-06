"""Drives the real editor widgets. Needs tkinter and a display (run with xvfb-run on a headless machine)."""
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None

from padmap.engine import Engine
from padmap.inputs import PadState
from padmap.profile import ProfileStore
from padmap.runtime import NullPad, Runtime
from tests.test_engine import Recorder


@unittest.skipIf(tk is None, "tkinter not installed")
class EditorTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        from padmap import gui
        self.gui = gui
        self.dir = tempfile.mkdtemp()
        self.out = Recorder()
        self.engine = Engine(self.out)
        self.runtime = Runtime(self.engine, NullPad(), lambda: ("", ""))
        self.store = ProfileStore(self.dir)
        self.app = gui.App(self.root, self.store, self.engine, self.runtime)
        self.now = 100.0

    def tearDown(self):
        self.app.stop_timers()
        self.root.destroy()

    def press(self, *buttons, **axes):
        self.now += 0.01
        self.engine.tick(PadState(frozenset(buttons), **axes), True, self.now)
        return self.out.take()

    def choose_type(self, kind):
        self.app.v_type.set(self.gui.TYPE_LABELS[kind])
        self.app._show_frames()
        self.app._on_edit()

    def test_assign_shortcut_reaches_the_engine(self):
        a = self.app
        a.select("X")
        self.choose_type("key")
        self.assertIn("Pick a key", a.v_error.get())          # nothing chosen yet: not saved
        self.assertNotIn("X", a.layer["bindings"])
        a.v_mods["ctrl"].set(True)
        a.v_key.set("F5")
        a._on_edit()
        self.assertEqual(a.layer["bindings"]["X"]["keys"], "ctrl+f5")
        self.assertEqual(self.press("X"), ["+ctrl", "+f5", "-f5", "-ctrl"])
        self.assertEqual(a.tree.item("X", "values")[1], "Ctrl+F5")

    def test_hold_and_repeat_settings(self):
        a = self.app
        a.select("Y")
        self.choose_type("key")
        a.v_key.set("Page Down")
        a.v_mode.set("repeat"); a.v_delay.set("500"); a.v_repeat.set("90")
        a._on_edit()
        b = a.layer["bindings"]["Y"]
        self.assertEqual((b["keys"], b["mode"], b["delay_ms"], b["repeat_ms"]), ("pagedown", "repeat", 500, 90))

    def test_bad_macro_is_reported_and_not_saved(self):
        a = self.app
        a.select("X")
        self.choose_type("macro")
        a.t_macro.insert("1.0", "ctrl+a; wait soon")
        a._on_edit()
        self.assertTrue(a.v_error.get())
        self.assertNotIn("X", a.layer["bindings"])
        a.t_macro.delete("1.0", "end"); a.t_macro.insert("1.0", "ctrl+a; wait 100; delete")
        a._on_edit()
        self.assertEqual(a.v_error.get(), "")
        self.assertEqual(a.tree.item("X", "values")[1], "Macro, 3 steps")

    def test_clearing_main_binding_unbinds(self):
        a = self.app
        a.select("A")
        self.assertIn("A", a.layer["bindings"])
        self.choose_type("none")
        self.assertNotIn("A", a.layer["bindings"])
        self.assertEqual(self.press("A"), [])

    def test_layers_inherit_override_and_block(self):
        a = self.app
        a.layer_idx = 1; a._rebuild_layers()
        a.select("A")                                           # shift layer doesn't bind A: inherits Main
        self.assertEqual(a.v_type.get(), self.gui.TYPE_LABELS["inherit"])
        self.assertTrue(a.tree.item("A", "values")[1].startswith("(Main)"))
        self.choose_type("block")
        self.press(lt=1.0)
        self.assertEqual(self.press("A", lt=1.0), [])
        self.choose_type("key"); a.v_key.set("Enter"); a._on_edit()
        self.press(); self.press(lt=1.0)
        self.assertEqual(self.press("A", lt=1.0), ["+enter", "-enter"])
        self.choose_type("inherit")
        self.assertNotIn("A", a.layer["bindings"])

    def test_add_change_and_remove_layer(self):
        a = self.app
        with mock.patch.object(self.gui.simpledialog, "askstring", return_value="Ratings"), \
                mock.patch.object(self.gui.messagebox, "showinfo"):
            a.add_layer()
        self.assertEqual([l["name"] for l in a.profile["layers"]], ["Main", "Shift (hold LT)", "Ratings"])
        self.assertEqual(a.layer["activator"], "RT")            # first unused of LT, RT, ...
        a.v_activator.set("Right bumper (RB)"); a._set_activator()
        self.assertEqual(a.layer["activator"], "RB")
        a.select("A"); self.choose_type("key"); a.v_key.set("5"); a.v_mods["ctrl"].set(True); a._on_edit()
        self.press("RB")
        self.assertEqual(self.press("A", "RB"), ["+ctrl", "+5", "-5", "-ctrl"])
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            a.remove_layer()
        self.assertEqual(len(a.profile["layers"]), 2)
        self.assertEqual(a.layer_idx, 0)

    def test_stick_and_trigger_settings(self):
        a = self.app
        a.select("RS_UP")
        self.assertEqual(a.v_smode.get(), self.gui.STICK_MODE_LABELS["scroll"])   # starter profile
        a.v_smode.set(self.gui.STICK_MODE_LABELS["mouse"]); a.v_sspeed.set(2.0); a._on_stick()
        self.assertEqual(a.profile["sticks"]["right"]["mode"], "mouse")
        self.assertEqual(a.profile["sticks"]["right"]["speed"], 2.0)
        a.select("LS_UP")
        a.v_four.set(False); a.v_sdead.set(0.5); a._on_stick()
        self.assertEqual(a.profile["sticks"]["left"]["deadzone"], 0.5)
        self.assertFalse(a.profile["sticks"]["left"]["four_way"])
        a.select("LT")
        a.v_thr.set(0.8); a._on_trigger()
        self.assertEqual(a.profile["trigger_threshold"], 0.8)
        self.assertEqual(self.press(lt=0.7), [])                # below the new press point

    def test_recorder_captures_shortcuts_and_lone_modifiers(self):
        got = []
        rec = self.gui.KeyRecorder(self.root, lambda mods, key: got.append((mods, key)))
        ev = lambda sym: SimpleNamespace(keycode=0, keysym=sym)
        rec._down(ev("Control_L")); rec._down(ev("Shift_L")); rec._down(ev("s"))
        self.assertEqual(got, [(["ctrl", "shift"], "s")])
        rec2 = self.gui.KeyRecorder(self.root, lambda mods, key: got.append((mods, key)))
        rec2._down(ev("Control_L")); rec2._up(ev("Control_L"))
        self.assertEqual(got[-1], ([], "ctrl"))
        rec3 = self.gui.KeyRecorder(self.root, lambda mods, key: got.append((mods, key)))
        rec3._down(ev("Prior"))
        self.assertEqual(got[-1], ([], "pageup"))

    def test_record_button_fills_the_editor(self):
        a = self.app
        a.select("X")
        a.record_key = lambda: None
        self.choose_type("key")
        # what the recorder callback does:
        a._loading = True
        a.v_mods["alt"].set(True); a.v_key.set(self.gui.pretty_key("left"))
        a._loading = False
        a._on_edit()
        self.assertEqual(a.layer["bindings"]["X"]["keys"], "alt+left")

    def test_profile_management(self):
        a = self.app
        with mock.patch.object(self.gui.simpledialog, "askstring", return_value="Headshot Room"):
            a.new_profile()
        self.assertEqual(a.profile["name"], "Headshot Room")
        self.assertEqual(a.profile["layers"][0]["bindings"], {})
        a.select("A"); self.choose_type("key"); a.v_key.set("Space"); a._on_edit()
        a._flush_save()
        self.assertEqual(self.store.load("Headshot Room")[0]["layers"][0]["bindings"]["A"]["keys"], "space")
        a.duplicate_profile()
        self.assertEqual(a.profile["name"], "Headshot Room copy")
        with mock.patch.object(self.gui.simpledialog, "askstring", return_value="Studio B"):
            a.rename_profile()
        self.assertEqual(self.store.names(), ["Bridge Backgrounds", "Headshot Room", "Studio B"])
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            a.delete_profile()
        self.assertEqual(self.store.names(), ["Bridge Backgrounds", "Headshot Room"])   # and it stays deleted
        time.sleep(0.5); self.root.update()
        self.assertEqual(self.store.names(), ["Bridge Backgrounds", "Headshot Room"])

    def test_last_profile_is_remembered_and_target_edits_apply(self):
        a = self.app
        a.v_match.set("bridge, photoshop"); a._on_target()
        self.assertEqual(self.engine.target["match"], "bridge, photoshop")
        a.v_only_focused.set(False); a._on_target()
        self.assertFalse(self.engine.target["only_when_focused"])
        a._flush_save()
        again = self.gui.App(tk.Toplevel(self.root), self.store, Engine(Recorder()), self.runtime)
        self.assertEqual(again.profile["target"]["match"], "bridge, photoshop")
        again.stop_timers()

    def test_live_map_tracks_pressed_inputs(self):
        self.press("A", "DPAD_LEFT", lt=1.0, lx=1.0)
        self.app._tick_ui(); self.root.update()
        snap = self.engine.snapshot()
        self.assertTrue({"A", "DPAD_LEFT", "LT", "LS_RIGHT"} <= snap["pressed"])
        m = self.app.map
        self.assertEqual(m.itemcget(m._shapes["A"][0], "fill"), self.gui.C["gold"])
        self.assertNotEqual(m.itemcget(m._shapes["B"][0], "fill"), self.gui.C["gold"])


if __name__ == "__main__":
    unittest.main()
