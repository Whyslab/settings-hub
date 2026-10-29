"""Binds on this machine's real config (live; read-only).

The real ~/.config/hypr/hyprland.conf is only read; `hyprctl binds -j` is the
only call to the live Hyprland, and it changes nothing. Writing is tried on a
copy of the real config in a temporary HOME with the stub hyprctl.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from binds_env import World
from conftest import before_install

from settings_hub.binds import conflicts, names, parser
from settings_hub.binds.parser import Combo, modmask

REAL = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "hypr"


def real_live() -> list:
    hyprctl = shutil.which("hyprctl")
    assert hyprctl, "hyprctl not installed"
    out = subprocess.run([hyprctl, "binds", "-j"], capture_output=True, text=True, timeout=10,
                         check=True, stdin=subprocess.DEVNULL)
    return json.loads(out.stdout)


@pytest.mark.live
def test_real_config_parses_like_hyprland_sees_it():
    cfg = parser.parse(REAL / "hyprland.conf", REAL / "settings-hub.conf")
    live = real_live()
    real = (REAL / "hyprland.conf").read_bytes()
    # 66 before install; ours replaces N and W and adds Super+I and the capture bind.
    assert len(cfg.binds) == len(live) == (66 if before_install(real) == real else 68)
    assert all(b.keyword and b.file.exists() and b.line > 0 for b in cfg.binds)
    found, extra = parser.reconcile(cfg.binds, live)
    assert all(found) and extra == []
    human = sum(names.bind_name(b, cfg).human for b in cfg.binds)
    assert human / len(cfg.binds) >= 0.9
    alt = next(e for e in conflicts.entries(cfg.binds) if e.combo == Combo.of("ALT", "Tab"))
    assert [b.dispatcher for b in alt.binds] == ["cyclenext", "bringactivetotop"]


@pytest.mark.live
def test_writing_on_a_copy_of_the_real_config(tmp_path, monkeypatch):
    real_conf = REAL / "hyprland.conf"
    before = real_conf.read_bytes()
    own = REAL / "settings-hub.conf"
    own_before = own.read_bytes() if own.exists() else None
    copy = tmp_path / "real.conf"
    copy.write_bytes(before_install(before))
    live = tmp_path / "live.json"
    live.write_text(json.dumps(real_live()))
    w = World(tmp_path / "w", monkeypatch, conf=copy, live=live)
    try:
        b = w.backend
        b.change(b.op_rebind("ALT, Tab", modmask("ALT"), "grave"))
        b.change(b.op_rebind(", XF86AudioMute", modmask("SUPER CTRL"), "M"))
        cfg = parser.parse(w.conf, w.own)
        grave = [x for x in cfg.binds if x.combo == Combo.of("ALT", "grave")]
        assert [x.dispatcher for x in grave] == ["cyclenext", "bringactivetotop"]
        mute = next(x for x in cfg.binds if x.combo == Combo.of("SUPER CTRL", "M"))
        assert mute.keyword == "bindl"
        # The template replaces N and W and adds Super+I and the capture submap's
        # bind (plan 5.3: 67 outside the submap, 1 inside); moves keep the count.
        assert len([x for x in cfg.binds if not x.submap]) == 67
        assert [x.submap for x in cfg.binds if x.submap] == ["settings-hub-capture"]
    finally:
        w.close()
    assert real_conf.read_bytes() == before
    assert (own.read_bytes() if own.exists() else None) == own_before
