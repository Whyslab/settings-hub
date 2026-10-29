#!/bin/sh
# uninstall.sh - remove settings-hub: exactly what install.sh recorded.
#
#   ./uninstall.sh --prefix DIR           undo a sandbox install, keep history
#   ./uninstall.sh --prefix DIR --purge   also remove history and logs
#
# Installed as ~/.local/bin/settings-hub-uninstall. It reads the install
# manifest and removes the files listed there, the directories install.sh
# created (if empty), and its one line in hyprland.conf -- only when that
# exact line occurs exactly once. Other files are never restored from copies.
# This version handles sandbox installs only and never calls hyprctl or gdbus.

set -eu

die() { printf 'error: %s\n' "$*" >&2; exit 2; }
say() { printf '==> %s\n' "$*"; }
ok() { printf '  ok %s\n' "$*"; }
warn() { printf '  !! %s\n' "$*"; }

PREFIX=""
PURGE=0
while [ $# -gt 0 ]; do
    case $1 in
        --prefix)
            [ $# -ge 2 ] && [ -n "$2" ] || die "--prefix needs a directory"
            PREFIX=${2%/}
            shift 2
            ;;
        --purge) PURGE=1; shift ;;
        -h | --help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown argument: $1 (try --help)" ;;
    esac
done

[ -n "$PREFIX" ] || die "this version handles sandbox installs only: --prefix DIR"
case $PREFIX in /*) ;; *) PREFIX=$PWD/$PREFIX ;; esac

STATE_DIR=$PREFIX${XDG_STATE_HOME:-$HOME/.local/state}/settings-hub
MANIFEST=$STATE_DIR/install-manifest
TAB=$(printf '\t')

inside() { case $1 in "$PREFIX"/*) return 0 ;; *) return 1 ;; esac; }

purge_state() {
    if [ "$PURGE" -eq 1 ] && [ -d "$STATE_DIR" ]; then
        rm -rf -- "$STATE_DIR"
        ok "history and logs removed"
    fi
}

if [ ! -f "$MANIFEST" ]; then
    warn "no install manifest at $MANIFEST - nothing to remove"
    purge_state
    exit 0
fi

say "Removing settings-hub from ${PREFIX}"

# Our line in a file: removed only if it occurs exactly once; a final newline
# that install.sh had to add is taken away again.
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
    ok "$(basename "$file"): our line removed"
}

while IFS="$TAB" read -r kind path text added; do
    [ "$kind" = line ] && remove_line "$path" "$text" "${added:-0}"
done <"$MANIFEST"

removed=0
while IFS="$TAB" read -r kind path; do
    [ "$kind" = file ] || continue
    if inside "$path"; then
        rm -f -- "$path"
        removed=$((removed + 1))
    else
        warn "skipping $path (outside $PREFIX)"
    fi
done <"$MANIFEST"
ok "$removed files removed"

# Python leaves byte-code caches in the program directory.
grep "^file$TAB" "$MANIFEST" | cut -f 2 | grep '\.py$' | while IFS= read -r f; do
    cache=$(dirname "$f")/__pycache__
    if inside "$cache" && [ -d "$cache" ]; then rm -rf -- "$cache"; fi
done

# Directories install.sh created, deepest first, removed only if empty.
dirs=$(grep "^dir$TAB" "$MANIFEST" | cut -f 2 | sort -r -u) || true
rm -f -- "$MANIFEST"
purge_state
printf '%s\n' "$dirs" | while IFS= read -r d; do
    if [ -n "$d" ] && inside "$d" && [ -d "$d" ]; then
        rmdir -- "$d" 2>/dev/null || warn "kept $d (not empty)"
    fi
done
say "Uninstall finished"
