#!/bin/sh
# install.sh - install settings-hub for the current user.
#
#   ./install.sh                 install and hook into the running Hyprland session
#   ./install.sh --dry-run       print every action, change nothing
#   ./install.sh --prefix DIR    install into a sandbox: every path is DIR + the
#                                usual path under your home directory; nothing
#                                calls hyprctl or gdbus
#
# A live install copies the program, writes ~/.config/hypr/settings-hub.conf (an
# existing file keeps its binds block byte for byte) and settings-hub.lua, hides
# the old "Screen and sleep" menu entry (NoDisplay=true in screen-sleep.desktop,
# if it has no NoDisplay line), adds one `source` line at the end of
# hyprland.conf and, if there is a hyprland.lua (Hyprland 0.57+ then reads only
# that), one `dofile` line at its end -- unless it already loads settings-hub.lua
# itself (dated copies first). Then it reloads Hyprland and checks `hyprctl
# configerrors`: new errors -> the line in the file Hyprland reads is taken out
# again, reload, exit 1. Then the background copy is started through Hyprland,
# not as a child of this script.
#
# Every created file and every added line is listed in
# $XDG_STATE_HOME/settings-hub/install-manifest; uninstall.sh removes exactly that.
# Running it twice adds nothing twice.

set -eu

die() { printf 'error: %s\n' "$*" >&2; exit 2; }
say() { printf '==> %s\n' "$*"; }
ok() { printf '  ok %s\n' "$*"; }
warn() { printf '  !! %s\n' "$*"; }

PREFIX=""
DRY=0
while [ $# -gt 0 ]; do
    case $1 in
        --prefix)
            [ $# -ge 2 ] && [ -n "$2" ] || die "--prefix needs a directory"
            PREFIX=${2%/}
            shift 2
            ;;
        --dry-run) DRY=1; shift ;;
        -h | --help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown argument: $1 (try --help)" ;;
    esac
done

[ "$(id -u)" -ne 0 ] || die "do not run this as root"
if [ -n "$PREFIX" ]; then
    case $PREFIX in /*) ;; *) PREFIX=$PWD/$PREFIX ;; esac
fi
LIVE=0
[ -n "$PREFIX" ] || LIVE=1

SRC=$(cd "$(dirname "$0")" && pwd)

# Paths as they are in a real install (written into generated files) ...
DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
STATE_HOME=${XDG_STATE_HOME:-$HOME/.local/state}
BIN_HOME=$HOME/.local/bin
# ... and where they land now.
APP_DIR=$PREFIX$DATA_HOME/settings-hub
BIN_DIR=$PREFIX$BIN_HOME
DESKTOP_DIR=$PREFIX$DATA_HOME/applications
HYPR_DIR=$PREFIX$CONFIG_HOME/hypr
STATE_DIR=$PREFIX$STATE_HOME/settings-hub
MANIFEST=$STATE_DIR/install-manifest
HYPR_CONF=$HYPR_DIR/hyprland.conf
OWN_CONF=$HYPR_DIR/settings-hub.conf
HYPR_LUA=$HYPR_DIR/hyprland.lua
OWN_LUA=$HYPR_DIR/settings-hub.lua
OLD_DESKTOP=$DESKTOP_DIR/screen-sleep.desktop
TAB=$(printf '\t')
APP_ID=io.github.whyslab.SettingsHub
OBJECT_PATH=/io/github/whyslab/SettingsHub

dry() { [ "$DRY" -eq 1 ]; }
would() { printf '   would %s\n' "$*"; }

if [ "$LIVE" -eq 1 ]; then
    say "Installing for $(id -un) (live)"
    [ -f "$HYPR_CONF" ] || [ -f "$HYPR_LUA" ] ||
        die "no $HYPR_LUA or $HYPR_CONF - is this a Hyprland session?"
    command -v hyprctl >/dev/null 2>&1 || die "hyprctl not found"
    command -v gdbus >/dev/null 2>&1 || warn "gdbus not found: settings-open needs it (glib2)"
else
    say "Installing into ${PREFIX}"
fi
command -v python3 >/dev/null 2>&1 || die "python3 not found"
dry && say "dry run: nothing will be changed"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
NEW_MANIFEST=$STAGE/manifest
: >"$NEW_MANIFEST"
: >"$STAGE/dirs"
record() { printf '%s\n' "$*" >>"$NEW_MANIFEST"; }

# Generated files are made first, in a scratch directory: a damaged binds block
# in an existing settings-hub.conf stops the install before anything changes.
py() { (cd "$SRC" && PYTHONDONTWRITEBYTECODE=1 python3 "$@"); }
py -m settings_hub.binds.writer conf "$STAGE/settings-hub.conf" \
    --data-home "$DATA_HOME" --bin-home "$BIN_HOME" --keep "$OWN_CONF" ||
    die "settings-hub.conf was not generated (see above); nothing was changed"
py -m settings_hub.binds.writer lua "$STAGE/settings-hub.lua" \
    --data-home "$DATA_HOME" --bin-home "$BIN_HOME" ||
    die "settings-hub.lua was not generated (see above); nothing was changed"
py -m settings_hub.registry pages-json "$STAGE/pages.json"
py -m settings_hub.registry open-failed "$STAGE/open-failed.txt" --log "$STATE_HOME/settings-hub/app.log"
py -m settings_hub.registry desktop "$STAGE/settings-hub.desktop" --exec "$BIN_HOME/settings-open"

# Directories that do not exist yet are recorded (outermost first) so the
# uninstaller removes exactly those, if they are empty by then.
make_dir() {
    missing=""
    d=$1
    # (a dry run remembers what it would have created)
    while [ ! -d "$d" ] && ! grep -Fxq "$d" "$STAGE/dirs"; do
        missing="$d
$missing"
        d=$(dirname "$d")
    done
    if [ -n "$missing" ]; then
        if dry; then would "create $1"; else mkdir -p "$1"; fi
    fi
    printf '%s' "$missing" | while IFS= read -r m; do
        [ -n "$m" ] && record "dir$TAB$m" && printf '%s\n' "$m" >>"$STAGE/dirs"
    done
    return 0
}

# put MODE SRC DEST: an identical file is left alone; otherwise it is replaced
# in one step (a copy next to it, then rename).
put() {
    make_dir "$(dirname "$3")"
    record "file$TAB$3"
    if [ -f "$3" ] && cmp -s "$2" "$3" && [ "$(stat -c %a "$3")" = "$1" ]; then
        return 0
    fi
    if dry; then
        would "write $3"
        return 0
    fi
    cp "$2" "$3.new.$$"
    chmod "$1" "$3.new.$$"
    mv -f "$3.new.$$" "$3"
}

make_dir "$STATE_DIR"

put 755 "$SRC/app.py" "$APP_DIR/app.py"
(cd "$SRC" && find settings_hub -name '*.py' -not -path '*/__pycache__/*') | sort |
    while IFS= read -r f; do put 644 "$SRC/$f" "$APP_DIR/$f"; done
put 644 "$SRC/style/base.css" "$APP_DIR/style/base.css"
for f in "$SRC"/style/icons/*.svg; do
    put 644 "$f" "$APP_DIR/style/icons/$(basename "$f")"
done
put 644 "$STAGE/pages.json" "$APP_DIR/pages.json"
put 644 "$STAGE/open-failed.txt" "$APP_DIR/open-failed.txt"
ok "program in $APP_DIR"

put 755 "$SRC/bin/settings-open" "$BIN_DIR/settings-open"
put 755 "$SRC/uninstall.sh" "$BIN_DIR/settings-hub-uninstall"
ok "settings-open and settings-hub-uninstall in $BIN_DIR"

put 644 "$STAGE/settings-hub.desktop" "$DESKTOP_DIR/settings-hub.desktop"
put 644 "$STAGE/settings-hub.conf" "$OWN_CONF"
put 644 "$STAGE/settings-hub.lua" "$OWN_LUA"
ok "settings-hub.desktop, settings-hub.conf, settings-hub.lua"

# The line this install added to FILE earlier, as the old manifest has it.
previous_line() { # FILE TEXT
    [ -f "$MANIFEST" ] || return 1
    grep -F "line$TAB$1$TAB$2$TAB" "$MANIFEST" | head -n 1 | grep . || return 1
}

# Append TEXT as the last line of FILE; the manifest remembers whether a final
# newline had to be added first, so removal restores the file byte for byte.
ADDED_NEWLINE=0
append_line() { # FILE TEXT
    ADDED_NEWLINE=0
    if [ -s "$1" ] && [ "$(tail -c 1 "$1" | od -An -c | tr -d ' ')" != '\n' ]; then
        ADDED_NEWLINE=1
    fi
    if dry; then
        would "append to $1: $2"
    else
        [ "$ADDED_NEWLINE" -eq 0 ] || printf '\n' >>"$1"
        printf '%s\n' "$2" >>"$1"
    fi
    record "line$TAB$1$TAB$2$TAB$ADDED_NEWLINE"
}

# The old "Screen and sleep" menu entry opens the old window; the Settings
# window replaces it. Hidden with one line, only if the file has no NoDisplay
# line of its own. screen-sleep's installer rewrites the file, which drops the
# line again (uninstall then finds nothing to remove).
HIDE=NoDisplay=true
if [ -f "$OLD_DESKTOP" ]; then
    if prev=$(previous_line "$OLD_DESKTOP" "$HIDE") && grep -Fxq "$HIDE" "$OLD_DESKTOP"; then
        record "$prev"
        ok "screen-sleep.desktop already hidden"
    elif grep -q '^NoDisplay[[:space:]]*=' "$OLD_DESKTOP"; then
        ok "screen-sleep.desktop has its own NoDisplay line - left as it is"
    elif [ "$(grep '^\[' "$OLD_DESKTOP" | tail -n 1)" != "[Desktop Entry]" ]; then
        warn "screen-sleep.desktop does not end in its [Desktop Entry] group - not hidden"
    else
        append_line "$OLD_DESKTOP" "$HIDE"
        ok "screen-sleep.desktop hidden from the menu"
    fi
fi

# One line at the end of FILE: a dated copy first, then the line, unless it is
# already there. Sets ADDED_SOURCE / SIZE_BEFORE / ADDED_NEWLINE for that file.
add_hook_line() { # FILE LINE
    ADDED_SOURCE=0
    SIZE_BEFORE=0
    ADDED_NEWLINE=0
    if grep -Fxq "$2" "$1"; then
        if prev=$(previous_line "$1" "$2"); then
            record "$prev"
        else
            record "line$TAB$1$TAB$2${TAB}0"
        fi
        ok "$(basename "$1") already has our line"
    else
        backup="$1.bak-$(date +%Y%m%d)-settings-hub"
        if [ ! -e "$backup" ]; then
            if dry; then would "copy $1 to $backup"; else cp -p "$1" "$backup"; fi
        fi
        SIZE_BEFORE=$(wc -c <"$1")
        append_line "$1" "$2"
        ADDED_SOURCE=1
        ok "$(basename "$1"): one line added (copy: $(basename "$backup"))"
    fi
}

# hyprland.conf: read by Hyprland up to 0.56, and again after a rollback.
if [ "$CONFIG_HOME" = "$HOME/.config" ]; then
    # Hyprland expands the tilde itself; the line stays readable this way.
    # shellcheck disable=SC2088
    conf_ref="~/.config/hypr/settings-hub.conf"
    lua_ref='os.getenv("HOME") .. "/.config/hypr/settings-hub.lua"'
else
    conf_ref="$CONFIG_HOME/hypr/settings-hub.conf"
    lua_ref=$(py -c 'import sys; from settings_hub.hypr import lua_str; print(lua_str(sys.argv[1]))' \
        "$CONFIG_HOME/hypr/settings-hub.lua")
fi
CONF_LINE="source = $conf_ref  # settings-hub"
LUA_LINE="dofile($lua_ref)  -- settings-hub"
HOOK_FILE="" # the file Hyprland reads, if we added a line to it
LINE=""
ADDED_SOURCE=0
SIZE_BEFORE=0
if [ -f "$HYPR_CONF" ]; then
    add_hook_line "$HYPR_CONF" "$CONF_LINE"
    HOOK_FILE=$HYPR_CONF LINE=$CONF_LINE
fi
# hyprland.lua: when it exists, Hyprland reads it and ignores hyprland.conf.
# A config that already loads settings-hub.lua itself (an uncommented line
# naming it) gets nothing more.
if [ -f "$HYPR_LUA" ]; then
    if ! grep -Fxq "$LUA_LINE" "$HYPR_LUA" && py -m settings_hub.hypr loads-settings-hub "$HYPR_LUA"; then
        ok "hyprland.lua loads settings-hub.lua itself - left as it is"
        HOOK_FILE="" ADDED_SOURCE=0
    else
        add_hook_line "$HYPR_LUA" "$LUA_LINE"
        HOOK_FILE=$HYPR_LUA LINE=$LUA_LINE
    fi
    # The Binds page edits only settings-hub.conf, which a Lua config never reads.
    kept=$(sed -n '/^# >>> settings-hub binds$/,/^# <<< settings-hub binds$/p' "$OWN_CONF" 2>/dev/null |
        grep -cv -e '^# >>> settings-hub binds$' -e '^# <<< settings-hub binds$' -e '^[[:space:]]*$' || true)
    if [ "${kept:-0}" -gt 0 ]; then
        warn "settings-hub.conf has $kept bind line(s) from the Binds page; Hyprland reads hyprland.lua, so they do nothing now"
    fi
fi

# A reinstall replaces the manifest; files the old one listed that this
# version no longer ships are removed now.
ROOT=${PREFIX:-$HOME}
if [ -f "$MANIFEST" ]; then
    grep "^file$TAB" "$MANIFEST" | cut -f 2 | while IFS= read -r old; do
        if ! grep -Fxq "file$TAB$old" "$NEW_MANIFEST"; then
            case $old in
                "$ROOT"/*) if dry; then would "remove $old"; else rm -f -- "$old"; fi ;;
            esac
        fi
    done
    grep "^dir$TAB" "$MANIFEST" | while IFS= read -r entry; do
        grep -Fxq "$entry" "$NEW_MANIFEST" || record "$entry"
    done
fi
if dry; then
    would "write $MANIFEST ($(wc -l <"$NEW_MANIFEST") entries)"
else
    cp "$NEW_MANIFEST" "$MANIFEST.new.$$"
    chmod 644 "$MANIFEST.new.$$"
    mv -f "$MANIFEST.new.$$" "$MANIFEST"
fi
ok "manifest: $MANIFEST"

if [ "$LIVE" -eq 0 ]; then
    say "Sandbox install finished"
    exit 0
fi

# ---- the running session ------------------------------------------------------

errors() { hyprctl configerrors 2>/dev/null | grep -v '^[[:space:]]*$' || true; }

if dry; then
    would "run: hyprctl reload, then hyprctl configerrors (new errors -> our line out again)"
    would "restart the background copy: hyprctl dispatch (exec) python3 $APP_DIR/app.py --daemon"
    say "Dry run finished: nothing was changed"
    exit 0
fi

errors >"$STAGE/errors-before"
hyprctl reload >/dev/null || warn "hyprctl reload failed"
errors >"$STAGE/errors-after"
if grep -Fxv -f "$STAGE/errors-before" "$STAGE/errors-after" >"$STAGE/errors-new"; then
    warn "Hyprland reports new config errors:"
    sed 's/^/     /' "$STAGE/errors-new" >&2
    # Taken out only if the file is exactly as this run left it.
    expected=$((SIZE_BEFORE + ADDED_NEWLINE + $(printf '%s\n' "$LINE" | wc -c)))  # bytes, not characters
    if [ "$ADDED_SOURCE" -eq 1 ] && [ "$(tail -n 1 "$HOOK_FILE")" = "$LINE" ] &&
        [ "$(wc -c <"$HOOK_FILE")" -eq "$expected" ]; then
        truncate -s "$SIZE_BEFORE" "$HOOK_FILE" # same inode; the file as it was
        grep -Fxv "line$TAB$HOOK_FILE$TAB$LINE$TAB$ADDED_NEWLINE" "$MANIFEST" \
            >"$STAGE/manifest-left" || true
        cat "$STAGE/manifest-left" >"$MANIFEST"
        hyprctl reload >/dev/null || true
        warn "our line was taken out of $(basename "$HOOK_FILE") again; the other files stay (settings-hub-uninstall removes them)"
    elif [ -n "$HOOK_FILE" ] && [ "$ADDED_SOURCE" -eq 0 ]; then
        warn "our line was in $(basename "$HOOK_FILE") before this run; left in (settings-hub-uninstall removes it)"
    elif [ -n "$HOOK_FILE" ]; then
        warn "$(basename "$HOOK_FILE") changed meanwhile; our line is left in (settings-hub-uninstall removes it)"
    fi
    exit 1
fi
ok "hyprctl reload: no new config errors"

has_owner() {
    gdbus call --session --timeout 1 --dest org.freedesktop.DBus \
        --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner "$APP_ID" 2>/dev/null | grep -q true
}

# A running copy keeps the old code: ask it to quit, then start the new one.
if has_owner; then
    gdbus call --session --timeout 2 --dest "$APP_ID" --object-path "$OBJECT_PATH" \
        --method org.gtk.Actions.Activate quit '[]' '{}' >/dev/null 2>&1 || true
    i=0
    while has_owner && [ "$i" -lt 30 ]; do sleep 0.1; i=$((i + 1)); done
fi
# Through Hyprland, so it is not a child of this script (exec-once only runs at
# login). A Lua config takes only hl.dsp.exec_cmd(...), a .conf only `exec`.
# Only a .conf Hyprland gets the plain form (it answers "Invalid dispatcher"):
# under Lua, plain text would run as Lua code.
start=$(py -c 'import shlex, sys; a, s = sys.argv[1:]; print(f"python3 {shlex.quote(a)} --daemon >>{shlex.quote(s)} 2>&1")' \
    "$APP_DIR/app.py" "$STATE_DIR/app.log")
start_lua=$(py -c 'import sys; from settings_hub.hypr import lua_str; print(lua_str(sys.argv[1]))' "$start")
reply=$(hyprctl dispatch "hl.dsp.exec_cmd($start_lua)" 2>/dev/null || true)
case $reply in *"Invalid dispatcher"*) reply=$(hyprctl dispatch exec "$start" 2>/dev/null || true) ;; esac
[ "$reply" = ok ] || warn "could not start the background copy; settings-open starts it on the first press"
i=0
while ! has_owner && [ "$i" -lt 50 ]; do sleep 0.1; i=$((i + 1)); done
if has_owner; then ok "background copy running"; else warn "background copy not up yet (see $STATE_DIR/app.log)"; fi
say "Installed. SUPER+I opens Settings; undo with settings-hub-uninstall"
