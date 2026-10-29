"""Loading other projects' live modules under private names."""

import shutil
import sys

import pytest
from conftest import FIXTURES

from settings_hub import loader

SS = FIXTURES / "screen_sleep"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_loads_under_private_names_and_removes_aliases(home):
    before = {n: sys.modules.get(n) for n in ("common", "idle", "night")}
    ss = loader.load_screen_sleep(SS)
    for name in ("common", "idle", "night"):
        assert sys.modules.get(name) is before[name]  # the temporary alias is gone
        assert f"_ss_live.{name}" in sys.modules
    assert "common" not in sys.modules
    assert ss.common.__name__ == "_ss_live.common"
    assert ss.idle.atomic_write_text is ss.common.atomic_write_text  # resolved via alias
    assert ss.night.MAX_TEMP == ss.common.MAX_TEMP


def test_existing_module_named_common_is_restored(home, monkeypatch):
    sentinel = type(sys)("common")
    monkeypatch.setitem(sys.modules, "common", sentinel)
    loader.load_screen_sleep(SS)
    assert sys.modules["common"] is sentinel


def test_paths_follow_home_and_config_check_does_not_create_it(home):
    ss = loader.load_screen_sleep(SS)
    assert str(ss.common.CONFIG_FILE).startswith(str(home))
    assert not ss.config_exists()
    assert not (home / ".config").exists()  # nothing was written by loading
    ss.common.CONFIG_FILE.parent.mkdir(parents=True)
    ss.common.CONFIG_FILE.write_text("{}")
    assert ss.config_exists()


def test_signatures_the_backends_will_use(home):
    ss = loader.load_screen_sleep(SS)
    for module, names in (
        (ss.common, ("load_config", "save_config", "default_config", "atomic_write_text")),
        (ss.idle, ("apply_profile", "current_power", "caffeine_set", "caffeine_active",
                   "render", "read_current_timeouts")),
        (ss.night, ("apply_temperature", "read_temperature", "check_hyprsunset_alive",
                    "check_daemon_alive")),
    ):
        for name in names:
            assert callable(getattr(module, name)), name


def test_env_variable_selects_the_directory(home, monkeypatch, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(SS, copy)
    monkeypatch.setenv("SETTINGS_HUB_SCREEN_SLEEP_DIR", str(copy))
    ss = loader.load_screen_sleep()
    assert ss.directory == copy
    assert not ss.changed_on_disk()
    (copy / "idle.py").write_text((copy / "idle.py").read_text() + "\n")
    import os
    os.utime(copy / "idle.py", (1, 1))
    assert ss.changed_on_disk()


def test_missing_or_broken_module_is_a_load_error(home, tmp_path):
    with pytest.raises(loader.LoadError):
        loader.load_screen_sleep(tmp_path / "absent")
    broken = tmp_path / "broken"
    shutil.copytree(SS, broken)
    (broken / "night.py").write_text("raise ImportError('boom')\n")
    with pytest.raises(loader.LoadError, match="boom"):
        loader.load_screen_sleep(broken)
    assert "common" not in sys.modules and "idle" not in sys.modules


def test_loading_writes_no_bytecode_into_the_other_project(home, tmp_path):
    copy = tmp_path / "ss"
    shutil.copytree(SS, copy)
    loader.load_screen_sleep(copy)
    hub = make_hub(tmp_path / "hub2")
    loader.load_rofi_module("rofi_hub.sections.animations", hub)
    assert list(copy.rglob("__pycache__")) == []
    assert list(hub.rglob("__pycache__")) == []
    assert sys.dont_write_bytecode is False


def make_hub(root):
    pkg = root / "rofi_hub"
    (pkg / "sections").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "sections" / "__init__.py").write_text("")
    (pkg / "strings.py").write_text("LANG = 'en'\n\ndef t(key):\n    return LANG + ':' + key\n")
    (pkg / "sections" / "animations.py").write_text(
        "from ..strings import LANG, t\n\nNAME = t('sec_animations')\n")
    return root


def test_rofi_package_loads_with_relative_imports(tmp_path):
    root = make_hub(tmp_path / "hub")
    mod = loader.load_rofi_module("rofi_hub.sections.animations", root)
    assert mod.__name__ == "_rofi_live.rofi_hub.sections.animations"
    assert mod.NAME == "en:sec_animations"
    assert "rofi_hub" not in sys.modules  # never a global name


def test_rofi_missing_package(tmp_path):
    with pytest.raises(loader.LoadError):
        loader.load_rofi_module("rofi_hub.sections.animations", tmp_path)


@pytest.mark.live
def test_live_screen_sleep_modules_load(monkeypatch):
    """The real installed copy (read-only: loading writes nothing)."""
    ss = loader.load_screen_sleep()
    assert "common" not in sys.modules
    assert callable(ss.idle.apply_profile)


@pytest.mark.live
def test_live_rofi_animations_load():
    mod = loader.load_rofi_module("rofi_hub.sections.animations")
    assert hasattr(mod, "LANG")
