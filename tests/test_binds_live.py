"""Binds on this machine's real config (live; read-only).

The real ~/.config/hypr files are only read; `hyprctl binds -j` is the only call
to the live Hyprland, and it changes nothing. Writing is tried on a copy of the
real hyprland.conf in a temporary HOME with the stub hyprctl.

Which test applies is decided like the window decides it (backends/binds.py):
with a hyprland.lua (Hyprland 0.57+) hyprland.conf is no longer read, and the
Binds page shows Hyprland's own list read-only; without one it parses the conf.
Every expected count comes from Hyprland's live list, none is written here.
"""

import json
import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest
from binds_env import World
from conftest import before_install

from settings_hub.backends import binds as bb
from settings_hub.binds import conflicts, names, parser, writer
from settings_hub.binds.parser import Combo, modmask
from settings_hub.controllers import binds as cb

REAL = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "hypr"
LUA_ACTIVE = (REAL / "hyprland.lua").exists()


def read_only_hyprctl(args: list[str]) -> tuple[int, str]:
    """The real hyprctl, for `binds -j` only: anything else fails the test."""
    assert args == ["binds", "-j"], f"a live test may not run hyprctl {args}"
    hyprctl = shutil.which("hyprctl")
    assert hyprctl, "hyprctl not installed"
    out = subprocess.run([hyprctl, *args], capture_output=True, text=True, timeout=10,
                         stdin=subprocess.DEVNULL)
    return out.returncode, out.stdout


def real_live() -> list:
    rc, out = read_only_hyprctl(["binds", "-j"])
    assert rc == 0, out
    return json.loads(out)


def real_backend() -> bb.Backend:
    paths = bb.Paths(REAL / "hyprland.conf", REAL / "settings-hub.conf", REAL / "hyprland.lua")
    return bb.Backend(None, paths, hyprctl=read_only_hyprctl)  # load() needs no workers


@pytest.mark.live
@pytest.mark.skipif(LUA_ACTIVE, reason="hyprland.lua is there: Hyprland does not read "
                    "hyprland.conf (see the Lua test)")
def test_real_config_parses_like_hyprland_sees_it():
    cfg = parser.parse(REAL / "hyprland.conf", REAL / "settings-hub.conf")
    live = real_live()
    assert len(cfg.binds) == len(live)
    found, extra = parser.reconcile(cfg.binds, live)
    assert all(found) and extra == []
    # Several binds on one combination stay one entry, in Hyprland's order.
    for e in conflicts.entries(cfg.binds):
        same = [x["dispatcher"] for x in live if not x.get("submap")
                and Combo.of(x["modmask"], x["key"]) == e.combo]
        if not e.submap and len(same) > 1:
            assert [b.dispatcher for b in e.binds] == same, e.combo


@pytest.mark.live
def test_real_hyprland_conf_reads_cleanly():
    """The page as it would be on hyprland.conf (Hyprland up to 0.56, or after a
    rollback from Lua): every bind found where it is, and named for a person."""
    cfg = parser.parse(REAL / "hyprland.conf", REAL / "settings-hub.conf")
    assert cfg.binds
    assert all(b.keyword and b.file.exists() and b.line > 0 for b in cfg.binds)
    human = sum(names.bind_name(b, cfg).human for b in cfg.binds)
    assert human / len(cfg.binds) >= 0.9


@pytest.mark.live
@pytest.mark.skipif(not LUA_ACTIVE, reason="no hyprland.lua: the conf test applies")
def test_binds_page_under_lua_shows_what_hyprland_has(monkeypatch):
    """What the Binds page shows on this machine: Hyprland's live list, one row
    per bind, all read-only (hyprland.conf is not read, nothing can be written).
    One `hyprctl binds -j` only: a focused game switches binds between calls."""
    backend = real_backend()
    monkeypatch.setattr(parser, "parse", lambda *_a, **_k: pytest.fail("parsed the conf"))
    state = backend.load()
    assert state.lua == REAL / "hyprland.lua" and state.cfg is None and not state.error
    assert state.live, "Hyprland's live list is empty or unreadable"
    assert state.extra == state.live
    rows = cb.Controller(backend, None, None).build(state)
    assert len(rows) == len(state.live)
    assert all(r.live_ok and not r.editable and not r.movable for r in rows)
    assert [r.group == "submap" for r in rows] == [bool(x.get("submap")) for x in state.live]
    assert all(r.name and r.combo for r in rows)
    # Named for a person like on hyprland.conf: what each runs is read from
    # hyprland.lua (binds/luaread.py), Hyprland's list says only "exec_cmd".
    unnamed = [f"{r.combo}: {r.name}" for r in rows if not r.human]
    assert len(unnamed) <= 0.1 * len(rows), unnamed
    with pytest.raises(writer.LuaActive):  # refused before anything is read or written
        backend.change(lambda *_: pytest.fail("planned under a Lua config"))
    with pytest.raises(writer.LuaActive):
        backend.apply_lines({"SUPER, I": []})


@pytest.mark.live
def test_writing_on_a_copy_of_the_real_config(tmp_path, monkeypatch):
    """The .conf writer (Hyprland up to 0.56, and after a rollback) on a copy of
    the real hyprland.conf as it was before install.sh."""
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
        # The installed state, checked against the conf alone and the template's
        # own binds: each of those replaces whatever the conf had on its combo.
        base = parser.parse(copy)
        template = parser.parse(w.conf, w.own, overrides={w.own: writer.read_own(w.own)[0]})
        ours = [x for x in template.binds if x.file == w.own and not x.submap]
        assert ours
        mine = {x.combo for x in ours}
        expect = Counter(x.combo for x in base.binds if not x.submap and x.combo not in mine)
        expect.update(x.combo for x in ours)
        assert Counter(x.combo for x in template.binds if not x.submap) == expect
        outside = sum(expect.values())
        b.change(b.op_rebind("ALT, Tab", modmask("ALT"), "grave"))
        b.change(b.op_rebind(", XF86AudioMute", modmask("SUPER CTRL"), "M"))
        cfg = parser.parse(w.conf, w.own)
        grave = [x for x in cfg.binds if x.combo == Combo.of("ALT", "grave")]
        tab = [x for x in base.binds if x.combo == Combo.of("ALT", "Tab")]
        assert [x.dispatcher for x in grave] == [x.dispatcher for x in tab]
        mute = next(x for x in cfg.binds if x.combo == Combo.of("SUPER CTRL", "M"))
        assert mute.keyword == "bindl"
        # Moves keep the count; the capture submap's bind is the only one inside.
        assert len(tab) > 1  # several binds on one combination move together
        assert len([x for x in cfg.binds if not x.submap]) == outside
        assert [x.submap for x in cfg.binds if x.submap] == ["settings-hub-capture"]
    finally:
        w.close()
    assert real_conf.read_bytes() == before
    assert (own.read_bytes() if own.exists() else None) == own_before
