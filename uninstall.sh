#!/bin/sh
# uninstall.sh - remove settings-hub: exactly what install.sh recorded.
#
#   settings-hub-uninstall                 undo the live install, keep history
#   settings-hub-uninstall --purge         also remove history and logs
#   settings-hub-uninstall --dry-run       print every action, change nothing
#   ./uninstall.sh --prefix DIR [--purge]  undo a sandbox install (never calls
#                                          hyprctl or gdbus)
#
# Installed as ~/.local/bin/settings-hub-uninstall. It reads the install
# manifest and removes the files listed there, the directories install.sh
# created (if empty), and each line install.sh added -- only when that exact
# line occurs exactly once (same file, same inode, same permissions). Other
# files are never restored from copies. Live: the background copy is asked to
# quit and the key-capture submap is reset first; after our line leaves
# hyprland.conf or hyprland.lua and our files are gone, Hyprland is reloaded
# (also when hyprland.lua loads settings-hub.lua by a line of its own).

set -eu

die() { printf 'error: %s\n' "$*" >&2; exit 2; }
say() { printf '==> %s\n' "$*"; }
ok() { printf '  ok %s\n' "$*"; }
warn() { printf '  !! %s\n' "$*"; }

PREFIX=""
PURGE=0
DRY=0
while [ $# -gt 0 ]; do
    case $1 in
        --prefix)
            [ $# -ge 2 ] && [ -n "$2" ] || die "--prefix needs a directory"
            PREFIX=${2%/}
            shift 2
            ;;
        --purge) PURGE=1; shift ;;
        --dry-run) DRY=1; shift ;;
        -h | --help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown argument: $1 (try --help)" ;;
    esac
done

[ "$(id -u)" -ne 0 ] || die "do not run this as root"
if [ -n "$PREFIX" ]; then
    case $PREFIX in /*) ;; *) PREFIX=$PWD/$PREFIX ;; esac
fi
LIVE=0
[ -n "$PREFIX" ] || LIVE=1
ROOT=${PREFIX:-$HOME}

STATE_DIR=$PREFIX${XDG_STATE_HOME:-$HOME/.local/state}/settings-hub
MANIFEST=$STATE_DIR/install-manifest
TAB=$(printf '\t')
APP_ID=io.github.whyslab.SettingsHub
OBJECT_PATH=/io/github/whyslab/SettingsHub

dry() { [ "$DRY" -eq 1 ]; }
would() { printf '   would %s\n' "$*"; }
inside() { case $1 in "$ROOT"/*) return 0 ;; *) return 1 ;; esac; }

purge_state() {
    if [ "$PURGE" -eq 1 ] && [ -d "$STATE_DIR" ]; then
        if dry; then would "remove $STATE_DIR"; else rm -rf -- "$STATE_DIR"; fi
        ok "history and logs removed"
    fi
}

if [ ! -f "$MANIFEST" ]; then
    warn "no install manifest at $MANIFEST - nothing to remove"
    purge_state
    exit 0
fi

if [ "$LIVE" -eq 1 ]; then say "Removing settings-hub (live)"; else say "Removing settings-hub from ${PREFIX}"; fi
dry && say "dry run: nothing will be changed"

has_owner() {
    gdbus call --session --timeout 1 --dest org.freedesktop.DBus \
        --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner "$APP_ID" 2>/dev/null | grep -q true
}

if [ "$LIVE" -eq 1 ]; then
    if dry; then
        would "ask the background copy to quit (gdbus ... Activate quit)"
        would "run: hyprctl dispatch submap reset (or its Lua form)"
    else
        gdbus call --session --timeout 2 --dest "$APP_ID" --object-path "$OBJECT_PATH" \
            --method org.gtk.Actions.Activate quit '[]' '{}' >/dev/null 2>&1 || true
        i=0
        while has_owner && [ "$i" -lt 30 ]; do sleep 0.1; i=$((i + 1)); done
        has_owner && warn "the background copy is still running"
        # A Lua config (Hyprland 0.57+) takes only hl.dsp.submap(...).
        [ "$(hyprctl dispatch 'hl.dsp.submap("reset")' 2>/dev/null)" = ok ] ||
            hyprctl dispatch submap reset >/dev/null 2>&1 || true
        ok "background copy asked to quit; submap reset"
    fi
fi

# Our line in a file: removed only if it occurs exactly once; a final newline
# that install.sh had to add is taken away again.
RELOAD=0
remove_line() { # FILE TEXT ADDED_NEWLINE
    file=$1
    if ! inside "$file" || [ ! -f "$file" ]; then
        warn "skipping $file"
        return 0
    fi
    count=$(grep -Fxc -- "$2" "$file" || true)
    if [ "$count" != 1 ]; then
        warn "$(basename "$file"): our line occurs $count times - left as it is"
        return 0
    fi
    if dry; then
        would "remove from $file: $2"
        return 0
    fi
    before=$(stat -c '%i %a' "$file")
    lines=$(wc -l <"$file")
    tmp=$(mktemp)
    LINE=$2 NL=$3 awk '
        { line[NR] = $0 }
        $0 == ENVIRON["LINE"] { hit = NR }
        END {
            last = (hit == NR) ? NR - 1 : NR
            for (i = 1; i <= NR; i++) {
                if (i == hit) continue
                if (i == last && hit == NR && ENVIRON["NL"] == "1") printf "%s", line[i]
                else print line[i]
            }
        }' "$file" >"$tmp"
    cat "$tmp" >"$file" # same inode, same permissions
    rm -f "$tmp"
    left=$(grep -Fxc -- "$2" "$file" || true)
    if [ "$left" != 0 ] || [ "$(stat -c '%i %a' "$file")" != "$before" ] ||
        [ "$(wc -l <"$file")" -lt $((lines - 2)) ]; then
        warn "$(basename "$file"): unexpected result after removing our line - please check it"
    fi
    ok "$(basename "$file"): our line removed"
    case $file in */hyprland.conf | */hyprland.lua) RELOAD=1 ;; esac
}

while IFS="$TAB" read -r kind path text added; do
    [ "$kind" = line ] && remove_line "$path" "$text" "${added:-0}"
done <"$MANIFEST"

removed=0
while IFS="$TAB" read -r kind path; do
    [ "$kind" = file ] || continue
    if inside "$path"; then
        if dry; then
            [ -e "$path" ] && would "remove $path"
        else
            rm -f -- "$path"
        fi
        removed=$((removed + 1))
    else
        warn "skipping $path (outside $ROOT)"
    fi
done <"$MANIFEST"
ok "$removed files removed"

# settings-hub.lua is gone; a hyprland.lua that loads it by a line of its own
# must forget its binds too.
HYPR_LUA=$PREFIX${XDG_CONFIG_HOME:-$HOME/.config}/hypr/hyprland.lua
[ -f "$HYPR_LUA" ] && ! dry && RELOAD=1
if [ "$LIVE" -eq 1 ] && [ "$RELOAD" -eq 1 ] && ! dry; then
    hyprctl reload >/dev/null 2>&1 || warn "hyprctl reload failed"
    errors=$(hyprctl configerrors 2>/dev/null | grep -v '^[[:space:]]*$' || true)
    if [ -n "$errors" ]; then
        warn "Hyprland reports config errors:"
        printf '%s\n' "$errors" | sed 's/^/     /' >&2
    else
        ok "hyprctl reload: no config errors"
    fi
fi


# Python leaves byte-code caches in the program directory.
grep "^file$TAB" "$MANIFEST" | cut -f 2 | grep '\.py$' | while IFS= read -r f; do
    cache=$(dirname "$f")/__pycache__
    if inside "$cache" && [ -d "$cache" ]; then
        if dry; then would "remove $cache"; else rm -rf -- "$cache"; fi
    fi
done

# Directories install.sh created, deepest first, removed only if empty.
dirs=$(grep "^dir$TAB" "$MANIFEST" | cut -f 2 | sort -r -u) || true
if dry; then
    would "remove $MANIFEST and the directories install.sh created, if empty"
    purge_state
    say "Dry run finished: nothing was changed"
    exit 0
fi
rm -f -- "$MANIFEST"
purge_state
printf '%s\n' "$dirs" | while IFS= read -r d; do
    if [ -n "$d" ] && inside "$d" && [ -d "$d" ]; then
        rmdir -- "$d" 2>/dev/null || warn "kept $d (not empty)"
    fi
done
say "Uninstall finished"
