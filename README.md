# settings-hub

A macOS-style **Settings** window for a Hyprland desktop, written in Python with
GTK4 and its own stylesheet (no libadwaita look). It stays resident in the
background, so a hotkey shows it in well under half a second, and it brings the
desktop's scattered settings windows together in one place.

The interface is in Russian; all user-facing text lives in
[`settings_hub/strings.py`](settings_hub/strings.py).

| Light | Dark |
|---|---|
| ![light](docs/screenshots/step2-screen-sleep-light.png) | ![dark](docs/screenshots/step2-screen-sleep-dark.png) |
| ![light](docs/screenshots/step2-night-light.png) | ![dark](docs/screenshots/step2-night-dark.png) |
| ![light](docs/screenshots/step3-wallpaper-light.png) | ![dark](docs/screenshots/step3-wallpaper-dark.png) |
| ![light](docs/screenshots/step3-animations-light.png) | ![dark](docs/screenshots/step3-animations-dark.png) |

## Status

Version 1 is being built step by step. Done so far: the **framework** and the
pages **Screen and sleep**, **Wallpaper and theme** and **Animations**. The
framework:

- the resident application, the window (sidebar with search and coloured
  icons, rounded groups of rows), light and dark looks, keyboard control;
- search over pages (case-insensitive, `yo`/`ye`, wrong keyboard layout);
- the change history with undo (one user action = one group of items);
- loading of other projects' live modules under private names, and one
  apply-queue thread per backend;
- `settings-open`, the hotkey entry point, with every fallback;
- a sandbox installer and uninstaller.

*Binds* is still a placeholder.

## Screen and sleep

The page replaces screen-sleep's old GTK3 window (`gui.py`, still installed as
the fallback) and drives the same live modules (`common`, `idle`, `night` in
`~/.local/share/screen-sleep`), loaded by file path under private names.

- Changes apply at once, like macOS. Idle timings and night settings are
  written 1.5 s after the last change: a fresh `load_config()`, the changed
  fields set, `save_config()`; if a field of the set for the current power
  source changed, `idle.apply_profile()` follows (the power source is checked
  again right before). All writes and hypridle restarts run on one worker
  thread, so they never overlap; queued restarts collapse into one.
- The *now* slider applies the temperature 120 ms after a change. A series of
  moves ends when the value has been still for 600 ms, the button is released
  or the slider loses focus; then manual mode is saved and the series becomes
  one History entry. Moving the slider turns *On schedule* off; turning it on
  clears manual mode and sets the scheduled temperature right away.
- The page re-reads everything when shown and every 5 s while visible (the
  daemon changes `manual_override` on its own), but never overwrites a field
  with a queued write, a focused field, or one changed in the last 10 s.
- *Stay awake* runs in a short helper process (`python3 -I
  settings_hub/helpers/caffeine.py on|off`), so `systemd-inhibit` never
  becomes a child of the resident window.
- Without `~/.config/screen-sleep/config.json` the page does not create it
  (screen-sleep's own first-run migration needs its original import layout);
  it offers a button that opens the old window once.
- Every change is a History item; undo and "return to a moment" restart
  hypridle at most once.

What the old window could do, and where it is on the new page (widget ids
from `settings_hub/controllers/screen_sleep.py`; `tests/test_screen_sleep.py`
checks this table against them, and the GUI test checks the page builds each):

| Point | Ability of the old window | Widgets of the new page |
|---|---|---|
| 1 | Two sets of idle timings, AC and battery, four steps each: on/off and minutes 1-600 | `idle.ac.dim.enabled` `idle.ac.dim.minutes` `idle.ac.lock.enabled` `idle.ac.lock.minutes` `idle.ac.dpms.enabled` `idle.ac.dpms.minutes` `idle.ac.suspend.enabled` `idle.ac.suspend.minutes` `idle.battery.dim.enabled` `idle.battery.dim.minutes` `idle.battery.lock.enabled` `idle.battery.lock.minutes` `idle.battery.dpms.enabled` `idle.battery.dpms.minutes` `idle.battery.suspend.enabled` `idle.battery.suspend.minutes` |
| 2 | Presets Normal / Movie / Saver | `idle.ac.preset.normal` `idle.ac.preset.movie` `idle.ac.preset.eco` `idle.battery.preset.normal` `idle.battery.preset.movie` `idle.battery.preset.eco` |
| 3 | Stay awake | `caffeine.switch` |
| 4 | Night filter: *now* slider 2000-6500 K with marks, *target at night* (2000-6500, step 100), warm-up start and off times, *turn off now*, Save returns to the schedule | `night.slider` `night.value` `night.target` `night.on.hour` `night.on.minute` `night.off.hour` `night.off.minute` `night.off-now` `night.schedule` |
| 5 | Moving the slider switches to manual mode | `night.slider` `night.schedule` |
| 6 | hyprsunset / hypridle / daemon checks; warning when steps are not in ascending order | `status.hyprsunset` `status.hypridle` `status.daemon` `status.power` `idle.ac.order-warning` `idle.battery.order-warning` |

## Wallpaper and theme

Only the existing command-line tools are called (on worker threads):
`~/.config/hypr/scripts/wallpaper.sh set <desktop|lock|sddm|all> FILE`,
`wallpaper.sh random <target> on|off`, `wallpaper.sh pick` (the old rofi grid),
`wallpaper-theme mode off|vivid|tinted` and `wallpaper-theme status`. What is on
each target is read from `~/.local/state/hypr-wallpaper/<target>.path` and
`random.conf`.

- A target switch (desktop / lock screen / login screen / all three), then a
  grid of the library `~/.config/hypr/wallpapers/`; a click applies at once.
- Thumbnails share the rofi picker's cache `~/.cache/wallpaper-thumbs` (same
  key, `sha1(path|mtime)[:16]`, 480 px); missing ones are made by `magick` on a
  worker, and decoded off the GTK thread.
- Random wallpapers per target; the wallpaper-driven theme off / vivid / tinted.
- History: `wallpaper.<target>` (a path), `random.<target>`, `theme.mode`.
  Choosing a picture also logs random mode it switched off, in the same group.
  Undo restores the picture first, then random mode. Restoring "random on"
  makes the script show a new random picture: that is what random mode does.

## Animations

The page drives rofi-launcher's own animations module (the installed
`rofi_hub/sections/animations.py`, loaded by file path under a private name),
with its language forced to Russian and its `notify-send` replaced by the
window's status line.

- Presets as picture tiles (pictures from `~/.cache/rofi-launcher/anim-previews`;
  a lettered tile when a picture is missing). A preset applies everything at
  once and resets the categories, as in the rofi grid.
- Four categories (window open, window close, workspaces, menus and
  notifications): a variant and a speed each.
- Applying is the module's own path: `save_tuning`, the active preset,
  `hyprconf.write(compose(preset, tuning))`, `hyprctl reload`, on one worker.
  The tests check the written `animations.conf` against `compose` run in a
  separate process.
- *Look* hides the window, runs `bin/anim-preview.sh` with
  `ANIM_PREVIEW_REOPEN=0` (the preview undoes itself and does not reopen the
  rofi grid) and shows the window again.
- History: `preset`, `override.<category>`, `speed.<category>`; a preset is one
  group with every category it reset.

## How it works

- `app.py --daemon` starts a `Gtk.Application` (`io.github.whyslab.SettingsHub`)
  that registers on the session bus and waits, hidden. The window class is the
  program name, `settings-hub`.
- `bin/settings-open [PAGE]` asks the running copy to open a page through
  `gdbus` (a small C program, much faster than starting Python). If nothing is
  running it starts the background copy under a lock (a second quick press
  waits instead of starting another one), and if that fails within 3 s it kills
  exactly the process it started and opens the old window for that page.
- The window keeps no state: every page re-reads its sources when shown.
- Esc is swallowed on press and hides the window on release, so the held key
  never leaks into the window underneath.
- Keys: Ctrl+F search, Up/Down move, Enter opens, Tab jumps between the sidebar
  and the page, Esc hides, Ctrl+Z undoes the last change.
- The look does not depend on the system GTK theme: the process uses GTK's
  built-in theme, and `style/base.css` (loaded above the user's `gtk.css`) uses
  only literal colours and its own `--sh-*` variables.

## Layout

```
app.py                  launcher (works from the repo and from the install)
settings_hub/           app, window, theme, registry, strings, search,
                        history, loader, workers, widgets/, pages/, backends/,
                        controllers/ (page logic without GTK), helpers/
style/                  base.css, icons/*.svg
bin/settings-open       hotkey entry point (POSIX sh)
install.sh, uninstall.sh
tools/shot.sh           screenshot in an isolated session (Xvfb :99+)
tests/                  pytest; fixtures/ holds anonymised copies
```

## Tests

```
ruff check .
pytest tests/ -q              # what CI runs; `live` tests are deselected
pytest tests/ -q -m live      # also this machine's installed modules, and
                              # the GTK page on a private Xvfb (:99 or higher)
```

Wallpaper and animation tests run in a temporary `HOME` with a stub
`wallpaper.sh`, stub `wallpaper-theme`, `magick`, `hyprctl` and
`anim-preview.sh`, and a copy of rofi-launcher's module
(`tests/fixtures/rofi`); the backends' `subprocess` refuses any program that
is not a stub or inside the temporary directory.

Tests that touch screen-sleep run on copies of its modules in a temporary
`HOME`, with stub `hyprctl`, `pkill`, `pgrep`, `systemctl` and
`systemd-inhibit` first in `PATH`. `idle.py` calls `/usr/bin/pkill` by absolute
path, so the copies' `subprocess` is wrapped to send absolute programs to the
stubs as well; a test fails if a real program would run.

Shell scripts: `sh -n` and `shellcheck -S warning`.

Screenshots never use your screen: `tools/shot.sh` starts a private Xvfb on
`:99` or higher, a temporary `HOME`, a private D-Bus session without service
activation, and stub `hyprctl` and friends:

```
tools/shot.sh --scheme dark --page history out.png
tools/shot.sh --hostile --page history out.png   # every gtk.css colour is #ff00ff
tools/shot.sh --page screen-sleep --row night out.png   # scrolled to a row
```

## Install

This revision installs into a sandbox only:

```
./install.sh --prefix /tmp/sandbox
./uninstall.sh --prefix /tmp/sandbox --purge
```

Everything the installer creates is listed in an install manifest; the
uninstaller removes exactly that, and removes its one line from
`hyprland.conf` only when that exact line occurs exactly once.

## License

MIT
