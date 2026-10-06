# BridgePad

Use an Xbox controller to drive Adobe Bridge. Every button, trigger, stick direction and stick click is
mappable to a key, a shortcut, a macro, a mouse click or the scroll wheel, and you can add layers
(hold a button to get a second set of mappings), like reWASD's shift modes.

Windows only. No installs beyond Python itself.

## Start it

1. Install Python 3.9 or newer from python.org (the default options are fine).
2. Plug in the controller (USB, or paired over Bluetooth / the Xbox wireless adapter).
3. Double-click **BridgePad.pyw**.

If nothing opens, double-click **Start BridgePad (shows errors).bat** instead. A failed start is also written
to `bridgepad-error.log`. **Check my controller.bat** prints what the program can see (controller, focused
app, whether it can send keystrokes), which is what to send over if something's off.

## Using it

Click a control on the picture, or a row in the list, then choose what it does on the right.
Changes apply immediately and save automatically. There's no Save button.

- **Blue outline** on the picture = mapped on the layer you're viewing. **Gold** = pressed right now, so the
  picture doubles as a button tester.
- **Keyboard**: tick modifiers, pick a key (or hit **Record…** and press it). Then choose how it behaves:
  - *Tap*: one press per button press.
  - *Hold*: key stays down while you hold the button.
  - *Repeat*: taps, then keeps tapping while held. This is the one for stepping through backgrounds; you set the
    delay before it starts and the speed.
- **Macro**: one step per line, e.g. `ctrl+a`, `wait 200`, `click left`, `scroll down 3`.
- **Layers**: "+ Add layer", then pick the button that activates it. While you hold that button, anything you've
  mapped on the layer wins; everything you haven't mapped falls back to the Main layer ("Block" stops that).
  The hold button itself doesn't fire its own mapping.
- **Sticks**: each stick can be four direction keys (4-way or 8-way), a mouse pointer, or a scroll wheel. Select
  a stick direction or click to see its deadzone and speed. Triggers have an adjustable press point.
- **Only send input while this app is in front**: on by default, matching `bridge` against the focused app's
  file name and window title. Alt-tab away and everything is released. It resumes when Bridge is back in front.
  Separate several apps with commas (`bridge, photoshop`). Untick it to send everywhere.
- **Profiles** live in the `profiles` folder as plain JSON files. Copy them to back up or share.

## The starter profile ("Bridge Backgrounds")

| Input | Does |
|---|---|
| D-pad, left stick, LB / RB | Arrow keys (repeating), so you can step through the backgrounds |
| A | Space (Bridge's full screen preview) |
| B | Esc (leave preview / slideshow) |
| Right stick | Scrolls the thumbnail grid |
| Hold LT + D-pad | Left = Home, Right = End, Up / Down = Page Up / Page Down |

Everything else is unmapped. Change whatever you like; it's a starting point.

## Key names

Letters, digits, `f1`–`f24`, `left right up down`, `space enter esc tab backspace delete insert home end
pageup pagedown`, `ctrl shift alt win`, `num0`–`num9`, punctuation (`; = , - . / ` [ \ ] '`), and media keys
(`volumeup volumedown volumemute mediaplay medianext mediaprev`). Combine with `+`: `ctrl+shift+s`. Common
aliases work (`pgup`, `return`, `del`, `escape`).

## If something doesn't work

- **Controller isn't found.** The status bar says so. Run *Check my controller.bat* and press a button. If the
  buttons print there but not in the app, send me that output.
- **Keys reach other apps but not Bridge.** Windows blocks a normal program from typing into an app that was
  started "as administrator". Run both the same way (close Bridge, reopen it normally).
- **Xbox button / Share button.** The Xbox (Guide) button is read when Windows allows it, but Windows' Game Bar
  usually grabs it first. The Series X|S Share button isn't visible to any program using XInput, so it can't
  be mapped.
- **PlayStation / Switch controllers** need a layer like DS4Windows to appear as an Xbox controller first.
- **Stuck key.** Every key is released when you pause, alt-tab, unplug, change profiles or close the app. If
  one ever sticks, tap it on the real keyboard.

## For developers

Pure standard library. The mapping logic (`padmap/engine.py`) knows nothing about Windows; `padmap/winio.py` is
the only file that touches XInput / SendInput.

    python -m unittest discover -s tests -t .      # GUI tests need tkinter and a display (xvfb-run on Linux)
    python -m padmap --diagnose
