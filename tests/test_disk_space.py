"""Disk space: disks from /proc/mounts, du of the home folder, Trash, Steam games."""

import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from settings_hub.backends import disk_space as ds

MOUNTS = """\
/dev/nvme0n1p2 / ext4 rw,relatime 0 0
proc /proc proc rw 0 0
tmpfs /tmp tmpfs rw 0 0
/dev/nvme0n1p1 /boot vfat rw 0 0
/dev/nvme0n1p2 /var/lib/docker/overlay ext4 rw 0 0
/dev/nvme0n1p2 /srv/bind ext4 rw 0 0
/dev/sdb1 /run/media/user/My\\040Disk exfat rw 0 0
/dev/sdc1 /run/user/1000/doc fuseblk rw 0 0
gvfsd-fuse /run/user/1000/gvfs fuse.gvfsd-fuse rw 0 0
"""


class Stat:
    def __init__(self, blocks, bfree, bavail, frsize=4096):
        self.f_blocks, self.f_bfree, self.f_bavail = blocks, bfree, bavail
        self.f_frsize, self.f_bsize = frsize, frsize


def test_real_disks_once_each_system_first():
    found = ds.parse_mounts(MOUNTS)
    assert [p for _, p, _ in found] == ["/", "/boot", "/run/media/user/My Disk"]


def test_how_full_and_nearly_full():
    stats = {"/": Stat(1000, 50, 40), "/boot": Stat(100, 90, 90),
             "/run/media/user/My Disk": Stat(10, 10, 10)}
    got = ds.mounts(MOUNTS, statvfs=lambda p: stats[p])
    root = got[0]
    assert (root.path, root.total, root.used, root.free) == ("/", 4096000, 950 * 4096, 40 * 4096)
    assert root.low and not got[1].low
    assert round(root.share, 3) == round(950 / 990, 3)  # as df: used / (used + free)
    assert got[2].share == 0.0


def test_a_disk_that_cannot_be_read_is_left_out():
    def statvfs(path):
        if path == "/boot":
            raise PermissionError(path)
        return Stat(10, 5, 5)
    assert [m.path for m in ds.mounts(MOUNTS, statvfs=statvfs)] == [
        "/", "/run/media/user/My Disk"]


def test_du_output_with_odd_names():
    raw = b"8\t/h/a\nb\x0016\t/h/c\x00junk\x00x\t/h/d\x00"
    assert ds.parse_du(raw) == {Path("/h/a\nb"): 8192, Path("/h/c"): 16384}


def test_steam_files():
    acf = '"AppState"\n{\n\t"appid"\t"570"\n\t"name"\t"Dota 2"\n\t"SizeOnDisk"\t"77"\n}\n'
    assert ds.read_manifest(acf) == ds.Game("Dota 2", 77)
    assert ds.read_manifest('"name" "x"\n"SizeOnDisk" "0"') is None
    assert ds.read_manifest('"name" "x"') is None
    vdf = '"libraryfolders"\n{\n "0"\n {\n  "path"  "/data/Steam"\n }\n' \
          ' "1"\n {\n  "path"  "/mnt/games"\n }\n}\n'
    assert ds.library_paths(vdf) == [Path("/data/Steam"), Path("/mnt/games")]


def test_pacman_cache_dirs():
    assert ds.pkg_cache_dirs("#CacheDir = /x/\n") == [ds.PKG_CACHE]
    assert ds.pkg_cache_dirs("[options]\nCacheDir = /a/ /b/\n") == [Path("/a"), Path("/b")]


class Run:
    """Real du on the temporary folders; systemctl and gio answered here."""

    def __init__(self, timer="enabled", gio_rc=0, gio_err="", du_rc=None):
        self.calls = []
        self.timer, self.gio_rc, self.gio_err, self.du_rc = timer, gio_rc, gio_err, du_rc

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if ds.DU in argv:
            if self.du_rc is not None:
                return subprocess.CompletedProcess(argv, self.du_rc, b"", b"")
            return subprocess.run(argv, **kwargs)
        if argv[0] == ds.SYSTEMCTL:
            return subprocess.CompletedProcess(argv, 0, self.timer + "\n", "")
        if argv[0] == ds.GIO:
            return subprocess.CompletedProcess(argv, self.gio_rc, "", self.gio_err)
        raise AssertionError(argv)


def fill(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))  # random: no file system may make it smaller


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    fill(home / "Videos" / "film.mkv", 3_000_000)
    fill(home / ".cache" / "thumbs" / "a.png", 1_000_000)
    fill(home / "tiny" / "note.txt", 10)
    trash = home / ".local" / "share" / "Trash"
    fill(trash / "files" / "old.iso", 500_000)
    (trash / "info").mkdir(parents=True)
    (trash / "info" / "old.iso.trashinfo").write_text("[Trash Info]\n")
    apps = home / ".local" / "share" / "Steam" / "steamapps"
    apps.mkdir(parents=True)
    (apps / "appmanifest_1.acf").write_text('"name" "Small"\n"SizeOnDisk" "10"\n')
    (apps / "appmanifest_2.acf").write_text('"name" "Big"\n"SizeOnDisk" "999"\n')
    (apps / "libraryfolders.vdf").write_text(f'"path" "{apps.parent}"\n')  # itself again
    (home / ".steam").mkdir()
    (home / ".steam" / "steam").symlink_to(apps.parent)  # the same library, once
    return home


def test_count_lists_the_biggest_folders(home, tmp_path):
    conf = tmp_path / "pacman.conf"
    pkg = tmp_path / "pkg"
    fill(pkg / "a.pkg.tar.zst", 200_000)
    conf.write_text(f"[options]\nCacheDir = {pkg}/\n")
    run = Run()
    space = ds.Backend(run=run, home=home, pacman_conf=conf, mounts_file=tmp_path / "none",
                       now=lambda: datetime(2026, 11, 27, 15, 0)).count()
    names = [f.path.name for f in space.folders]
    assert names[0] == "Videos" and ".cache" in names and ".local" in names
    assert "tiny" not in names  # under 1 % of the home folder
    assert space.home_size >= 4_500_000 and space.complete
    assert space.trash.items == 1 and space.trash.size >= 500_000
    assert space.cache_size >= 1_000_000 and space.cache_dir == home / ".cache"
    assert space.pkg_size >= 200_000 and space.pkg_dir == pkg and space.pkg_auto is True
    assert space.games == (ds.Game("Big", 999), ds.Game("Small", 10))
    du = [a for a in run.calls if ds.DU in a]
    assert du and all("-x" in a for a in du)  # never into other disks
    assert all(a[0] in (ds.NICE, ds.DU) for a in run.calls if a[0] != ds.SYSTEMCTL)


def test_count_says_when_du_did_not_answer(home, tmp_path):
    none = tmp_path / "none"
    space = ds.Backend(run=Run(du_rc=2, timer="disabled"), home=home, mounts_file=none).count()
    assert not space.complete and space.folders == () and space.pkg_auto is False
    assert space.trash.size is None and space.trash.items == 1  # not "0 КБ"
    assert ds.Backend(run=Run(timer=""), home=home, mounts_file=none).count().pkg_auto is None


def test_a_folder_du_cannot_read_still_counts(home, tmp_path):
    locked = home / "locked"
    fill(locked / "x", 10)
    locked.chmod(0)
    try:
        space = ds.Backend(run=Run(), home=home, mounts_file=tmp_path / "none").count()
    finally:
        locked.chmod(0o755)
    assert space.complete and space.folders[0].path.name == "Videos"


def test_emptying_the_trash(home):
    run = Run()
    backend = ds.Backend(run=run, home=home)
    backend.empty_trash()
    assert run.calls == [["/usr/bin/gio", "trash", "--empty"]]
    with pytest.raises(RuntimeError, match="busy"):
        ds.Backend(run=Run(gio_rc=1, gio_err="gio: file busy\n"), home=home).empty_trash()

    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
    with pytest.raises(TimeoutError):
        ds.Backend(run=slow, home=home).empty_trash()
    trash = ds.Backend(run=Run(), home=home, mounts_file=home / "none").trash_all()
    assert (trash.items, trash.other, trash.network) == (1, 0, ()) and trash.size >= 500_000


def test_every_trash_that_gio_empties_is_counted(home, tmp_path):
    usb = tmp_path / "usb"
    (usb / ".Trash-1000" / "files").mkdir(parents=True)
    (usb / ".Trash-1000" / "files" / "a").write_text("a")
    (usb / ".Trash-1000" / "files" / "no-info").write_text("b")  # its .trashinfo lost
    (usb / ".Trash-1000" / "info").mkdir()
    (usb / ".Trash-1000" / "info" / "a.trashinfo").write_text("[Trash Info]\n")
    (usb / ".Trash-2000").mkdir()  # someone else's
    mounts = tmp_path / "mounts"
    (usb / "link").mkdir()
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "files").mkdir(parents=True)
    (elsewhere / "files" / "x").write_text("x")
    (usb / "link" / ".Trash-1000").symlink_to(elsewhere)  # never followed
    mounts.write_text(f"/dev/sdb1 {usb} vfat rw 0 0\n/dev/sdb2 {usb / 'link'} ext4 rw 0 0\n"
                      f"srv:/x {tmp_path / 'nas'} nfs4 rw 0 0\n"
                      f"me@h:/ {tmp_path / 'ssh'} fuse.sshfs rw 0 0\n"
                      f"gvfsd-fuse /run/user/1000/gvfs fuse.gvfsd-fuse rw 0 0\n"
                      f"/dev/nvme0n1p2 / ext4 rw 0 0\n/dev/nvme0n1p3 /home ext4 rw 0 0\n")
    backend = ds.Backend(run=Run(), home=home, mounts_file=mounts, uid=1000)
    assert backend.trash_dirs() == [home / ".local/share/Trash", usb / ".Trash-1000"]
    trash = backend.trash_all()
    assert (trash.items, trash.other) == (3, 2) and trash.size > 0
    assert backend._system("/") and backend._system("/home") and backend._system("/var/x")
    assert not backend._system(str(usb))  # the system's own disks: gvfs leaves them
    # emptied by gvfs too, but not counted: the dialog names them
    assert trash.network == (str(tmp_path / "nas"), str(tmp_path / "ssh"))


def test_steam_files_that_could_hang_are_not_read(home, tmp_path):
    apps = home / ".local" / "share" / "Steam" / "steamapps"
    os.mkfifo(apps / "appmanifest_3.acf")  # would block a plain read for ever
    (apps / "appmanifest_4.acf").symlink_to("/dev/zero")  # would read until memory ends
    remote = tmp_path / "nfs" / "lib" / "steamapps"
    remote.mkdir(parents=True)
    (remote / "appmanifest_5.acf").write_text('"name" "Remote"\n"SizeOnDisk" "5"\n')
    (apps / "libraryfolders.vdf").write_text(f'"path" "{remote.parent}"\n"path" "rel"\n')
    mounts = tmp_path / "mounts"
    mounts.write_text(f"/dev/a / ext4 rw 0 0\ntmpfs /tmp tmpfs rw 0 0\n"
                      f"srv:/x {tmp_path / 'nfs'} nfs rw 0 0\n")
    backend = ds.Backend(run=Run(), home=home, mounts_file=mounts)
    assert backend._games(backend._table()) == (ds.Game("Big", 999), ds.Game("Small", 10))
    assert ds.read_small(apps / "appmanifest_3.acf") is None
    # a library reached through a symlink onto the network disk is not looked into
    (home / "games").symlink_to(remote.parent)
    (apps / "libraryfolders.vdf").write_text(f'"path" "{home / "games"}"\n')
    assert backend._games(backend._table()) == (ds.Game("Big", 999), ds.Game("Small", 10))
    table = backend._table()
    assert ds.safe_resolve(home / "games" / "steamapps", table) is None
    assert ds.safe_resolve(home / ".steam" / "steam", table) == apps.parent.resolve()


def test_timer_states_and_nearly_full():
    def state(said):
        return ds.Backend(run=lambda argv, **k: subprocess.CompletedProcess(
            argv, 0, said, ""))._pkg_auto()
    assert state("enabled-runtime\n") is True and state("masked\n") is False
    assert state("static\n") is None
    gib = 1024 ** 3
    assert ds.Mount("/", "d", "ext4", 100 * gib, 95 * gib, 5 * gib).low
    assert not ds.Mount("/d", "d", "ext4", 4000 * gib, 3640 * gib, 360 * gib).low  # 9 % of 4 TB
    assert ds.Mount("/boot", "d", "vfat", gib, gib - 50 * 2 ** 20, 50 * 2 ** 20).low


def test_page_words():
    pytest.importorskip("gi")
    from settings_hub.pages import system

    assert system.size_text(155 * 1024 ** 3) == "155.0 ГБ"
    assert system.size_text(327 * 1024 ** 2) == "327 МБ"
    assert system.size_text(12 * 1024) == "12 КБ"
    assert system.size_text(int(1023.7 * 1024 ** 2)) == "1.0 ГБ"
    assert system.size_text(int(1023.8 * 1024)) == "1 МБ"
    assert system.size_text(4 * 1024 ** 4) == "4.0 ТБ"
    assert system.folder_name(Path("/h/.local")) == "Данные программ"
    assert system.folder_name(Path("/h/stuff")) == "stuff"
    assert system.short_path(Path("/h/u/.local"), Path("/h/u")) == "~/.local"
    assert system.short_path(Path("/var/x"), Path("/h/u")) == "/var/x"
    mount = ds.Mount("/run/media/u/USB", "/dev/sdb1", "exfat", 1, 0, 1)
    assert system.mount_name(mount) == "USB"
    assert system.mount_name(ds.Mount("/", "d", "ext4", 1, 0, 1)) == "Системный диск"
