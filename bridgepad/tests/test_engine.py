import math
import unittest

from padmap.engine import Engine, BaseOutput
from padmap.inputs import PadState
from padmap.profile import key, new_profile


class Recorder(BaseOutput):
    """Logs what would reach the OS, after reference counting."""
    def __init__(self):
        super().__init__()
        self.log = []

    def _send_key(self, name, down): self.log.append((("+" if down else "-") + name))
    def _send_button(self, button, down): self.log.append(("m+" if down else "m-") + button)
    def _send_move(self, dx, dy): self.log.append(("move", dx, dy))
    def _send_wheel(self, notches): self.log.append(("wheel", notches))

    def take(self):
        out, self.log = self.log, []
        return out


def pad(*buttons, lt=0.0, rt=0.0, lx=0.0, ly=0.0, rx=0.0, ry=0.0):
    return PadState(frozenset(buttons), lt, rt, lx, ly, rx, ry)


class Rig:
    """Engine + recorder + a fake clock, so timing tests are exact."""
    def __init__(self, profile=None):
        self.out = Recorder()
        self.engine = Engine(self.out)
        self.now = 1000.0
        self.focused = True
        self.engine.set_profile(profile or new_profile())

    def bind(self, input_id, binding, layer=0):
        p = self.profile()
        p["layers"][layer]["bindings"][input_id] = binding
        self.engine.set_profile(p)

    def profile(self):
        return self.engine._profile

    def step(self, state, dt=0.008):
        self.now += dt
        self.engine.tick(state, self.focused, self.now)
        return self.out.take()

    def run(self, state, seconds, dt=0.008):
        events = []
        for _ in range(round(seconds / dt)):
            events += self.step(state, dt)
        return events


class KeyModes(unittest.TestCase):
    def test_tap_fires_once_per_press(self):
        r = Rig(); r.bind("A", key("space"))
        self.assertEqual(r.step(pad("A")), ["+space", "-space"])
        self.assertEqual(r.run(pad("A"), 1.0), [])
        self.assertEqual(r.step(pad()), [])
        self.assertEqual(r.step(pad("A")), ["+space", "-space"])

    def test_hold_follows_the_button(self):
        r = Rig(); r.bind("A", key("w", "hold"))
        self.assertEqual(r.step(pad("A")), ["+w"])
        self.assertEqual(r.run(pad("A"), 0.5), [])
        self.assertEqual(r.step(pad()), ["-w"])

    def test_repeat_waits_for_delay_then_steps(self):
        r = Rig(); r.bind("DPAD_RIGHT", key("right", "repeat", repeat_ms=100, delay_ms=400))
        self.assertEqual(r.step(pad("DPAD_RIGHT")), ["+right", "-right"])
        taps = r.run(pad("DPAD_RIGHT"), 0.3)         # still inside the initial delay
        self.assertEqual(taps, [])
        taps = r.run(pad("DPAD_RIGHT"), 0.7)         # 0.3..1.0s: taps at 0.4, 0.5, ... 1.0
        self.assertEqual(taps.count("+right"), 7)
        self.assertEqual(r.run(pad(), 1.0), [])      # released: stops

    def test_combo_order(self):
        r = Rig(); r.bind("X", key("ctrl+shift+s"))
        self.assertEqual(r.step(pad("X")), ["+ctrl", "+shift", "+s", "-s", "-shift", "-ctrl"])

    def test_overlapping_bindings_share_modifier(self):
        r = Rig(); r.bind("LB", key("ctrl", "hold")); r.bind("X", key("ctrl+s"))
        self.assertEqual(r.step(pad("LB")), ["+ctrl"])
        self.assertEqual(r.step(pad("LB", "X")), ["+s", "-s"])          # ctrl stays down
        self.assertEqual(r.step(pad("LB")), [])
        self.assertEqual(r.step(pad()), ["-ctrl"])

    def test_mouse_click_and_hold(self):
        r = Rig()
        r.bind("A", {"type": "mouse", "button": "left", "mode": "tap"})
        r.bind("B", {"type": "mouse", "button": "right", "mode": "hold"})
        self.assertEqual(r.step(pad("A")), ["m+left", "m-left"])
        self.assertEqual(r.step(pad("B")), ["m+right"])
        self.assertEqual(r.step(pad()), ["m-right"])

    def test_scroll_binding_repeats(self):
        r = Rig(); r.bind("Y", {"type": "scroll", "direction": "down", "repeat_ms": 100, "delay_ms": 200})
        self.assertEqual(r.step(pad("Y")), [("wheel", -1)])
        self.assertEqual(len([e for e in r.run(pad("Y"), 0.55) if e == ("wheel", -1)]), 4)

    def test_broken_binding_is_inert(self):
        r = Rig()
        p = r.profile(); p["layers"][0]["bindings"]["A"] = {"type": "key", "keys": "nonsense"}
        r.engine.set_profile(p)
        self.assertEqual(r.step(pad("A")), [])


class Macros(unittest.TestCase):
    def test_steps_run_on_schedule(self):
        r = Rig(); r.bind("A", {"type": "macro", "steps": "ctrl+a; wait 100; delete; click left"})
        self.assertEqual(r.step(pad("A")), ["+ctrl", "+a", "-a", "-ctrl"])
        self.assertEqual(r.run(pad("A"), 0.09), [])                      # waiting
        ev = r.run(pad("A"), 0.1)
        self.assertEqual(ev, ["+delete", "-delete", "m+left", "m-left"])

    def test_macro_does_not_stack_while_running(self):
        r = Rig(); r.bind("A", {"type": "macro", "steps": "a; wait 200; b"})
        r.step(pad("A")); r.step(pad()); self.assertEqual(r.step(pad("A")), [])
        self.assertEqual(r.run(pad(), 0.4), ["+b", "-b"])


class Layers(unittest.TestCase):
    def make(self):
        p = new_profile()
        p["layers"][0]["bindings"].update({"DPAD_LEFT": key("left"), "A": key("space"), "LT": key("esc")})
        p["layers"].append({"name": "Shift", "activator": "LT", "bindings": {
            "DPAD_LEFT": key("home"), "B": {"type": "none"}}})
        p["layers"][0]["bindings"]["B"] = key("enter")
        return Rig(p)

    def test_hold_activator_switches_layer(self):
        r = self.make()
        self.assertEqual(r.step(pad("DPAD_LEFT")), ["+left", "-left"])
        r.step(pad())
        r.step(pad(lt=1.0))
        self.assertEqual(r.engine.snapshot()["layer"], 1)
        self.assertEqual(r.step(pad("DPAD_LEFT", lt=1.0)), ["+home", "-home"])
        r.step(pad())
        self.assertEqual(r.engine.snapshot()["layer"], 0)

    def test_activator_does_not_fire_its_own_binding(self):
        r = self.make()
        self.assertEqual(r.step(pad(lt=1.0)), [])

    def test_unbound_inputs_fall_through_to_main(self):
        r = self.make(); r.step(pad(lt=1.0))
        self.assertEqual(r.step(pad("A", lt=1.0)), ["+space", "-space"])

    def test_none_blocks_inheritance(self):
        r = self.make(); r.step(pad(lt=1.0))
        self.assertEqual(r.step(pad("B", lt=1.0)), [])
        r.step(pad())
        self.assertEqual(r.step(pad("B")), ["+enter", "-enter"])

    def test_held_key_survives_layer_change(self):
        p = new_profile()
        p["layers"][0]["bindings"]["A"] = key("w", "hold")
        p["layers"].append({"name": "S", "activator": "LB", "bindings": {"A": key("s", "hold")}})
        r = Rig(p)
        self.assertEqual(r.step(pad("A")), ["+w"])
        self.assertEqual(r.step(pad("A", "LB")), [])
        self.assertEqual(r.step(pad("LB")), ["-w"])      # releases what it pressed, not the new layer's key


class Gating(unittest.TestCase):
    def test_focus_loss_releases_held_keys(self):
        r = Rig(); r.bind("A", key("w", "hold"))
        r.step(pad("A"))
        r.focused = False
        self.assertEqual(r.step(pad("A")), ["-w"])
        self.assertFalse(r.engine.snapshot()["live"])

    def test_no_phantom_press_when_focus_returns_with_button_held(self):
        r = Rig(); r.bind("A", key("space"))
        r.focused = False
        r.step(pad("A"))
        r.focused = True
        self.assertEqual(r.step(pad("A")), [])
        r.step(pad())
        self.assertEqual(r.step(pad("A")), ["+space", "-space"])

    def test_disable_releases_and_silences(self):
        r = Rig(); r.bind("A", key("w", "hold"))
        r.step(pad("A"))
        r.engine.set_enabled(False)
        self.assertEqual(r.out.take(), ["-w"])
        self.assertEqual(r.step(pad("B", "A")), [])

    def test_controller_unplugged_releases(self):
        r = Rig(); r.bind("A", key("w", "hold"))
        r.step(pad("A"))
        self.assertEqual(r.step(None), ["-w"])

    def test_profile_swap_releases(self):
        r = Rig(); r.bind("A", key("w", "hold"))
        r.step(pad("A"))
        r.engine.set_profile(new_profile())
        self.assertEqual(r.out.take(), ["-w"])


class Triggers(unittest.TestCase):
    def test_threshold_with_hysteresis(self):
        r = Rig(); r.bind("RT", key("space", "hold"))
        self.assertEqual(r.step(pad(rt=0.4)), [])
        self.assertEqual(r.step(pad(rt=0.55)), ["+space"])
        self.assertEqual(r.step(pad(rt=0.45)), [])            # dipped under 0.5 but inside hysteresis band
        self.assertEqual(r.step(pad(rt=0.3)), ["-space"])


def tilt(angle_deg, mag=1.0):
    a = math.radians(angle_deg)
    return dict(lx=mag * math.cos(a), ly=mag * math.sin(a))


class Sticks(unittest.TestCase):
    def arrows(self, side="LS", **kw):
        r = Rig()
        for d, k in (("UP", "up"), ("DOWN", "down"), ("LEFT", "left"), ("RIGHT", "right")):
            r.bind(f"{side}_{d}", key(k, "hold"))
        return r

    def test_four_way_picks_dominant_axis(self):
        r = self.arrows()
        self.assertEqual(r.step(pad(**tilt(10))), ["+right"])
        self.assertEqual(r.step(pad(**tilt(80))), ["-right", "+up"])
        self.assertEqual(r.step(pad(**tilt(200))), ["-up", "+left"])
        self.assertEqual(r.step(pad(**tilt(270))), ["-left", "+down"])
        self.assertEqual(r.step(pad()), ["-down"])

    def test_four_way_does_not_flicker_on_the_diagonal(self):
        r = self.arrows()
        r.step(pad(**tilt(20)))
        events = []
        for a in (44, 46, 44, 46, 45, 47):           # wobbling around the diagonal
            events += r.step(pad(**tilt(a)))
        self.assertEqual(events, [])

    def test_eight_way_allows_diagonals(self):
        r = self.arrows()
        p = r.profile(); p["sticks"]["left"]["four_way"] = False; r.engine.set_profile(p)
        self.assertEqual(sorted(r.step(pad(**tilt(45)))), ["+right", "+up"])

    def test_deadzone(self):
        r = self.arrows()
        self.assertEqual(r.step(pad(lx=0.3)), [])
        self.assertEqual(r.step(pad(lx=0.4)), ["+right"])
        self.assertEqual(r.step(pad(lx=0.3)), [])           # still held: 0.3 > 0.35 * 0.8
        self.assertEqual(r.step(pad(lx=0.2)), ["-right"])

    def test_mouse_mode_moves_pointer(self):
        r = Rig()
        p = r.profile(); p["sticks"]["right"]["mode"] = "mouse"; r.engine.set_profile(p)
        moves = [e for e in r.run(pad(rx=1.0), 1.0) if e[0] == "move"]
        dx = sum(e[1] for e in moves)
        self.assertTrue(1300 <= dx <= 1450, dx)
        self.assertEqual(sum(e[2] for e in moves), 0)
        self.assertEqual([e for e in r.run(pad(rx=0.1), 0.5) if e[0] == "move"], [])

    def test_mouse_up_is_negative_y(self):
        r = Rig()
        p = r.profile(); p["sticks"]["left"]["mode"] = "mouse"; r.engine.set_profile(p)
        moves = [e for e in r.run(pad(ly=1.0), 0.2) if e[0] == "move"]
        self.assertLess(sum(e[2] for e in moves), 0)

    def test_scroll_mode_up_is_positive(self):
        r = Rig()
        p = r.profile(); p["sticks"]["right"]["mode"] = "scroll"; r.engine.set_profile(p)
        up = sum(e[1] for e in r.run(pad(ry=1.0), 1.0) if e[0] == "wheel")
        self.assertTrue(12 <= up <= 15, up)
        down = sum(e[1] for e in r.run(pad(ry=-1.0), 1.0) if e[0] == "wheel")
        self.assertTrue(-15 <= down <= -12, down)


if __name__ == "__main__":
    unittest.main()
