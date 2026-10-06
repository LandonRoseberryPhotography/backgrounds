import json
import os
import tempfile
import unittest

from padmap import keys
from padmap.profile import (ProfileStore, bridge_profile, clean_binding, clean_profile, describe,
                            key, new_profile, target_matches)


class Keys(unittest.TestCase):
    def test_parse_and_aliases(self):
        self.assertEqual(keys.parse_combo("Control + Shift+S"), ["ctrl", "shift", "s"])
        self.assertEqual(keys.parse_combo("PgDn"), ["pagedown"])
        self.assertEqual(keys.format_combo(["ctrl", "pageup"]), "Ctrl+Page Up")

    def test_rejects_unknown(self):
        for bad in ("", "ctrl+", "flarp", "ctrl+flarp"):
            with self.assertRaises(ValueError, msg=bad):
                keys.parse_combo(bad)

    def test_split_join_for_editor(self):
        self.assertEqual(keys.split_combo("ctrl+shift+s"), (["ctrl", "shift"], "s"))
        self.assertEqual(keys.split_combo("ctrl"), ([], "ctrl"))
        self.assertEqual(keys.join_combo(["shift", "ctrl"], "s"), "ctrl+shift+s")

    def test_every_key_has_a_vk(self):
        for name, (vk, ext) in keys.KEYS.items():
            self.assertTrue(0 < vk < 256, name)

    def test_macro_parse(self):
        self.assertEqual(keys.parse_macro("a; wait 1s\nscroll up 2; click right"),
                         [("combo", ["a"]), ("wait", 1.0), ("scroll", 2), ("click", "right")])
        for bad in ("", "wait", "wait x", "click up", "scroll sideways", "ctrl+flarp"):
            with self.assertRaises(ValueError, msg=bad):
                keys.parse_macro(bad)


class Profiles(unittest.TestCase):
    def test_starter_profile_roundtrips_and_is_valid(self):
        p = bridge_profile()
        again, warnings = clean_profile(json.loads(json.dumps(p)))
        self.assertEqual(again, p)
        self.assertEqual(warnings, [])

    def test_bad_data_is_dropped_not_fatal(self):
        raw = {"layers": [
            {"name": "x", "bindings": {"A": key("space"), "NOPE": key("a"), "B": {"type": "key", "keys": "zzz"}}},
            {"name": "dup", "activator": "LT", "bindings": {}},
            {"name": "dup2", "activator": "LT", "bindings": {}},
            {"name": "sticky", "activator": "LS_UP", "bindings": {}},
        ]}
        p, warnings = clean_profile(raw)
        self.assertEqual(p["layers"][0]["name"], "Main")
        self.assertEqual(list(p["layers"][0]["bindings"]), ["A"])
        self.assertEqual([l["activator"] for l in p["layers"]], [None, "LT"])
        self.assertEqual(len(warnings), 4)

    def test_values_are_clamped(self):
        p, _ = clean_profile({"sticks": {"left": {"deadzone": 5, "speed": -1, "mode": "bogus"}}, "trigger_threshold": 0})
        self.assertEqual(p["sticks"]["left"], {"mode": "keys", "deadzone": 0.9, "four_way": True, "speed": 0.1})
        self.assertEqual(p["trigger_threshold"], 0.1)

    def test_describe(self):
        self.assertEqual(describe(key("ctrl+5")), "Ctrl+5")
        self.assertEqual(describe(clean_binding({"type": "mouse", "mode": "hold"})), "Left click  (hold)")
        self.assertEqual(describe(None), "")

    def test_target_matching(self):
        t = {"only_when_focused": True, "match": "bridge, photoshop"}
        self.assertTrue(target_matches(t, "Adobe Bridge.exe", ""))
        self.assertTrue(target_matches(t, "x.exe", "Photoshop 2026"))
        self.assertFalse(target_matches(t, "chrome.exe", "Gmail"))
        self.assertTrue(target_matches({"only_when_focused": False, "match": "bridge"}, "chrome.exe", ""))


class Store(unittest.TestCase):
    def test_seeds_saves_and_reloads(self):
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(d)
            self.assertEqual(store.names(), ["Bridge Backgrounds"])
            p, _ = store.load("Bridge Backgrounds")
            p["layers"][0]["bindings"]["X"] = key("f5")
            store.save(p)
            self.assertEqual(store.load("Bridge Backgrounds")[0]["layers"][0]["bindings"]["X"]["keys"], "f5")
            self.assertEqual(store.unique_name("Bridge Backgrounds"), "Bridge Backgrounds 2")
            store.remember("Bridge Backgrounds"); self.assertEqual(store.last_used(), "Bridge Backgrounds")
            self.assertEqual(store.names(), ["Bridge Backgrounds"])   # settings.json isn't a profile
            self.assertFalse([f for f in os.listdir(d) if f.endswith(".tmp")])

    def test_unsafe_names_stay_inside_the_folder(self):
        with tempfile.TemporaryDirectory() as d:
            store = ProfileStore(d)
            p = new_profile("../../evil/name")
            store.save(p)
            self.assertTrue(all(os.path.dirname(os.path.join(d, f)) == d for f in os.listdir(d)))


if __name__ == "__main__":
    unittest.main()
