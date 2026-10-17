"""Save screenshots and crop template images from them.

    python tools/capture.py shots                    # save full screenshots, one name per screen
    python tools/capture.py crop --screen city       # screenshot now, crop templates into templates/city/
    python tools/capture.py crop --image screenshots/city.png --screen city

Cropping: drag a box and press ENTER or SPACE, then type a name in the console, e.g.
`btn_missions` (goes to the --screen folder) or `popups/btn_close` (explicit folder).
Press C or ESC in the window with no box drawn to finish. Templates are saved at full
resolution with a .json sidecar recording the crop region and source screenshot.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import re
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adb_client import AdbClient, DeviceError  # noqa: E402
from config import ROOT, ConfigError, load_config  # noqa: E402
from images import read_image, write_png  # noqa: E402

SHOTS_DIR = ROOT / "screenshots"
TEMPLATES_DIR = ROOT / "templates"
WINDOW = "capture: drag a box, ENTER = accept, C = finish"
CROP_HELP = ("Drag a box, press ENTER or SPACE, then type a name here (e.g. btn_missions or popups/btn_close).\n"
             "Press C or ESC in the window with no box drawn to finish.")
SHOT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
TEMPLATE_NAME_RE = re.compile(r"^([a-z0-9_]+/)?[a-z0-9_]+$")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in itertools.count(2):
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not candidate.exists():
            return candidate


def display_height() -> int:
    """Usable screen height in pixels, so the preview window fits on a laptop screen."""
    if sys.platform == "win32":
        import ctypes
        try:
            # Without this Windows bitmap-stretches the window by the display scaling (125-150%).
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass
        return ctypes.windll.user32.GetSystemMetrics(1) - 120  # minus taskbar and title bar
    return 900


def connect(args: argparse.Namespace) -> AdbClient:
    cfg = load_config(args.config)
    client = AdbClient(args.serial or cfg.adb.serial, cfg.game.package,
                       timeout=cfg.adb.timeout, adb_path=cfg.adb.adb_path)
    client.connect()
    return client


def cmd_shots(args: argparse.Namespace) -> None:
    client = connect(args)
    print("Go to a screen in the game, then type a name for it here and press Enter.")
    print("Blank name = timestamp, q = quit. Files go to screenshots/.")
    while True:
        name = input("screen name> ").strip()
        if name.lower() in ("q", "quit", "exit"):
            return
        name = name or time.strftime("shot_%Y%m%d_%H%M%S")
        if not SHOT_NAME_RE.match(name):
            print("  use letters, digits, _ or -")
            continue
        path = write_png(unique_path(SHOTS_DIR / f"{name}.png"), client.screenshot())
        print(f"  saved {path.relative_to(ROOT)}")


def cmd_crop(args: argparse.Namespace) -> None:
    if args.image:
        source = Path(args.image).resolve()
        image = read_image(source)
    else:
        image = connect(args).screenshot()
        source = write_png(unique_path(SHOTS_DIR / time.strftime("crop_src_%Y%m%d_%H%M%S.png")), image)
        print(f"Saved source screenshot {source.relative_to(ROOT)}")
    try:
        source_ref = source.relative_to(ROOT).as_posix()
    except ValueError:
        source_ref = str(source)

    h, w = image.shape[:2]
    scale = args.scale or min(1.0, display_height() / h)
    preview = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale != 1 else image.copy()
    print(CROP_HELP)

    screen = args.screen
    saved = 0
    while True:
        bx, by, bw, bh = cv2.selectROI(WINDOW, preview, showCrosshair=True, fromCenter=False)
        if bw == 0 or bh == 0:
            break
        # Map the preview box back to full resolution, rounding outwards.
        x0, y0 = math.floor(bx / scale), math.floor(by / scale)
        x1, y1 = min(w, math.ceil((bx + bw) / scale)), min(h, math.ceil((by + bh) / scale))
        cv2.waitKey(1)
        name = input(f"name for {x1 - x0}x{y1 - y0} crop at ({x0}, {y0}) [blank = discard]> ").strip().lower()
        if not name:
            continue
        if not TEMPLATE_NAME_RE.match(name):
            print("  use lowercase letters, digits and _, optionally prefixed by folder/")
            continue
        folder, _, stem = name.rpartition("/")
        if not folder:
            while not screen:
                screen = input("screen folder for templates (e.g. city, popups)> ").strip().lower()
            folder = screen
        path = TEMPLATES_DIR / folder / f"{stem}.png"
        if path.exists() and input(f"  {path.relative_to(ROOT)} exists, overwrite? [y/N]> ").strip().lower() != "y":
            continue
        write_png(path, image[y0:y1, x0:x1])
        meta = {
            "region": [x0, y0, x1 - x0, y1 - y0],
            "screen_size": [w, h],
            "source": source_ref,
            "captured": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(f"  saved {path.relative_to(ROOT)}")
        saved += 1
        cv2.rectangle(preview, (bx, by), (bx + bw, by + bh), (0, 255, 0), 1)
        cv2.putText(preview, stem, (bx, max(12, by - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    cv2.destroyAllWindows()
    print(f"{saved} template(s) saved.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--serial", help="override adb.serial from the config")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("shots", help="save full screenshots to screenshots/")
    crop = sub.add_parser("crop", help="crop templates from a screenshot")
    crop.add_argument("--image", help="crop from this file instead of taking a screenshot")
    crop.add_argument("--screen", help="default templates/ subfolder, e.g. city or popups")
    crop.add_argument("--scale", type=float, help="preview scale (default: fit the screen height)")
    args = parser.parse_args()

    try:
        {"shots": cmd_shots, "crop": cmd_crop}[args.command](args)
    except (ConfigError, DeviceError, ValueError) as e:
        print(f"Error: {e}")
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
