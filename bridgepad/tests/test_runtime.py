import time
import unittest

from padmap.engine import Engine
from padmap.inputs import PadState
from padmap.profile import key, new_profile
from padmap.runtime import Runtime
from tests.test_engine import Recorder


class ScriptedPad:
    available = True
    name = "scripted"

    def __init__(self):
        self.state = None
        self.explode = False

    def read(self):
        if self.explode:
            raise OSError("controller driver hiccup")
        return self.state


def wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


class RuntimeLoop(unittest.TestCase):
    def setUp(self):
        self.out = Recorder()
        self.engine = Engine(self.out)
        profile = new_profile()
        profile["target"]["match"] = "bridge"
        profile["layers"][0]["bindings"].update({"A": key("space"), "B": key("w", "hold")})
        self.engine.set_profile(profile)
        self.pad = ScriptedPad()
        self.front = ("Adobe Bridge.exe", "Adobe Bridge 2026")
        self.rt = Runtime(self.engine, self.pad, lambda: self.front)
        self.rt.start()
        self.addCleanup(self.rt.stop)

    def test_presses_flow_through_when_bridge_is_in_front(self):
        self.pad.state = PadState(frozenset({"A"}))
        self.assertTrue(wait_for(lambda: self.out.log == ["+space", "-space"]))
        self.assertTrue(self.rt.connected and self.rt.focused)

    def test_nothing_is_sent_to_other_apps_and_held_keys_are_released_on_switch(self):
        self.pad.state = PadState(frozenset({"B"}))
        self.assertTrue(wait_for(lambda: self.out.log == ["+w"]))
        self.front = ("chrome.exe", "Gmail")                     # alt-tab away mid-hold
        self.assertTrue(wait_for(lambda: self.out.log == ["+w", "-w"]))
        self.pad.state = PadState(frozenset({"A", "B"}))
        time.sleep(0.15)
        self.assertEqual(self.out.log, ["+w", "-w"])             # still nothing while elsewhere

    def test_unplugging_releases_and_reports(self):
        self.pad.state = PadState(frozenset({"B"}))
        self.assertTrue(wait_for(lambda: self.out.log == ["+w"]))
        self.pad.state = None
        self.assertTrue(wait_for(lambda: self.out.log == ["+w", "-w"]))
        self.assertFalse(self.rt.connected)

    def test_errors_dont_kill_the_loop_or_leave_keys_down(self):
        self.pad.state = PadState(frozenset({"B"}))
        self.assertTrue(wait_for(lambda: self.out.log == ["+w"]))
        self.pad.explode = True
        self.assertTrue(wait_for(lambda: "hiccup" in self.rt.error))
        self.assertEqual(self.out.log, ["+w", "-w"])
        self.pad.explode = False
        self.assertTrue(wait_for(lambda: self.rt.error == ""))
        self.pad.state = PadState(frozenset({"A"}))
        self.assertTrue(wait_for(lambda: self.out.log[-2:] == ["+space", "-space"]))

    def test_stop_releases_everything(self):
        self.pad.state = PadState(frozenset({"B"}))
        self.assertTrue(wait_for(lambda: self.out.log == ["+w"]))
        self.rt.stop()
        self.assertEqual(self.out.log, ["+w", "-w"])


if __name__ == "__main__":
    unittest.main()
