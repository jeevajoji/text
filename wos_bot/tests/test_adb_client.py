import struct

import adbutils
import cv2
import numpy as np
import pytest

from adb_client import AdbClient, DeviceError, _parse_wm, decode_png, decode_raw_screencap


def raw_screencap(rgba: np.ndarray, fmt: int = 1, colorspace: bool = True) -> bytes:
    h, w = rgba.shape[:2]
    header = struct.pack("<3I", w, h, fmt) + (struct.pack("<I", 1) if colorspace else b"")
    return header + rgba.tobytes()


@pytest.fixture
def rgba() -> np.ndarray:
    img = np.zeros((4, 3, 4), dtype=np.uint8)
    img[..., 0] = 10   # R
    img[..., 1] = 20   # G
    img[..., 2] = 30   # B
    img[..., 3] = 255
    return img


@pytest.mark.parametrize("colorspace", [True, False])  # Android 9+ adds a 4-byte field
def test_raw_rgba_decodes_to_bgr(rgba, colorspace):
    out = decode_raw_screencap(raw_screencap(rgba, colorspace=colorspace))
    assert out.shape == (4, 3, 3)
    assert out[0, 0].tolist() == [30, 20, 10]


def test_raw_bgra_format(rgba):
    out = decode_raw_screencap(raw_screencap(rgba, fmt=5))
    assert out[0, 0].tolist() == [10, 20, 30]


@pytest.mark.parametrize("data", [b"short", raw_screencap(np.zeros((4, 3, 4), np.uint8), fmt=4)])
def test_raw_rejects_bad_input(data):
    with pytest.raises(ValueError):
        decode_raw_screencap(data)


def test_raw_rejects_truncated(rgba):
    with pytest.raises(ValueError):
        decode_raw_screencap(raw_screencap(rgba)[:-5])


def test_png_roundtrip():
    img = np.random.default_rng(0).integers(0, 255, (5, 7, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert np.array_equal(decode_png(buf.tobytes()), img)


def test_parse_wm_prefers_override():
    out = "Physical size: 720x1280\nOverride size: 1080x1920"
    assert _parse_wm(out, r"(\d+)x(\d+)", lambda m: (int(m[2]), int(m[3]))) == (1080, 1920)
    assert _parse_wm("Physical density: 240", r"(\d+)", lambda m: int(m[2])) == 240


class FakeDevice:
    def __init__(self, fail_times: int = 0):
        self.commands: list = []
        self.fail_times = fail_times

    def shell(self, cmd, timeout=None):
        if self.fail_times:
            self.fail_times -= 1
            raise adbutils.AdbError("connection dropped")
        self.commands.append(cmd)
        return "Events injected: 1"


def make_client(device: FakeDevice, dry_run: bool = False) -> AdbClient:
    client = AdbClient("127.0.0.1:5555", "com.gof.global", dry_run=dry_run)
    client._device = device
    client.connect = lambda: setattr(client, "_device", device)
    return client


def test_dry_run_sends_nothing():
    dev = FakeDevice()
    client = make_client(dev, dry_run=True)
    client.tap(100, 200)
    client.swipe(0, 0, 10, 10)
    client.back()
    client.launch_app()
    client.kill_app()
    assert dev.commands == []


def test_input_commands():
    dev = FakeDevice()
    client = make_client(dev)
    client.tap(100.4, 199.6)
    client.back()
    assert dev.commands == [["input", "tap", "100", "200"], ["input", "keyevent", "4"]]


def test_reconnects_once_then_gives_up():
    dev = FakeDevice(fail_times=1)
    make_client(dev).tap(1, 2)
    assert dev.commands == [["input", "tap", "1", "2"]]

    with pytest.raises(DeviceError):
        make_client(FakeDevice(fail_times=2)).tap(1, 2)
