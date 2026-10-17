"""Check that the emulator is reachable over ADB and that screenshots work.

    python tools/check_adb.py            # use adb.serial from config.yaml
    python tools/check_adb.py --scan     # also probe the usual emulator ports
    python tools/check_adb.py --serial 127.0.0.1:16384

Read-only: it never taps or launches anything. Saves the last screenshot to
screenshots/check_adb.png. Exit code 0 means every check passed.
"""
from __future__ import annotations

import argparse
import socket
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adb_client import AdbClient, DeviceError  # noqa: E402
from config import ROOT, Config, ConfigError, load_config  # noqa: E402
from images import write_png  # noqa: E402
from log import setup_logging  # noqa: E402

# First-instance ADB ports, plus a few extra instances, for common emulators.
COMMON_PORTS = {
    5555: "BlueStacks 5 / LDPlayer 9",
    5557: "LDPlayer 9 (2nd instance)",
    5565: "BlueStacks 5 (2nd instance)",
    5575: "BlueStacks 5 (3rd instance)",
    16384: "MuMu 12",
    16416: "MuMu 12 (2nd instance)",
    7555: "MuMu (older)",
    62001: "Nox",
    21503: "MEmu",
}

failures: list[str] = []


def ok(msg: str) -> None:
    print(f"  [ OK ] {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    failures.append(msg)


def scan_ports(client: AdbClient) -> None:
    print("\nScanning common emulator ADB ports on 127.0.0.1 ...")
    found = False
    for port, name in COMMON_PORTS.items():
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                continue
        found = True
        probe = AdbClient(f"127.0.0.1:{port}", client.package, timeout=5)
        try:
            probe.connect()
            model = probe.getprop("ro.product.model")
            print(f"  127.0.0.1:{port} answers ADB ({name}?) - model '{model}'")
        except DeviceError as e:
            print(f"  127.0.0.1:{port} is open but not ADB-ready ({name}?): {e}")
    if not found:
        print("  No common emulator port is open. Is the emulator running with ADB enabled?")


def run_checks(cfg: Config, args: argparse.Namespace) -> int:
    serial = args.serial or cfg.adb.serial
    client = AdbClient(serial, cfg.game.package, timeout=cfg.adb.timeout, adb_path=cfg.adb.adb_path)

    print("1. ADB server")
    try:
        ok(f"adb server running (protocol version {client.server_version()})")
    except DeviceError as e:
        fail(f"{e}\n         Install platform-tools or set adb.adb_path in config.yaml.")
        return 1

    if args.scan:
        scan_ports(client)

    print(f"\n2. Connect to {serial}")
    try:
        client.connect()
        ok("connected, state 'device'")
    except DeviceError as e:
        fail(str(e))
        devices = client.devices()
        print("     Devices the adb server knows:", devices or "none")
        print("     Hints: enable ADB in the emulator settings, check the port, or run with --scan.")
        return 1

    print("\n3. Device")
    model = client.getprop("ro.product.model")
    android = client.getprop("ro.build.version.release")
    ok(f"model '{model}', Android {android}")
    width, height = client.screen_size()
    dpi = client.density()
    want = (cfg.game.width, cfg.game.height)
    if (width, height) == want:
        ok(f"resolution {width}x{height}")
    else:
        fail(f"resolution {width}x{height}, expected {want[0]}x{want[1]} - change it in the emulator settings")
    if dpi == cfg.game.dpi:
        ok(f"density {dpi} dpi")
    else:
        warn(f"density {dpi} dpi, expected {cfg.game.dpi} - templates may not match at other DPIs")

    print(f"\n4. Game package {cfg.game.package}")
    if client.is_app_installed():
        ok("installed")
        running = client.is_app_running()
        fg = client.foreground_package()
        (ok if running else warn)(f"running: {running}, foreground app: {fg}")
    else:
        fail("not installed under this name")
        candidates = [p for key in ("gof", "whiteout", "century") for p in client.list_packages(key)]
        print("     Possible matches:", sorted(set(candidates)) or "none - is the game installed?")

    print(f"\n5. Screenshots ({args.shots})")
    times, image = [], None
    for _ in range(max(1, args.shots)):
        t0 = time.perf_counter()
        image = client.screenshot()
        times.append(time.perf_counter() - t0)
    h, w = image.shape[:2]
    ok(f"{w}x{h} BGR via {client.screencap_mode} screencap, median {statistics.median(times) * 1000:.0f} ms "
       f"(min {min(times) * 1000:.0f}, max {max(times) * 1000:.0f})")
    if (w, h) != want:
        fail(f"screenshot is {w}x{h}, expected {want[0]}x{want[1]}" + (" (landscape?)" if w > h else ""))
    if image.mean() < 3:
        warn("screenshot is almost entirely black - try switching the emulator's graphics renderer "
             "(DirectX <-> OpenGL), or the game may be loading")
    out = write_png(ROOT / "screenshots" / "check_adb.png", image)
    ok(f"saved {out}")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed.")
        return 1
    print("All checks passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--serial", help="override adb.serial from the config")
    parser.add_argument("--scan", action="store_true", help="probe common emulator ports")
    parser.add_argument("--shots", type=int, default=5, help="screenshots to time (default 5)")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1
    setup_logging("WARNING", cfg.logging.dir)
    try:
        return run_checks(cfg, args)
    except DeviceError as e:
        fail(f"device error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
