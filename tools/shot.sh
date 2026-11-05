#!/bin/sh
# tools/shot.sh - screenshot the window in an isolated session, never on your screen.
#
#   tools/shot.sh [--scheme light|dark] [--page ID] [--hostile] [--cold]
#                 [--history FILE] [--settle S] [--no-ss-config] [--row ROW] OUT.png
#
# Isolation (plan section 4): a private Xvfb display numbered :99 or higher
# (a bare Xvfb would take :1 and break the desktop), a temporary HOME and XDG
# dirs, no WAYLAND_DISPLAY / HYPRLAND_INSTANCE_SIGNATURE, stub hyprctl and
# friends first in PATH (each logs its arguments to $tmp/calls.log), and a
# private D-Bus session.
#
#   --hostile  a gtk.css where every @define-color is #ff00ff (plus a few rules
#              painting everything #ff00ff) and gtk-theme-name=Monochrome-Vivid
#   --cold     do not pre-start the app; settings-open has to start it
#   --settle   seconds to wait after opening before the screenshot (default 2)
#   --no-ss-config  no screen-sleep config.json (the page offers the old window)
#   --row      then scroll the page to this row (the window's "page#row" open)
#
# Wallpaper: the pictures of tests/fixtures/wallpapers in $HOME/.config/hypr/wallpapers,
# a stub wallpaper.sh that only logs, thumbnails made by magick into $HOME/.cache
# (never the real cache), a stub wallpaper-theme that says "vivid".
# Animations: a copy of tests/fixtures/rofi (rofi-launcher's module and data) with a
# stub bin/anim-preview.sh; its preview pictures are drawn into $HOME/.cache.
# Binds: tests/fixtures/hypr/hyprland.conf in $HOME/.config/hypr; the stub hyprctl
# answers `binds -j` with tests/fixtures/hypr/binds.json and `submap` with default.
#
# screen-sleep's modules come from tests/fixtures (anonymised copies), with
# their absolute /usr/bin/pkill and /usr/bin/pgrep pointed at the stubs; the
# stub hyprctl answers "hyprsunset temperature" with 4300 and the stub
# systemctl says the daemon is active.
#
# The screen is exactly the window size, so the root window is the window.
# Prints the temporary directory (calls.log, open.log, app.log) on exit.

set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
scheme=""
page="history"
hostile=0
cold=0
history_file=""
settle=2
ss_config=1
row=""
while [ $# -gt 1 ]; do
    case $1 in
        --scheme) scheme=$2; shift 2 ;;
        --page) page=$2; shift 2 ;;
        --hostile) hostile=1; shift ;;
        --cold) cold=1; shift ;;
        --history) history_file=$2; shift 2 ;;
        --settle) settle=$2; shift 2 ;;
        --no-ss-config) ss_config=0; shift ;;
        --row) row=$2; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
[ $# -eq 1 ] || { sed -n '2,8p' "$0"; exit 2; }
out=$1
case $out in /*) ;; *) out=$PWD/$out ;; esac

tmp=$(mktemp -d)
stubs=$tmp/stubs
mkdir -p "$stubs" "$tmp/.config" "$tmp/.local/state" "$tmp/.local/share" "$tmp/.cache" "$tmp/run"
chmod 700 "$tmp/run"
for name in hyprctl notify-send pkill pgrep systemctl systemd-inhibit wallpaper.sh \
    wallpaper-theme pactl nmcli bluetoothctl tailscale powerprofilesctl brightnessctl \
    pacman; do
    printf '#!/bin/sh\necho "%s $*" >>"%s/calls.log"\n' "$name" "$tmp" >"$stubs/$name"
    chmod +x "$stubs/$name"
done
# The live values of the variable pages come from the registry's defaults.
python3 -B -c 'import json, sys; sys.path.insert(0, sys.argv[1]); \
from settings_hub import variables; \
print(json.dumps({v.option: v.default for v in variables.VARS}))' "$ROOT" >"$tmp/vars.json"
cat >"$stubs/hyprctl" <<'PY'
import json, sys
from pathlib import Path
tmp = Path(__file__).resolve().parent.parent
args = sys.argv[1:]
with (tmp / "calls.log").open("a") as fh:
    fh.write("hyprctl " + " ".join(args) + "\n")
if args[:1] == ["getoption"]:
    option = args[1]
    values = json.loads((tmp / "vars.json").read_text())
    value = values.get(option, 0)
    kind = ("bool" if isinstance(value, bool) else
            "float" if isinstance(value, float) else
            "int" if isinstance(value, int) else "str")
    print(json.dumps({"option": option, kind: value, "set": True}))
elif args[:2] == ["binds", "-j"]:
    print((tmp / "binds.json").read_text())
elif args[:1] == ["submap"]:
    print("default")
elif args[:2] == ["hyprsunset", "temperature"]:
    print("4300")
PY
chmod +x "$stubs/hyprctl"
cat >>"$stubs/systemctl" <<'STUB'
case " $* " in *" is-active "*) echo active ;; esac
exit 0
STUB
cat >>"$stubs/pactl" <<'STUB'
case "$*" in
  *"json list sinks"*) echo '[{"name":"speakers","description":"Колонки","mute":false,"volume":{"l":{"value_percent":"45%"}}},{"name":"headset","description":"Наушники G435","mute":false,"volume":{"l":{"value_percent":"80%"}}}]' ;;
  *"json list sources"*) echo '[{"name":"mic","description":"Микрофон","mute":true,"volume":{"l":{"value_percent":"60%"}}}]' ;;
  "get-default-sink") echo speakers ;;
  "get-default-source") echo mic ;;
esac
exit 0
STUB
cat >>"$stubs/nmcli" <<'STUB'
case "$*" in
  "radio wifi") echo enabled ;;
  *"device wifi list"*) printf '*:Домашняя:72:WPA2\n :Сосед:38:WPA2\n' ;;
  *"connection show"*) printf 'Домашняя:802-11-wireless:yes\nГость:802-11-wireless:no\n' ;;
esac
exit 0
STUB
cat >>"$stubs/bluetoothctl" <<'STUB'
case "$*" in
  "show") printf 'Controller AA:BB\n\tPowered: yes\n' ;;
esac
exit 0
STUB
cat >>"$stubs/tailscale" <<'STUB'
case "$*" in
  "status --json") echo '{"BackendState":"Running","TailscaleIPs":["100.64.0.1"]}' ;;
esac
exit 0
STUB
cat >>"$stubs/powerprofilesctl" <<'STUB'
case "$1" in
  get) echo balanced ;;
  list) printf '* performance:\n  balanced:\n  power-saver:\n' ;;
esac
exit 0
STUB
cat >>"$stubs/brightnessctl" <<'STUB'
case "$1" in
  get) echo 12000 ;;
  max) echo 24000 ;;
esac
exit 0
STUB
cat >>"$stubs/pacman" <<'STUB'
exit 1
STUB

ss_dir=$tmp/.local/share/screen-sleep
mkdir -p "$ss_dir"
for m in common idle night; do
    sed -e "s#/usr/bin/pkill#$stubs/pkill#g" -e "s#/usr/bin/pgrep#$stubs/pgrep#g" \
        "$ROOT/tests/fixtures/screen_sleep/$m.py" >"$ss_dir/$m.py"
done
if grep -q '/usr/bin/p' "$ss_dir"/*.py; then
    echo "screen-sleep copies still call /usr/bin programs" >&2
    exit 1
fi
if [ "$ss_config" -eq 1 ]; then
    mkdir -p "$tmp/.config/screen-sleep"
    cp "$ROOT/tests/fixtures/screen_sleep/config.json" "$tmp/.config/screen-sleep/config.json"
fi

# Wallpaper and theme.
wp=$tmp/.config/hypr/wallpapers
mkdir -p "$wp" "$tmp/.config/hypr/scripts" "$tmp/.local/state/hypr-wallpaper"
cp "$ROOT"/tests/fixtures/wallpapers/* "$wp/"
printf '#!/bin/sh\necho "wallpaper.sh $*" >>"%s/calls.log"\n' "$tmp" \
    >"$tmp/.config/hypr/scripts/wallpaper.sh"
chmod +x "$tmp/.config/hypr/scripts/wallpaper.sh"
for t in desktop sddm; do echo "$wp/blue-dusk.jpg" >"$tmp/.local/state/hypr-wallpaper/$t.path"; done
echo "$wp/forest.png" >"$tmp/.local/state/hypr-wallpaper/lock.path"
printf 'desktop=off\nlock=on\nsddm=off\n' >"$tmp/.local/state/hypr-wallpaper/random.conf"
sed 's/MODE/vivid/' "$ROOT/tests/fixtures/wallpaper_theme_status.txt" >"$tmp/theme-status"
cat >>"$stubs/wallpaper-theme" <<STUB
[ "\$1" = status ] && cat "$tmp/theme-status"
exit 0
STUB

# Animations.
mkdir -p "$tmp/rofi/bin" "$tmp/.config/rofi-launcher"
cp -r "$ROOT/tests/fixtures/rofi/rofi_hub" "$ROOT/tests/fixtures/rofi/data" "$tmp/rofi/"
printf '#!/bin/sh\necho "anim-preview.sh $* REOPEN=$ANIM_PREVIEW_REOPEN" >>"%s/calls.log"\n' \
    "$tmp" >"$tmp/rofi/bin/anim-preview.sh"
chmod +x "$tmp/rofi/bin/anim-preview.sh"
cp "$ROOT"/tests/fixtures/animations/* "$tmp/.config/rofi-launcher/"
if python3 -c 'import PIL' 2>/dev/null; then
    python3 -B "$ROOT/tests/fixtures/rofi/tools/render_preview.py" \
        --out "$tmp/.cache/rofi-launcher/anim-previews" >/dev/null
fi

# Binds: an anonymised copy of hyprland.conf (nothing is ever written to it), and
# Hyprland's live list as the stub's answer to `hyprctl binds -j`.
mkdir -p "$tmp/.config/hypr"
cp "$ROOT/tests/fixtures/hypr/hyprland.conf" "$tmp/.config/hypr/hyprland.conf"
cp "$ROOT/tests/fixtures/hypr/binds.json" "$tmp/binds.json"

if [ "$hostile" -eq 1 ]; then
    mkdir -p "$tmp/.config/gtk-4.0"
    printf '[Settings]\ngtk-theme-name=Monochrome-Vivid\n' >"$tmp/.config/gtk-4.0/settings.ini"
    for c in window_bg_color view_bg_color headerbar_bg_color sidebar_bg_color card_bg_color \
        dialog_bg_color popover_bg_color thumbnail_bg_color shade_color \
        scrollbar_outline_color window_fg_color view_fg_color headerbar_fg_color \
        sidebar_fg_color card_fg_color dialog_fg_color popover_fg_color accent_bg_color \
        accent_fg_color accent_color destructive_bg_color destructive_fg_color \
        success_bg_color warning_bg_color error_bg_color theme_bg_color theme_fg_color \
        theme_base_color theme_text_color theme_selected_bg_color theme_selected_fg_color \
        theme_view_bg_color borders unfocused_borders tooltip_bg_color tooltip_fg_color \
        content_view_bg; do
        printf '@define-color %s #ff00ff;\n' "$c"
    done >"$tmp/.config/gtk-4.0/gtk.css"
    cat >>"$tmp/.config/gtk-4.0/gtk.css" <<'CSS'
* { color: #ff00ff; background-color: #ff00ff; border-color: #ff00ff; outline-color: #ff00ff; }
window, label, entry, row, button, list { color: #ff00ff; background-color: #ff00ff; }
CSS
    theme_src=${XDG_DATA_HOME:-$HOME/.local/share}/themes/Monochrome-Vivid
    if [ -d "$theme_src" ]; then
        mkdir -p "$tmp/.local/share/themes"
        cp -r "$theme_src" "$tmp/.local/share/themes/"
    fi
fi

if [ -n "$history_file" ]; then
    mkdir -p "$tmp/.local/state/settings-hub"
    cp "$history_file" "$tmp/.local/state/settings-hub/history.jsonl"
fi

# A bus without service activation: nothing (portals, a11y, gvfs) gets
# started inside the private session.
cat >"$tmp/bus.conf" <<BUS
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:tmpdir=/tmp</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
BUS

display=99
while [ -e "/tmp/.X$display-lock" ] || [ -e "/tmp/.X11-unix/X$display" ]; do
    display=$((display + 1))
done
Xvfb ":$display" -screen 0 920x640x24 -nolisten tcp >"$tmp/xvfb.log" 2>&1 &
xvfb_pid=$!
trap 'kill "$xvfb_pid" 2>/dev/null; wait "$xvfb_pid" 2>/dev/null; echo "$tmp"' EXIT
i=0
while [ ! -e "/tmp/.X11-unix/X$display" ] && [ "$i" -lt 50 ]; do
    sleep 0.1
    i=$((i + 1))
done
kill -0 "$xvfb_pid" 2>/dev/null || { echo "Xvfb :$display did not start" >&2; exit 1; }

# Xvfb has no DRI3; GTK's default renderer then sometimes presents a black
# first frame. The GL renderer is reliable there. (Only for this tool.)
renderer=${GSK_RENDERER:-gl}

scheme_arg=""
[ -n "$scheme" ] && scheme_arg="--color-scheme=$scheme"

env -u WAYLAND_DISPLAY -u HYPRLAND_INSTANCE_SIGNATURE \
    HOME="$tmp" XDG_CONFIG_HOME="$tmp/.config" XDG_STATE_HOME="$tmp/.local/state" \
    XDG_DATA_HOME="$tmp/.local/share" XDG_CACHE_HOME="$tmp/.cache" XDG_RUNTIME_DIR="$tmp/run" \
    PATH="$stubs:$PATH" DISPLAY=":$display" GDK_BACKEND=x11 GSK_RENDERER="$renderer" NO_AT_BRIDGE=1 GTK_A11Y=none \
    SETTINGS_HUB_APP="$ROOT/app.py" SETTINGS_HUB_ROFI_DIR="$tmp/rofi" PYTHONDONTWRITEBYTECODE=1 \
    COLD="$cold" SCHEME_ARG="$scheme_arg" PAGE="$page" OUT="$out" SETTLE="$settle" \
    OPEN="$ROOT/bin/settings-open" ROW="$row" \
    dbus-run-session --config-file="$tmp/bus.conf" -- sh -c '
        if [ "$COLD" -eq 0 ]; then
            # shellcheck disable=SC2086
            python3 "$SETTINGS_HUB_APP" --daemon $SCHEME_ARG >>"$HOME/daemon.out" 2>&1 &
            i=0
            until gdbus call --session --dest org.freedesktop.DBus \
                --object-path /org/freedesktop/DBus \
                --method org.freedesktop.DBus.NameHasOwner io.github.whyslab.SettingsHub \
                2>/dev/null | grep -q true; do
                i=$((i + 1)); [ "$i" -lt 100 ] || { echo "app did not start" >&2; exit 1; }
                sleep 0.1
            done
        fi
        "$OPEN" "$PAGE" || echo "settings-open exited $?" >&2
        if [ -n "$ROW" ]; then
            sleep 0.5
            gdbus call --session --dest io.github.whyslab.SettingsHub \
                --object-path /io/github/whyslab/SettingsHub \
                --method org.gtk.Actions.Activate open "[<\"$PAGE#$ROW\">]" "{}" >/dev/null
        fi
        sleep "$SETTLE"
        # The window logs its map event; no map, no window to photograph.
        grep -q "^map " "$XDG_STATE_HOME/settings-hub/open.log" ||
            { echo "the window was never mapped" >&2; exit 1; }
        # Software GL on Xvfb can take seconds for the first frame; an all-black
        # shot would make every pixel check pass vacuously, so wait it out.
        n=0
        while :; do
            magick import -window root "$OUT"
            [ "$(magick "$OUT" -format "%[fx:maxima.r+maxima.g+maxima.b>0]" info:)" = 1 ] && break
            n=$((n + 1)); [ "$n" -lt 20 ] || { echo "the window stayed black" >&2; exit 1; }
            sleep 0.5
        done
        gdbus call --session --dest io.github.whyslab.SettingsHub \
            --object-path /io/github/whyslab/SettingsHub \
            --method org.gtk.Actions.Activate quit "[]" "{}" >/dev/null 2>&1 || true
        sleep 0.3
    '
