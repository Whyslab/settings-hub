"""The page registry: ids, sidebar groups, icons and colours.

No text lives here (titles and keywords are in strings.py). This module has no
GTK dependency, so the installer can run it to export pages.json for the rofi
hub and the .desktop entry:

    python3 -m settings_hub.registry pages-json FILE
    python3 -m settings_hub.registry desktop FILE --exec CMD
    python3 -m settings_hub.registry open-failed FILE --log PATH
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from . import strings

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "style" / "icons"


@dataclass(frozen=True)
class PageInfo:
    id: str
    group: str
    icon: str
    color: str

    @property
    def module(self) -> str:
        """Module name under settings_hub.pages that builds this page."""
        return self.id.replace("-", "_")

    @property
    def icon_path(self) -> Path:
        return ICON_DIR / self.icon


GROUP_ORDER = ("display", "keyboard", "system")

PAGES: tuple[PageInfo, ...] = (
    PageInfo("screen-sleep", "display", "screen-sleep.svg", "#007aff"),
    PageInfo("wallpaper", "display", "wallpaper.svg", "#32ade6"),
    PageInfo("animations", "display", "animations.svg", "#af52de"),
    PageInfo("binds", "keyboard", "binds.svg", "#8e8e93"),
    PageInfo("history", "system", "history.svg", "#ff9500"),
)

DEFAULT_PAGE = PAGES[0].id


def get(page_id: str) -> PageInfo | None:
    for page in PAGES:
        if page.id == page_id:
            return page
    return None


def title(page_id: str) -> str:
    return strings.PAGES[page_id]["title"]


def keywords(page_id: str) -> list[str]:
    return list(strings.PAGES[page_id]["keywords"])


def rows(page_id: str) -> dict[str, tuple[str, list[str]]]:
    return dict(strings.PAGES[page_id]["rows"])


def grouped() -> list[tuple[str, list[PageInfo]]]:
    """Pages by sidebar group, in display order; empty groups are left out."""
    out = []
    for group in GROUP_ORDER:
        members = [p for p in PAGES if p.group == group]
        if members:
            out.append((group, members))
    return out


def export_pages() -> list[dict]:
    """What the rofi hub reads: [{id, title, keywords}]."""
    return [
        {"id": p.id, "title": title(p.id), "keywords": keywords(p.id)}
        for p in PAGES
    ]


def desktop_entry(exec_cmd: str) -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=Settings",
        f"Name[ru]={strings.APP_TITLE}",
        f"Comment[ru]={strings.APP_COMMENT}",
        f"Keywords={strings.APP_KEYWORDS}",
        f"Exec={exec_cmd}",
        "Icon=preferences-system",
        "Categories=Settings;",
        "StartupWMClass=settings-hub",
        "Terminal=false",
        "",
    ])


def _write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def main(argv: list[str]) -> int:
    usage = "usage: registry {pages-json FILE | desktop FILE --exec CMD | open-failed FILE --log P}"
    if len(argv) < 2:
        print(usage, file=sys.stderr)
        return 2
    cmd, path, rest = argv[0], argv[1], argv[2:]
    if cmd == "pages-json" and not rest:
        _write(path, json.dumps(export_pages(), ensure_ascii=False, indent=1) + "\n")
        return 0
    if cmd == "desktop" and len(rest) == 2 and rest[0] == "--exec":
        _write(path, desktop_entry(rest[1]))
        return 0
    if cmd == "open-failed" and len(rest) == 2 and rest[0] == "--log":
        _write(path, strings.OPEN_FAILED.format(log=rest[1]) + "\n")
        return 0
    print(usage, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
