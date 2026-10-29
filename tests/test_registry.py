"""Registry and strings: every page is complete, exports are well-formed."""

import json
import re
import subprocess
import sys

from conftest import ROOT

from settings_hub import registry, strings


def test_ids_unique_and_well_formed():
    ids = [p.id for p in registry.PAGES]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z0-9-]+", i) for i in ids)  # settings-open accepts these
    assert ids == ["screen-sleep", "wallpaper", "animations", "binds", "history"]


def test_every_page_has_text_icon_module_and_group():
    for page in registry.PAGES:
        text = strings.PAGES[page.id]
        assert text["title"] and text["keywords"]
        assert page.group in registry.GROUP_ORDER and page.group in strings.GROUPS
        assert page.icon_path.is_file()
        assert (ROOT / "settings_hub" / "pages" / f"{page.module}.py").is_file()
        assert re.fullmatch(r"#[0-9a-f]{6}", page.color)
    assert set(strings.PAGES) == {p.id for p in registry.PAGES}


def test_icon_colour_matches_registry():
    for page in registry.PAGES:
        assert page.color in page.icon_path.read_text()


def test_groups_in_sidebar_order():
    groups = registry.grouped()
    assert [g for g, _ in groups] == list(registry.GROUP_ORDER)
    assert [p.id for _, ps in groups for p in ps] == [p.id for p in registry.PAGES]


def test_export_pages_json(tmp_path):
    out = tmp_path / "pages.json"
    subprocess.run([sys.executable, "-m", "settings_hub.registry", "pages-json", str(out)],
                   cwd=ROOT, check=True)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [p["id"] for p in data] == [p.id for p in registry.PAGES]
    for item in data:
        assert set(item) == {"id", "title", "keywords"}
        assert item["title"] == registry.title(item["id"])
        assert isinstance(item["keywords"], list) and item["keywords"]


def test_export_desktop_and_message(tmp_path):
    desk = tmp_path / "s.desktop"
    subprocess.run([sys.executable, "-m", "settings_hub.registry", "desktop", str(desk),
                    "--exec", "/opt/x/settings-open"], cwd=ROOT, check=True)
    text = desk.read_text(encoding="utf-8")
    assert "Exec=/opt/x/settings-open\n" in text
    assert "StartupWMClass=settings-hub" in text
    assert f"Name[ru]={strings.APP_TITLE}" in text
    msg = tmp_path / "m.txt"
    subprocess.run([sys.executable, "-m", "settings_hub.registry", "open-failed", str(msg),
                    "--log", "/var/x/app.log"], cwd=ROOT, check=True)
    assert "/var/x/app.log" in msg.read_text(encoding="utf-8")


def test_bad_registry_command_fails():
    run = subprocess.run([sys.executable, "-m", "settings_hub.registry", "nope", "x"],
                         cwd=ROOT, capture_output=True)
    assert run.returncode == 2


def test_importing_the_core_does_not_import_gtk():
    code = ("import sys; import settings_hub.registry, settings_hub.search, "
            "settings_hub.history, settings_hub.loader, settings_hub.workers; "
            "print('gi' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    assert out.strip() == "False"
