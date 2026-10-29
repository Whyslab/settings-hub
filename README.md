# settings-hub

A macOS-style **Settings** window for a Hyprland desktop, written in Python with
GTK4 and its own stylesheet (no libadwaita look). It stays resident in the
background, so a hotkey shows it in well under half a second, and it brings the
desktop's scattered settings windows together in one place.

The interface is in Russian; all user-facing text lives in
[`settings_hub/strings.py`](settings_hub/strings.py).

| Light | Dark |
|---|---|
| ![light](docs/screenshots/step1-history-light.png) | ![dark](docs/screenshots/step1-history-dark.png) |

## Status

Version 1 is being built step by step. This revision is the **framework**:

- the resident application, the window (sidebar with search and coloured
  icons, rounded groups of rows), light and dark looks, keyboard control;
- search over pages (case-insensitive, `yo`/`ye`, wrong keyboard layout);
- the change history with undo (one user action = one group of items);
- loading of other projects' live modules under private names, and one
  apply-queue thread per backend;
- `settings-open`, the hotkey entry point, with every fallback;
- a sandbox installer and uninstaller.

The pages *Screen and sleep*, *Wallpaper and theme*, *Animations* and *Binds*
are placeholders here; *History* works.

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
                        history, loader, workers, widgets/, pages/, backends/
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
pytest tests/ -q -m live      # also read this machine's installed modules
```

Shell scripts: `sh -n` and `shellcheck -S warning`.

Screenshots never use your screen: `tools/shot.sh` starts a private Xvfb on
`:99` or higher, a temporary `HOME`, a private D-Bus session without service
activation, and stub `hyprctl` and friends:

```
tools/shot.sh --scheme dark --page history out.png
tools/shot.sh --hostile --page history out.png   # every gtk.css colour is #ff00ff
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
