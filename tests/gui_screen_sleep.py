"""Drive the real GTK page in-process (no synthetic input). Run by test_gui.py.

    python3 gui_screen_sleep.py REPO SCREEN_SLEEP_DIR STUBS HISTORY OUT.json

The caller has already isolated the environment (temporary HOME, stubs first in
PATH, a private Xvfb display and D-Bus session). Widgets are driven through
their own API -- set_value(), set_active(), emitting "clicked", the gesture's
"released" and the focus controller's "leave" -- which runs exactly the
handlers that real input would. Results go to OUT.json; the test asserts them.
Not collected by pytest (no test_ prefix): it needs the system's PyGObject.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
repo, ss_dir, stubs, history_path, out_path = (Path(a) for a in sys.argv[1:6])
sys.path.insert(0, str(repo))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from settings_hub import pages, strings  # noqa: E402
from settings_hub.backends import screen_sleep as ssb  # noqa: E402
from settings_hub.controllers import screen_sleep as ctl  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402


class Redirect:
    """idle.py runs /usr/bin/pkill and /usr/bin/pgrep: send them to the stubs."""

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def _fix(self, cmd):
        if isinstance(cmd, (list, tuple)) and cmd and str(cmd[0]).startswith("/"):
            stub = stubs / Path(cmd[0]).name
            if not stub.exists():
                raise AssertionError(f"a real program would run: {cmd}")
            return [str(stub), *cmd[1:]]
        return cmd

    def run(self, cmd, *a, **k):
        return subprocess.run(self._fix(cmd), *a, **k)

    def Popen(self, cmd, *a, **k):  # noqa: N802
        return subprocess.Popen(self._fix(cmd), *a, **k)


def spin(seconds: float) -> None:
    """Run the GTK main loop for a while (timers, worker results)."""
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.005)


def config() -> dict:
    return json.loads(Path(backend.ss.common.CONFIG_FILE).read_text())


def calls() -> list[str]:
    log = stubs.parent / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


Gtk.init()
workers = Workers()
history = History(history_path)
backend = ssb.Backend(workers, ss_dir)
for module in (backend.ss.idle, backend.ss.night):
    module.subprocess = Redirect()
backend.ss.idle.on_ac = lambda: True
ssb.register(history, backend)
statuses: list[str] = []
ctx = pages.Context(history, workers, statuses.append, lambda: None, {ssb.BACKEND: backend})
page = pages.create("screen-sleep", ctx)
win = Gtk.Window(title="test")
win.set_default_size(920, 900)
win.set_child(page.widget)
win.present()
spin(1.5)
r: dict = {}
w = page.widgets

r["missing_widgets"] = [i for i in ctl.WIDGETS if i not in w]
r["missing_rows"] = sorted(set(strings.SS_ROWS) - set(page.rows))
r["initial"] = {
    "ac_dim": w["idle.ac.dim.minutes"].get_value(),
    "ac_suspend_on": w["idle.ac.suspend.enabled"].get_active(),
    "ac_suspend_spin_sensitive": w["idle.ac.suspend.minutes"].get_sensitive(),
    "schedule_on": w["night.schedule"].get_active(),
    "slider": w["night.slider"].get_value(),
    "label": w["night.value"].get_label(),
    "target": w["night.target"].get_value(),
    "on_hour_text": w["night.on.hour"].get_text(),
    "shown_profile": page.shown_profile,
    "ac_rows_visible": [row.get_visible() for row in page.profile_rows["ac"]],
    "battery_rows_visible": [row.get_visible() for row in page.profile_rows["battery"]],
    "power_text": w["status.power"].get_label(),
    "alert_visible": page.alert_group.get_visible(),
    "night_more_expanded": w["night.more"].get_expanded(),
    "setup_visible": page.setup_group.get_visible(),
}

# The switch shows the other set; a probe with the same power keeps it there.
page.profile_buttons["battery"].set_active(True)
r["after_click"] = {
    "shown_profile": page.shown_profile,
    "battery_rows_visible": [row.get_visible() for row in page.profile_rows["battery"]],
    "ac_rows_visible": [row.get_visible() for row in page.profile_rows["ac"]],
    "power_text": w["status.power"].get_label(),
}
probes = []
real_show_probe = page.show_probe
page.show_probe = lambda pr: (probes.append(pr.power), real_show_probe(pr))
page.controller.refresh()
spin(1.0)
page.show_probe = real_show_probe
r["after_click_probes"] = probes
r["after_click_probe"] = page.shown_profile
# Unplugged: the set now in force is shown again.
probe = ssb.Probe(power="battery", hyprsunset=(True, ""), hypridle=True, daemon=(True, ""))
page.show_probe(probe)
probe.power = "ac"
page.show_probe(probe)
r["after_power_change"] = page.shown_profile
# A service down: one bad probe is not enough, two in a row show its row.
probe.hypridle = False
page.show_probe(probe)
r["alert_one_bad"] = page.alert_group.get_visible()
page.show_probe(probe)
r["alert_down"] = {
    "group": page.alert_group.get_visible(),
    "rows": {n: row.get_visible() for n, (row, _b) in page.checks.items()},
    "badge": page.checks["hypridle"][1].label.get_label(),
}
probe.hypridle = True
page.show_probe(probe)
r["alert_back"] = page.alert_group.get_visible()
# Search: the battery row switches the set, the target row unfolds the schedule.
page.reveal("battery")
r["reveal_battery"] = page.shown_profile
page._hidden()  # what unmap runs: the next showing starts on the set in force
r["after_hidden"] = page.shown_profile
page.controller.set_visible(True)  # what map runs
# The first probe of a page just built is no power change: a search result
# that opened the battery set before it stays.
page._power = page._last_power = ""
page.reveal("battery")
page.show_probe(ssb.Probe(power="ac", hyprsunset=(True, ""), hypridle=True,
                          daemon=(True, "")))
r["first_probe_after_reveal"] = page.shown_profile
# A failed power reading leaves no stale caption.
page.show_probe(ssb.Probe(power="", hyprsunset=(True, ""), hypridle=True,
                          daemon=(True, "")))
r["caption_no_power"] = w["status.power"].get_visible()
# Steps out of order in the hidden set are told in the switch's caption.
page.show_profile("ac")
page.show_order("battery", True)
r["order_other_caption"] = w["status.power"].get_label()
r["order_other_label_visible"] = page.order_labels["battery"].get_visible()
ok = dict(hyprsunset=(True, ""), hypridle=True, daemon=(True, ""))
page.show_probe(ssb.Probe(power="ac", **ok))
r["order_two_lines"] = w["status.power"].get_label()
page.show_order("battery", False)
# A failed power reading between two equal ones is no change: the pick stays.
page.profile_buttons["battery"].set_active(True)
for power in ("", "ac"):
    page.show_probe(ssb.Probe(power=power, **ok))
r["pick_after_failed_read"] = page.shown_profile
# Typing in a minutes field: a power change waits until the field is left.
page._typing = lambda: True
page.show_probe(ssb.Probe(power="battery", **ok))
page.profile_buttons["ac"].set_active(True)  # the pick made before unplugging
page.show_probe(ssb.Probe(power="ac", **ok))
page.show_probe(ssb.Probe(power="battery", **ok))
r["typing_kept"] = page.shown_profile
del page._typing
page.show_probe(ssb.Probe(power="battery", **ok))
r["after_typing"] = page.shown_profile
page.reveal("target")
spin(0.3)
r["reveal_target_expanded"] = w["night.more"].get_expanded()
page.show_profile("ac")

# A timing edit through the widget: written 1.5 s after the change, not before.
w["idle.battery.dim.minutes"].set_value(9)
spin(1.0)
r["dim_after_1s"] = config()["idle"]["battery"]["dim"]["minutes"]
spin(1.0)
r["dim_after_2s"] = config()["idle"]["battery"]["dim"]["minutes"]
r["pkill_calls"] = [c for c in calls() if c.startswith("pkill")]

# Re-read before the write: the typed value stays on screen and is then written.
w["idle.ac.lock.minutes"].set_value(33)
cfg = config()
cfg["idle"]["ac"]["lock"]["minutes"] = 44
cfg["night"]["target_temp"] = 3000
backend.ss.common.save_config(cfg)  # what the daemon might do meanwhile
page.refresh()
spin(0.3)
r["lock_shown_after_reread"] = w["idle.ac.lock.minutes"].get_value()
r["target_shown_after_reread"] = w["night.target"].get_value()
spin(1.6)
r["lock_written"] = config()["idle"]["ac"]["lock"]["minutes"]

# Focus: a focused text field is not overwritten by a re-read.
w["idle.ac.dpms.minutes"].grab_focus()
spin(0.2)
r["window_active"] = win.is_active()
r["dpms_focused"] = page.focused("idle.ac.dpms")
cfg = config()
cfg["idle"]["ac"]["dpms"]["minutes"] = 55
backend.ss.common.save_config(cfg)
page.refresh()
spin(0.3)
r["dpms_shown_while_focused"] = w["idle.ac.dpms.minutes"].get_value()
w["night.target"].grab_focus()
spin(0.1)
page.refresh()
spin(0.3)
r["dpms_shown_after_focus_left"] = w["idle.ac.dpms.minutes"].get_value()

# The slider: live temperature, "On schedule" goes off, one group after 600 ms.
groups_before = len(history.groups())
w["night.slider"].set_value(5000)
r["schedule_right_after_move"] = w["night.schedule"].get_active()
spin(0.3)
r["temp_applied"] = "hyprctl hyprsunset temperature 5000" in calls()
r["override_before_600ms"] = config()["night"]["manual_override"]
spin(0.6)
r["override_after_600ms"] = config()["night"]["manual_override"]
r["slider_group"] = sorted(e.key for e in history.groups()[-1].entries)
r["slider_groups_added"] = len(history.groups()) - groups_before


def controllers(widget, kind):
    found = []
    model = widget.observe_controllers()
    for i in range(model.get_n_items()):
        item = model.get_item(i)
        if isinstance(item, kind):
            found.append(item)
    return found


# Button released (GestureClick) ends a series at once, before 600 ms.
groups_before = len(history.groups())
w["night.slider"].set_value(3500)
for gesture in controllers(w["night.slider"], Gtk.GestureClick):
    gesture.emit("released", 1, 0.0, 0.0)
spin(0.25)
r["released_groups_added"] = len(history.groups()) - groups_before
r["released_temp"] = "hyprctl hyprsunset temperature 3500" in calls()

# Focus leaving the slider ends a series too.
groups_before = len(history.groups())
w["night.slider"].set_value(3000)
for focus in controllers(w["night.slider"], Gtk.EventControllerFocus):
    focus.emit("leave")
spin(0.25)
r["focus_out_groups_added"] = len(history.groups()) - groups_before

# "On schedule" back on: manual_override false, scheduled temperature applied.
w["night.schedule"].set_active(True)
spin(0.5)
r["override_after_schedule_on"] = config()["night"]["manual_override"]

# A preset is one group; undo brings every field back and the page shows it.
w["idle.ac.preset.movie"].emit("clicked")
spin(0.8)
r["ac_after_movie"] = [config()["idle"]["ac"][s]["enabled"] for s in ctl.STEPS]
r["ac_switches_after_movie"] = [w[f"idle.ac.{s}.enabled"].get_active() for s in ctl.STEPS]
r["movie_group_size"] = len(history.groups()[-1].entries)
history.execute(history.plan_undo_last())
spin(0.8)
r["ac_after_undo"] = [config()["idle"]["ac"][s]["enabled"] for s in ctl.STEPS]
r["ac_switches_after_undo"] = [w[f"idle.ac.{s}.enabled"].get_active() for s in ctl.STEPS]

# Stay awake through its switch (the helper process, stub systemd-inhibit).
pid_file = Path(backend.ss.common.STATE_DIR) / "caffeine.pid"
w["caffeine.switch"].set_active(True)
spin(2.0)
r["caffeine_pid_file"] = pid_file.exists()
w["caffeine.switch"].set_active(False)
spin(2.0)
r["caffeine_pid_file_after_off"] = pid_file.exists()

# Without config.json the page offers the old window and does not create it.
Path(backend.ss.common.CONFIG_FILE).unlink()
page.refresh()
spin(0.2)
r["missing_setup_visible"] = page.setup_group.get_visible()
r["missing_main_visible"] = page.idle_group.get_visible()
r["missing_config_created"] = Path(backend.ss.common.CONFIG_FILE).exists()
r["statuses"] = statuses[-5:]

workers.stop_all(2)
out_path.write_text(json.dumps(r, ensure_ascii=False, indent=1))
