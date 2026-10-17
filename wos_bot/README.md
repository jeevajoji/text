# Whiteout Survival bot

Automates daily chores in Whiteout Survival on an Android emulator, driven over ADB from Python.

**Status: step 1 of 3.** ADB connection, screenshots and the capture tool are done. Vision and
screen detection come next, then the tasks one at a time.

## Layout

```
adb_client.py      ADB wrapper: connect, screenshot (in memory), tap/swipe/back, launch/kill, dry-run
config.py          loads config.yaml into typed dataclasses (typos are errors)
config.yaml        settings
log.py             console + file logging, failure screenshots in logs/failures/
images.py          PNG read/write that works with non-ASCII Windows paths
tools/check_adb.py checks ADB, resolution, game package and screenshot speed (read-only)
tools/capture.py   saves screenshots and crops templates from them
templates/         template PNGs, one folder per screen
screenshots/       full screenshots (commit them so they can be reviewed)
tasks/             one module per task (step 3)
```

Still to come: `vision.py`, `screens.py`, `popup_handler.py` (step 2), plus `main.py` and the
tasks (step 3).

## Setup (Windows)

1. **Emulator:** set the resolution to **720x1280 portrait, 240 DPI** and turn on ADB in its
   settings. The usual ADB addresses are:
   - BlueStacks 5: `127.0.0.1:5555`. The ADB toggle is under Settings > Advanced and shows the port.
   - LDPlayer 9: `127.0.0.1:5555` (ADB debugging is under Settings > Other settings).
   - MuMu 12: `127.0.0.1:16384`.

   Put the address in `config.yaml` under `adb.serial`.

2. **Python 3.11+**, from this folder:
   ```
   py -3.11 -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
   You don't need to install adb separately: `adbutils` ships `adb.exe`.

3. **Check the connection** with the game open on the city screen:
   ```
   python tools\check_adb.py
   python tools\check_adb.py --scan      # if it can't connect: probes the usual emulator ports
   ```
   It reports the ADB server, the connection, resolution/DPI, whether `com.gof.global` is
   installed and in front, and how long screenshots take. The last screenshot goes to
   `screenshots\check_adb.png`. It never taps anything.

## Capturing screenshots and templates

```
python tools\capture.py shots                  # go to a screen, type a name, Enter. q quits.
python tools\capture.py crop --screen city     # screenshot now, drag boxes to save templates
python tools\capture.py crop --image screenshots\city.png --screen city
```

In crop mode, drag a box and press Enter, then type a name in the console (`btn_missions`, or
`popups/btn_close` to choose another folder). Press `C` with no box drawn to finish. Each template
gets a `.json` file next to it with its crop region.

## Troubleshooting

- **"adb server version doesn't match" / connection keeps dropping:** two different adb versions
  are fighting over port 5037, for example the emulator's own adb (BlueStacks `HD-Adb.exe`,
  LDPlayer's `adb.exe`) and another one. Set `adb.adb_path` to one of them, and use that same
  adb for anything else you run.
- **Black screenshots:** switch the emulator's graphics renderer (DirectX/OpenGL).
- **Wrong resolution:** the bot expects exactly 720x1280. Templates won't match at other sizes.

## Tests

```
pip install -r requirements-dev.txt
pytest
```
The tests use a fake device, so no emulator is needed.
