"""Thin ADB wrapper over adbutils: connect, in-memory screenshots, input, app control.

Every command that changes device state goes through `_input()`, so dry-run only has to
intercept there. Screenshots and read-only queries still run in dry-run mode, so the rest
of the bot sees the real screen.
"""
from __future__ import annotations

import logging
import os
import re
import struct
import time
from typing import Callable, TypeVar

import adbutils
import cv2
import numpy as np

log = logging.getLogger(__name__)

T = TypeVar("T")

KEYCODE_BACK = 4

# android.graphics.PixelFormat values found in the raw screencap header.
_RGBA_8888 = 1
_RGBX_8888 = 2
_BGRA_8888 = 5

# Raised by adbutils/sockets when the server or the emulator link drops.
_LINK_ERRORS = (adbutils.AdbError, OSError)


class DeviceError(RuntimeError):
    """The emulator could not be reached or an ADB command failed."""


def decode_raw_screencap(data: bytes) -> np.ndarray:
    """Decode `screencap` (without -p) output into a BGR image.

    The header is width, height, format as little-endian uint32, plus a 4-byte colour
    space on Android 9+. The header length is inferred from the payload size rather than
    from the Android version.
    """
    if len(data) < 12:
        raise ValueError(f"raw screencap too short ({len(data)} bytes)")
    width, height, fmt = struct.unpack_from("<3I", data)
    if fmt not in (_RGBA_8888, _RGBX_8888, _BGRA_8888):
        raise ValueError(f"unsupported raw pixel format {fmt}")
    size = width * height * 4
    header = len(data) - size
    if header not in (12, 16):
        raise ValueError(f"raw screencap is {len(data)} bytes, expected {size}+12/16 for {width}x{height}")
    rgba = np.frombuffer(data, dtype=np.uint8, count=size, offset=header).reshape(height, width, 4)
    return cv2.cvtColor(rgba, cv2.COLOR_BGRA2BGR if fmt == _BGRA_8888 else cv2.COLOR_RGBA2BGR)


def decode_png(data: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"PNG screencap could not be decoded ({len(data)} bytes)")
    return image


class AdbClient:
    _FOCUS_RE = re.compile(r"mCurrentFocus=Window\{[^}]*?\s([\w.]+)/[^\s}]+\}")
    _RESUMED_RE = re.compile(r"ResumedActivity: ?ActivityRecord\{\S+ \S+ ([\w.]+)/")

    def __init__(self, serial: str, package: str, *, timeout: float = 10.0, adb_path: str = "",
                 dry_run: bool = False):
        if adb_path:
            # adbutils only runs adb itself to start the server when none is listening.
            os.environ["ADBUTILS_ADB_PATH"] = adb_path
        self.serial = serial
        self.package = package
        self.timeout = timeout
        self.dry_run = dry_run
        self._adb = adbutils.AdbClient(socket_timeout=timeout)
        self._device: adbutils.AdbDevice | None = None
        self._raw_screencap = True  # switched off if the device's raw format isn't understood

    # ------------------------------------------------------------------ connection

    @property
    def device(self) -> adbutils.AdbDevice:
        if self._device is None:
            self.connect()
        return self._device

    def connect(self) -> None:
        """`adb connect` host:port serials, then wait until the device state is 'device'."""
        try:
            if ":" in self.serial:
                msg = self._adb.connect(self.serial, timeout=self.timeout)
                log.debug("adb connect %s: %s", self.serial, msg)
                if not msg.startswith(("connected", "already connected")):
                    raise DeviceError(f"adb connect {self.serial}: {msg}")
            device = self._adb.device(serial=self.serial)
            deadline = time.monotonic() + self.timeout
            while (state := self._state(device)) != "device":
                if time.monotonic() > deadline:
                    raise DeviceError(f"{self.serial} state is '{state}', expected 'device'")
                time.sleep(0.5)
        except _LINK_ERRORS as e:
            raise DeviceError(f"cannot reach {self.serial}: {e}") from e
        self._device = device
        log.info("Connected to %s", self.serial)

    @staticmethod
    def _state(device: adbutils.AdbDevice) -> str:
        try:
            return device.get_state()
        except adbutils.AdbError as e:  # "device not found" right after connect
            return f"unavailable: {e}"

    def devices(self) -> list[tuple[str, str]]:
        """(serial, state) for every device the adb server knows about."""
        try:
            return [(d.serial, d.state) for d in self._adb.list()]
        except _LINK_ERRORS as e:
            raise DeviceError(f"adb server unreachable: {e}") from e

    def server_version(self) -> int:
        try:
            return self._adb.server_version()
        except _LINK_ERRORS as e:
            raise DeviceError(f"adb server unreachable: {e}") from e

    def _call(self, fn: Callable[[adbutils.AdbDevice], T]) -> T:
        """Run fn(device); if the link dropped, reconnect once and retry."""
        try:
            return fn(self.device)
        except _LINK_ERRORS as e:
            log.warning("ADB command failed (%s); reconnecting", e)
            self._device = None
        try:
            return fn(self.device)
        except _LINK_ERRORS as e:
            raise DeviceError(f"ADB command failed after reconnect: {e}") from e

    # ------------------------------------------------------------------ raw commands

    def shell(self, cmd: str | list[str], timeout: float | None = None) -> str:
        return self._call(lambda d: d.shell(cmd, timeout=timeout or self.timeout))

    def exec_out(self, cmd: str, timeout: float | None = None) -> bytes:
        """Like `adb exec-out`: binary stdout without the shell PTY's newline mangling."""
        def run(d: adbutils.AdbDevice) -> bytes:
            with d.open_transport(timeout=timeout or self.timeout) as c:
                c.send_command("exec:" + cmd)
                c.check_okay()
                return c.read_until_close(encoding=None)
        return self._call(run)

    # ------------------------------------------------------------------ screen

    def screenshot(self) -> np.ndarray:
        """Current screen as a BGR uint8 array of shape (height, width, 3). No temp files."""
        if self._raw_screencap:
            # Raw is ~3.7 MB at 720x1280 but skips PNG compression on the device, which is
            # the slow part of `screencap -p`.
            try:
                return decode_raw_screencap(self.exec_out("screencap"))
            except ValueError as e:
                log.warning("Raw screencap unusable (%s); using PNG screencap from now on", e)
                self._raw_screencap = False
        try:
            return decode_png(self.exec_out("screencap -p"))
        except ValueError as e:
            raise DeviceError(f"screenshot failed: {e}") from e

    @property
    def screencap_mode(self) -> str:
        return "raw" if self._raw_screencap else "png"

    # ------------------------------------------------------------------ input

    def tap(self, x: float, y: float) -> None:
        x, y = round(x), round(y)
        self._input(f"tap ({x}, {y})", ["input", "tap", str(x), str(y)])

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300) -> None:
        x1, y1, x2, y2 = (round(v) for v in (x1, y1, x2, y2))
        self._input(f"swipe ({x1}, {y1}) -> ({x2}, {y2}) in {duration_ms}ms",
                    ["input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])

    def back(self) -> None:
        self._input("press back", ["input", "keyevent", str(KEYCODE_BACK)])

    def launch_app(self) -> None:
        # monkey resolves the launcher activity itself, so we don't depend on its name.
        out = self._input(f"launch {self.package}",
                          ["monkey", "-p", self.package, "-c", "android.intent.category.LAUNCHER", "1"])
        if "monkey aborted" in out or "No activities found" in out:
            raise DeviceError(f"could not launch {self.package}: {out.strip()}")

    def kill_app(self) -> None:
        self._input(f"force-stop {self.package}", ["am", "force-stop", self.package])

    def _input(self, desc: str, cmd: list[str]) -> str:
        if self.dry_run:
            log.info("[DRY-RUN] would %s", desc)
            return ""
        log.debug("adb: %s", desc)
        return self.shell(cmd)

    # ------------------------------------------------------------------ queries

    def is_app_installed(self) -> bool:
        return self.shell(["pm", "path", self.package]).startswith("package:")

    def is_app_running(self) -> bool:
        return bool(self.shell(["pidof", self.package]).strip())

    def foreground_package(self) -> str | None:
        """Package owning the focused window, or None (e.g. while a system dialog has focus)."""
        m = self._FOCUS_RE.search(self.shell(["dumpsys", "window"]))
        if not m:
            m = self._RESUMED_RE.search(self.shell(["dumpsys", "activity", "activities"]))
        return m.group(1) if m else None

    def list_packages(self, contains: str = "") -> list[str]:
        out = self.shell(["pm", "list", "packages"])
        pkgs = [line.removeprefix("package:").strip() for line in out.splitlines() if line.startswith("package:")]
        return sorted(p for p in pkgs if contains.lower() in p.lower())

    def getprop(self, name: str) -> str:
        return self.shell(["getprop", name]).strip()

    def screen_size(self) -> tuple[int, int]:
        """(width, height) from `wm size`, preferring an override over the physical size."""
        return _parse_wm(self.shell(["wm", "size"]), r"(\d+)x(\d+)", lambda m: (int(m[2]), int(m[3])))

    def density(self) -> int:
        return _parse_wm(self.shell(["wm", "density"]), r"(\d+)", lambda m: int(m[2]))


def _parse_wm(output: str, pattern: str, convert: Callable[[re.Match], T]) -> T:
    """Parse `wm size` / `wm density`, which print a Physical line and maybe an Override line.

    `convert` gets a match whose group 1 is Physical/Override and groups 2+ come from `pattern`.
    """
    values = {}
    for line in output.splitlines():
        m = re.match(rf"\s*(Physical|Override) \w+: {pattern}", line)
        if m:
            values[m[1]] = convert(m)
    if not values:
        raise DeviceError(f"unexpected wm output: {output!r}")
    return values.get("Override", values.get("Physical"))
