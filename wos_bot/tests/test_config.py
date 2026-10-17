import pytest

from config import DEFAULT_CONFIG_PATH, ConfigError, load_config


def test_shipped_config_loads():
    cfg = load_config(DEFAULT_CONFIG_PATH)
    assert cfg.game.package == "com.gof.global"
    assert (cfg.game.width, cfg.game.height) == (720, 1280)
    assert isinstance(cfg.adb.timeout, float)


def test_missing_sections_use_defaults(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("adb:\n  serial: emulator-5554\n")
    cfg = load_config(path)
    assert cfg.adb.serial == "emulator-5554"
    assert cfg.game.width == 720


@pytest.mark.parametrize("text", [
    "adb:\n  serail: x\n",          # typo
    "game:\n  width: '720'\n",      # wrong type
    "game:\n  width: true\n",       # bool is not an int here
    "adb: 5\n",                     # section must be a mapping
])
def test_bad_config_rejected(tmp_path, text):
    path = tmp_path / "c.yaml"
    path.write_text(text)
    with pytest.raises(ConfigError):
        load_config(path)
