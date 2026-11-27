"""Disk space: how full each disk is, and what takes the room in the home folder.

All of it is read without root:

    /proc/self/mounts + statvfs    the disks and how full they are
    du -xk --max-depth=1 ~         the biggest folders in the home folder
    ~/.local/share/Trash           the Trash (emptied with `gio trash --empty`)
    /var/cache/pacman/pkg          old package versions (paccache.timer prunes them)
    Steam's appmanifest_*.acf      installed games and their size on disk

The one change offered is emptying the Trash, which the person confirms first;
nothing here runs as root.

No GTK.
"""

from __future__ import annotations

import logging
import os
import re
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

BACKEND = WORKER = "disk-space"
DU = "/usr/bin/du"
NICE = "/usr/bin/nice"
IONICE = "/usr/bin/ionice"
GIO = "/usr/bin/gio"
SYSTEMCTL = "/usr/bin/systemctl"
PACMAN_CONF = Path("/etc/pacman.conf")
PKG_CACHE = Path("/var/cache/pacman/pkg")
LOW = 0.10  # less free than this share of a disk...
LOW_ROOM = 20 * 1024 ** 3  # ...and less than this: say so (9 % of 4 TB is plenty)
MOUNTS = Path("/proc/self/mounts")
TOP = 8  # folders listed
MIN_SHARE = 0.01  # folders smaller than this share of the home folder are not listed
DU_TIMEOUT = 120
REAL_FS = frozenset({
    "ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "vfat", "exfat", "ntfs", "ntfs3",
    "fuseblk", "zfs", "bcachefs", "jfs", "reiserfs", "nilfs2", "hfsplus",
})
LOCAL_FS = REAL_FS | {"tmpfs"}  # where a Steam library may be looked into: no network hangs
# gvfs empties the trash on network and FUSE disks too, but they are not looked into
NETWORK_FS = frozenset({"nfs", "nfs4", "cifs", "smb3", "smbfs", "9p", "afs", "ceph",
                        "glusterfs", "davfs", "sshfs"})
# disks of the system itself: gvfs leaves their .Trash-UID alone (GLib's own list)
SYSTEM_MOUNTS = ("/", "/boot", "/efi", "/home", "/usr", "/var", "/opt", "/srv", "/root",
                 "/tmp", "/etc", "/nix", "/gnu")
SKIP = ("/proc", "/sys", "/dev", "/run/user", "/var/lib/docker", "/var/lib/containers",
        "/snap", "/var/snap")


@dataclass(frozen=True)
class Mount:
    path: str
    device: str
    fstype: str
    total: int  # bytes
    used: int
    free: int  # what a user may still write

    @property
    def share(self) -> float:
        """The used share, as df counts it (used / (used + free))."""
        room = self.used + self.free
        return self.used / room if room else 0.0

    @property
    def low(self) -> bool:
        return self.total > 0 and self.free / self.total < LOW and self.free < LOW_ROOM


@dataclass(frozen=True)
class Folder:
    path: Path
    size: int  # bytes on disk


@dataclass(frozen=True)
class Game:
    name: str
    size: int


@dataclass(frozen=True)
class Trash:
    size: int | None  # None: du did not answer
    items: int
    other: int = 0  # of them, on other disks
    network: tuple[str, ...] = ()  # disks whose trash is emptied too but not counted


@dataclass(frozen=True)
class Space:
    """What takes the room; counted on demand (du can take a while)."""

    counted_at: datetime
    home: Path
    home_size: int = 0
    folders: tuple[Folder, ...] = ()  # biggest first
    trash: Trash = field(default_factory=lambda: Trash(0, 0))
    cache_size: int = 0
    cache_dir: Path | None = None
    pkg_size: int = 0
    pkg_dir: Path | None = None
    pkg_auto: bool | None = None  # paccache.timer prunes old versions; None: unknown
    games: tuple[Game, ...] = ()  # biggest first
    complete: bool = True  # du answered


def _unescape(text: str) -> str:
    """/proc/mounts writes a space as \\040, a tab as \\011 and so on."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), text)


def mount_table(text: str) -> list[tuple[str, str, str]]:
    """Every line of /proc/mounts as (device, mount point, fs type)."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            out.append((_unescape(parts[0]), _unescape(parts[1]), parts[2]))
    return out


def fs_of(path: Path, table: list[tuple[str, str, str]]) -> str:
    """The fs type of the mount a path is on (by its text: nothing is touched)."""
    text = os.path.normpath(str(path))
    best, kind = -1, ""
    for _device, mount, fstype in table:
        if (text == mount or text.startswith(mount.rstrip("/") + "/")) and len(mount) > best:
            best, kind = len(mount), fstype
    return kind


def safe_resolve(path: Path, table: list[tuple[str, str, str]],
                 hops: int = 0) -> Path | None:
    """The real path, found one part at a time without stepping onto a disk that is
    not local (a hung network mount would block even a stat). None: not there, a
    network disk on the way, or a symlink loop."""
    parts = Path(os.path.normpath(str(path))).parts
    if not parts or parts[0] != "/" or hops > 20:
        return None
    current = Path("/")
    for index, part in enumerate(parts[1:], start=1):
        step = current / part
        kind = fs_of(step, table)
        if kind and kind not in LOCAL_FS:  # "": no mount listed, "/" is always local
            return None
        try:
            mode = os.lstat(step).st_mode
        except OSError:
            return None
        if stat.S_ISLNK(mode):
            try:
                target = os.readlink(step)
            except OSError:
                return None
            return safe_resolve(current / target / Path(*parts[index + 1:])
                                if index + 1 < len(parts) else current / target,
                                table, hops + 1)
        current = step
    return current


def read_small(path: Path, limit: int = 1 << 20) -> str | None:
    """A regular file's text, at most `limit` bytes; never a FIFO or a device."""
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):  # before opening: devices stay shut
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        return os.read(fd, limit).decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def parse_mounts(text: str) -> list[tuple[str, str, str]]:
    """(device, mount point, fs type) of the real disks, once per device."""
    seen: dict[str, tuple[str, str, str]] = {}
    for device, path, fstype in mount_table(text):
        if fstype not in REAL_FS:
            continue
        if any(path == s or path.startswith(s + "/") for s in SKIP):
            continue
        old = seen.get(device)
        if old is None or len(path) < len(old[1]):  # a bind mount or subvolume: the top one
            seen[device] = (device, path, fstype)
    return list(seen.values())


def _order(path: str) -> tuple[int, str]:
    return ({"/": 0, "/home": 1, "/boot": 2, "/efi": 2, "/boot/efi": 2}.get(path, 3), path)


def mounts(text: str | None = None,
           statvfs: Callable[[str], os.statvfs_result] = os.statvfs) -> tuple[Mount, ...]:
    if text is None:
        text = read_small(MOUNTS, 4 << 20)
        if text is None:
            return ()
    out = []
    for device, path, fstype in parse_mounts(text):
        try:
            st = statvfs(path)
        except OSError:
            continue
        size = st.f_frsize or st.f_bsize
        total = st.f_blocks * size
        if total <= 0:
            continue
        out.append(Mount(path, device, fstype, total, (st.f_blocks - st.f_bfree) * size,
                         st.f_bavail * size))
    return tuple(sorted(out, key=lambda m: _order(m.path)))


def parse_du(raw: bytes) -> dict[Path, int]:
    """`du -0 -k` output: "KiB<TAB>path" records ended by NUL (a name may hold a newline)."""
    out: dict[Path, int] = {}
    for record in raw.split(b"\0"):
        size, sep, path = record.lstrip(b"\n").partition(b"\t")
        if not sep:
            continue
        try:
            out[Path(os.fsdecode(path))] = int(size) * 1024
        except ValueError:
            continue
    return out


_VDF = re.compile(r'"([^"]+)"\s+"([^"]*)"')


def read_manifest(text: str) -> Game | None:
    values = {k.lower(): v for k, v in _VDF.findall(text)}
    try:
        size = int(values.get("sizeondisk", ""))
    except ValueError:
        return None
    name = values.get("name", "").strip()
    return Game(name[:60], size) if name and size > 0 else None


def library_paths(text: str) -> list[Path]:
    """libraryfolders.vdf: every "path" is a Steam library."""
    return [Path(v.replace("\\\\", "\\")) for k, v in _VDF.findall(text) if k.lower() == "path"]


def pkg_cache_dirs(text: str) -> list[Path]:
    """CacheDir lines of pacman.conf (they may name several); the default when none."""
    out = []
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "CacheDir":
            out.extend(Path(v) for v in value.split())
    return out or [PKG_CACHE]


@dataclass
class Backend:
    run: Callable[..., subprocess.CompletedProcess] = field(default=subprocess.run)
    home: Path | None = None  # Path.home() when the count starts
    now: Callable[[], datetime] = field(default=datetime.now)
    pacman_conf: Path = PACMAN_CONF
    steam_roots: tuple[Path, ...] | None = None  # where Steam keeps its libraries
    mounts_file: Path = MOUNTS
    uid: int = field(default_factory=os.getuid)

    def _table(self) -> list[tuple[str, str, str]]:
        return mount_table(read_small(self.mounts_file, 4 << 20) or "")

    def _home(self) -> Path:
        return self.home if self.home is not None else Path.home()

    def _data(self) -> Path:
        value = os.environ.get("XDG_DATA_HOME", "")
        return Path(value) if value.startswith("/") else self._home() / ".local" / "share"

    def _cache(self) -> Path:
        value = os.environ.get("XDG_CACHE_HOME", "")
        return Path(value) if value.startswith("/") else self._home() / ".cache"

    def trash_dir(self) -> Path:
        return self._data() / "Trash"

    def du(self, paths: list[Path], depth: int | None = None) -> dict[Path, int] | None:
        """Sizes on disk; None when du could not run at all."""
        paths = [p for p in paths if p.exists()]
        if not paths:
            return {}
        argv = [DU, "-x", "-k", "-0"]
        argv += [f"--max-depth={depth}"] if depth is not None else ["-s"]
        argv += ["--", *map(str, paths)]
        if os.access(IONICE, os.X_OK):  # du waits on the disk, not the processor
            argv = [IONICE, "-c3", *argv]
        if os.access(NICE, os.X_OK):
            argv = [NICE, "-n", "19", *argv]
        try:
            done = self.run(argv, capture_output=True, timeout=DU_TIMEOUT, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("du failed: %s", exc)
            return None
        if done.returncode not in (0, 1):  # 1: some folder could not be read
            return None
        return parse_du(done.stdout if isinstance(done.stdout, bytes)
                        else os.fsencode(done.stdout or ""))

    def _pkg_auto(self) -> bool | None:
        try:
            done = self.run([SYSTEMCTL, "is-enabled", "paccache.timer"], capture_output=True,
                            text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        said = (done.stdout or "").strip()
        if said in ("enabled", "enabled-runtime"):
            return True
        if said in ("disabled", "masked", "masked-runtime"):
            return False
        return None  # static, linked...; nothing on stdout: no such timer, or no answer

    def _games(self, table: list[tuple[str, str, str]]) -> tuple[Game, ...]:
        """Installed Steam games. Libraries come from a file anyone may edit: only
        local disks are looked into, and only small regular files are read."""
        home = self._home()
        roots = self.steam_roots if self.steam_roots is not None else (
            self._data() / "Steam", home / ".steam" / "steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam")
        libraries: list[Path] = []
        for root in roots:
            apps = safe_resolve(root / "steamapps", table)
            if apps is None:
                continue
            libraries.append(apps)
            text = read_small(apps / "libraryfolders.vdf")
            if text is not None:
                libraries.extend(p / "steamapps" for p in library_paths(text)[:32]
                                 if p.is_absolute())
        games: dict[str, Game] = {}
        seen: set[Path] = set()
        for apps in libraries:
            real = safe_resolve(apps, table)  # every library, and every symlink on the way
            if real is None or real in seen:
                continue
            seen.add(real)
            try:
                manifests = sorted(apps.glob("appmanifest_*.acf"))[:500]
            except OSError:
                continue
            for manifest in manifests:
                text = read_small(manifest)
                game = read_manifest(text) if text is not None else None
                if game is not None:
                    games[manifest.name + str(real)] = game
        return tuple(sorted(games.values(), key=lambda g: -g.size))

    @staticmethod
    def _system(mount: str) -> bool:
        return mount in SYSTEM_MOUNTS or any(mount.startswith(s + "/") for s in SKIP) or \
            mount.startswith(("/usr/", "/var/", "/boot/"))

    def trash_dirs(self, table: list[tuple[str, str, str]] | None = None) -> list[Path]:
        """The trash folders `gio trash --empty` empties that can be counted: the home
        one, then each local disk's .Trash-UID and .Trash/UID (a USB stick's too)."""
        table = self._table() if table is None else table
        out, seen = [self.trash_dir()], set()
        for _device, mount, fstype in table:
            if fstype not in REAL_FS or self._system(mount):
                continue
            for candidate in (Path(mount, f".Trash-{self.uid}"),
                              Path(mount, ".Trash", str(self.uid))):
                if not candidate.is_symlink() and candidate.is_dir():  # lstat first
                    out.append(candidate)
        unique = []
        for path in out:
            try:
                key = path.resolve()
            except OSError:
                continue
            if key not in seen:
                seen.add(key)
                unique.append(path)
        return unique

    @staticmethod
    def _items(trash: Path) -> int:
        """What a trash holds: entries in files/ (some may lack their .trashinfo)."""
        counts = []
        for sub, pattern in (("files", "*"), ("info", "*.trashinfo")):
            try:  # pathlib's "*" matches dot files too
                counts.append(sum(1 for _ in (trash / sub).glob(pattern)))
            except OSError:
                counts.append(0)
        return max(counts)

    def network_disks(self, table: list[tuple[str, str, str]] | None = None) -> tuple[str, ...]:
        """Network and FUSE disks: gvfs empties their trash too, they are not counted
        (only the mount table is read: nothing on them is touched)."""
        table = self._table() if table is None else table
        out = []
        for _device, mount, fstype in table:
            kind = fstype.removeprefix("fuse.")
            if (kind in NETWORK_FS or (fstype.startswith("fuse.") and kind not in (
                    "gvfsd-fuse", "portal", "xdg-document-portal"))) \
                    and not self._system(mount) and mount not in out:
                out.append(mount)
        return tuple(out)

    def trash_all(self, table: list[tuple[str, str, str]] | None = None) -> Trash:
        """What `empty_trash` removes: counted, and the disks that cannot be."""
        table = self._table() if table is None else table
        dirs = self.trash_dirs(table)
        sizes = self.du(dirs)
        items = [self._items(d) for d in dirs]
        return Trash(sum(sizes.get(d, 0) for d in dirs) if sizes is not None else None,
                     sum(items), sum(items[1:]), self.network_disks(table))

    def count(self) -> Space:
        """What takes the room. Slow on a cold disk: run it in a worker."""
        home = self._home()
        table = self._table()
        sizes = self.du([home], depth=1)
        complete = sizes is not None
        sizes = sizes or {}
        home_size = sizes.pop(home, 0)
        folders = sorted((Folder(p, s) for p, s in sizes.items() if p.parent == home),
                         key=lambda f: -f.size)
        listed = tuple(f for f in folders if f.size >= home_size * MIN_SHARE)[:TOP]
        cache = self._cache()
        conf = read_small(self.pacman_conf) or ""
        pkg_dirs = pkg_cache_dirs(conf)
        # ~/.cache was counted with the home folder already
        extra = self.du(pkg_dirs + ([] if cache in sizes else [cache])) or {}
        return Space(
            counted_at=self.now(), home=home, home_size=home_size, folders=listed,
            trash=self.trash_all(table),
            cache_size=sizes.get(cache, extra.get(cache, 0)),
            cache_dir=cache if cache.is_dir() else None,
            pkg_size=sum(extra.get(p, 0) for p in pkg_dirs),
            pkg_dir=next((p for p in pkg_dirs if p.is_dir()), None),
            pkg_auto=self._pkg_auto(), games=self._games(table), complete=complete)

    def empty_trash(self) -> None:
        """Delete everything in every trash for good (the page asks first,
        with the numbers of trash_all)."""
        try:
            done = self.run([GIO, "trash", "--empty"], capture_output=True, text=True,
                            timeout=300, check=False)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(str(exc)) from exc
        if done.returncode != 0:
            said = (done.stderr or "").strip().splitlines()
            raise RuntimeError(said[-1] if said else f"exit {done.returncode}")
        log.info("emptied the Trash")
