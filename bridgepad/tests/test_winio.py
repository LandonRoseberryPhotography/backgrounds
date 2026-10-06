import ctypes
import unittest

from padmap import winio
from padmap.keys import KEYS


class StructLayouts(unittest.TestCase):
    """SendInput silently fails if sizeof(INPUT) is wrong, and we can only run it on Windows, so pin the sizes."""

    def test_input_size_matches_win32(self):
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(ctypes.sizeof(winio.INPUT), expected)

    def test_xinput_state_is_16_bytes(self):
        self.assertEqual(ctypes.sizeof(winio.XINPUT_STATE), 16)
        self.assertEqual(ctypes.sizeof(winio.XINPUT_GAMEPAD), 12)

    def test_keyboard_union_offsets(self):
        item = winio.INPUT(type=winio.INPUT_KEYBOARD)
        item.ki = winio.KEYBDINPUT(0x41, 0x1E, 2, 0, 0)
        raw = bytes(item)
        self.assertEqual(raw[8:10], b"\x41\x00")          # wVk sits right after the 8-byte type+padding
        self.assertEqual(raw[10:12], b"\x1e\x00")


class Tables(unittest.TestCase):
    def test_extended_keys_flagged(self):
        for name in ("left", "right", "up", "down", "home", "end", "pageup", "pagedown", "delete", "insert"):
            self.assertTrue(KEYS[name][1], name)
        self.assertFalse(KEYS["a"][1])


if __name__ == "__main__":
    unittest.main()
