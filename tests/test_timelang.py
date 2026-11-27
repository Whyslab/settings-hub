"""Date, time and language: read without root, change through timedatectl/localectl."""

import subprocess
from datetime import timedelta

import pytest

from settings_hub.backends import timelang as tl

STATUS = """System Locale: LANG=ru_RU.UTF-8
               LC_TIME=en_GB.UTF-8
    VC Keymap: us
   X11 Layout: ru,us
    X11 Model: pc105
  X11 Variant: ,
  X11 Options: terminate:ctrl_alt_bksp,grp:shifts_toggle
"""


class Run:
    def __init__(self, rc=0, err=""):
        self.calls, self.envs, self.rc, self.err = [], [], rc, err

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.envs.append(kwargs.get("env", {}))
        out = ""
        if argv[:2] == [tl.TIMEDATECTL, "show"]:
            out = "Timezone=Europe/Oslo\nNTP=yes\nNTPSynchronized=no\nCanNTP=yes\n"
        elif argv[:2] == [tl.TIMEDATECTL, "list-timezones"]:
            out = "Europe/Oslo\nUTC\nAmerica/New_York\nbad zone\n"
        elif argv[:2] == [tl.LOCALECTL, "status"]:
            out = STATUS
        elif argv[0] == tl.LOCALE:
            out = "C\nC.utf8\nPOSIX\nen_US.utf8\nru_RU.utf8\nde_DE.iso88591\nen_GB.UTF-8\n"
        else:
            return subprocess.CompletedProcess(argv, self.rc, "", self.err)
        return subprocess.CompletedProcess(argv, 0, out, "")


def test_probe_reads_everything():
    run = Run()
    info = tl.Backend(run=run).probe()
    assert (info.timezone, info.ntp, info.synced, info.can_ntp) == ("Europe/Oslo", True, False,
                                                                     True)
    assert info.timezones == ("Europe/Oslo", "UTC", "America/New_York")  # "bad zone" left out
    assert info.locale == {"LANG": "ru_RU.UTF-8", "LC_TIME": "en_GB.UTF-8"}
    assert info.locales == ("en_GB.UTF-8", "en_US.UTF-8", "ru_RU.UTF-8")
    assert info.login == tl.LoginKeys("ru,us", "pc105", ",",
                                      "terminate:ctrl_alt_bksp,grp:shifts_toggle")
    assert all(c[0].startswith("/usr/bin/") for c in run.calls)  # never looked up in PATH
    assert all(e.get("LC_ALL") == "C" for e in run.envs)  # English labels to parse


def test_a_colon_in_a_value_does_not_end_the_locale():
    text = ("System Locale: LANG=en_US.UTF-8\n               LANGUAGE=ru:en\n"
            "               LC_TIME=en_GB.UTF-8\n    VC Keymap: us\n   X11 Layout: us\n")
    locale, login = tl.parse_localectl(text)
    assert locale == {"LANG": "en_US.UTF-8", "LANGUAGE": "ru:en", "LC_TIME": "en_GB.UTF-8"}
    assert login.layouts == "us"


def test_locales_with_a_modifier():
    assert tl.utf8_locales("ca_ES.utf8@valencia\nsr_RS.utf8@latin\nru_RU.utf8\n") == (
        "ca_ES.UTF-8@valencia", "ru_RU.UTF-8", "sr_RS.UTF-8@latin")


def test_putting_back_what_was_there():
    run = Run()
    backend = tl.Backend(run=run)
    backend.set_locale({"LANG": "C.UTF-8"})  # the old value may be C: always there
    backend.set_locale({"LANG": "ru_RU.UTF-8", "LANGUAGE": "ru:en"})
    backend.set_login_keys(tl.LoginKeys("us,us", "pc105", ",dvorak-l",  # a real variant
                                        "grp:shifts_toggle"))
    with pytest.raises(ValueError):
        backend.set_login_keys(tl.LoginKeys("us", "pc105", "-x", ""))
    with pytest.raises(ValueError):
        backend.set_locale({"LANG": "ru_RU.UTF-8", "LANGUAGE": "ru\nLC_ALL=x"})
    # real xkb names: compose:rwin-altgr, eurosign:E, model tm2030USB-102, variant macOS
    backend.set_login_keys(tl.LoginKeys("us,ua", "tm2030USB-102", ",macOS",
                                        "compose:rwin-altgr,eurosign:E,grp:shifts_toggle"))
    backend.set_locale({"LANG": "ru_RU.utf8"})  # locale.conf may spell it so
    sets = [c for c in run.calls if c[1] in ("set-locale", "--no-convert")]
    assert sets[1] == [tl.LOCALECTL, "set-locale", "LANG=ru_RU.UTF-8", "LANGUAGE=ru:en"]
    assert sets[2][-2] == ",dvorak-l"


def test_nothing_answers():
    def broken(argv, **kwargs):
        raise FileNotFoundError(argv[0])
    info = tl.Backend(run=broken).probe()
    assert not info.ok_time and not info.ok_locale and info.ntp is None
    assert info.timezone == "" and info.locales == ()


def test_changes_run_the_right_commands():
    run = Run()
    backend = tl.Backend(run=run)
    backend.set_timezone("America/New_York")
    backend.set_ntp(False)
    backend.set_locale({"LANG": "en_US.UTF-8", "LC_TIME": "en_GB.UTF-8"})
    backend.set_login_keys(tl.LoginKeys("us,ru,no", "pc105", "", "grp:win_space_toggle"))
    changes = [c for c in run.calls if c[1] in ("set-timezone", "set-ntp", "set-locale",
                                                 "--no-convert")]
    assert changes == [
        [tl.TIMEDATECTL, "set-timezone", "America/New_York"],
        [tl.TIMEDATECTL, "set-ntp", "false"],
        [tl.LOCALECTL, "set-locale", "LANG=en_US.UTF-8", "LC_TIME=en_GB.UTF-8"],
        [tl.LOCALECTL, "--no-convert", "set-x11-keymap", "us,ru,no", "pc105", "",
         "grp:win_space_toggle"],
    ]


@pytest.mark.parametrize("zone", ["Mars/Base", "Europe/Oslo; reboot", "../../etc/passwd",
                                  "-h", ""])
def test_a_time_zone_the_system_does_not_list_is_refused(zone):
    run = Run()
    with pytest.raises(ValueError):
        tl.Backend(run=run).set_timezone(zone)
    assert not any(c[1] == "set-timezone" for c in run.calls)


def test_only_installed_languages_and_sane_keys():
    run = Run()
    backend = tl.Backend(run=run)
    for bad in ({"LANG": "fr_FR.UTF-8"}, {"LANG": "ru_RU.UTF-8\nLC_ALL=C"},
                {"LANG": "ru_RU.UTF-8", "PATH": "/tmp"}, {"LC_TIME": "ru_RU.UTF-8"}):
        with pytest.raises(ValueError):
            backend.set_locale(bad)
    for bad in (tl.LoginKeys("", "pc105", "", ""), tl.LoginKeys("us,-x", "pc105", "", ""),
                tl.LoginKeys("us", "pc105", "", "grp:a b"),
                tl.LoginKeys("us,ru,no,de,fr", "pc105", "", "")):
        with pytest.raises(ValueError):
            backend.set_login_keys(bad)
    assert not any(c[1] in ("set-locale", "--no-convert") for c in run.calls)


def test_a_login_screen_you_cannot_type_a_password_on_is_refused():
    assert tl.login_safe(tl.LoginKeys("ru,us", "", "", "grp:shifts_toggle"))  # as now
    assert tl.login_safe(tl.LoginKeys("us", "", "", ""))
    assert tl.login_safe(tl.LoginKeys("us,ru", "", "", ""))  # Latin first: no switch needed
    assert not tl.login_safe(tl.LoginKeys("ru", "", "", "grp:shifts_toggle"))
    assert not tl.login_safe(tl.LoginKeys("ru,us", "", "", "terminate:ctrl_alt_bksp"))
    assert not tl.login_safe(tl.LoginKeys("ru,ua", "", "", "grp:shifts_toggle"))  # none Latin
    assert not tl.login_safe(tl.LoginKeys("us", "", "rus", ""))  # a variant may not be Latin
    assert not tl.login_safe(tl.LoginKeys("us(rus)", "", "", ""))
    assert not tl.login_safe(tl.LoginKeys("in", "", "", ""))  # Devanagari
    assert not tl.login_safe(tl.LoginKeys("us,ru,no,de,fr", "", "", "grp:shifts_toggle"))
    assert not tl.login_safe(tl.LoginKeys("", "", "", ""))
    run = Run()
    for bad in (tl.LoginKeys("ru", "pc105", "", ""), tl.LoginKeys("ru,us", "pc105", "", "")):
        with pytest.raises(tl.UnsafeLogin):
            tl.Backend(run=run).set_login_keys(bad)
    assert not any("set-x11-keymap" in c for c in run.calls)


def test_values_from_a_hand_edited_history_go_nowhere():
    run = Run()
    backend = tl.Backend(run=run)
    for bad in ({"LANG": "ru_RU.UTF-8", "LANG=x -y": "ru_RU.UTF-8"},
                {"LANG": "ru_RU.UTF-8", "LC_ALL": "C"},
                {"LANG": "ru_RU.UTF-8", "LANGUAGE": "-h"}):
        with pytest.raises(ValueError):
            backend.set_locale(bad)
    backend.apply({"ntp": "false"})  # not a bool: not "true" either
    assert not any(c[1] in ("set-locale", "set-ntp") for c in run.calls)

    class Listed(Run):  # even if the system listed it, an option is not a zone
        def __call__(self, argv, **kwargs):
            done = super().__call__(argv, **kwargs)
            if argv[:2] == [tl.TIMEDATECTL, "list-timezones"]:
                done.stdout += "-h\nEurope/Oslo\n\n"
            return done
    run = Listed()
    assert "-h" not in tl.Backend(run=run).probe().timezones
    assert tl.Backend.asks_password  # History runs its undo off the GTK thread


def test_what_went_wrong_is_told_apart():
    cases = [
        ("Failed to set time zone: Access denied", PermissionError),
        ("Failed: Interactive authentication required.", tl.NoAgent),
        ("Failed to set time zone: Invalid or not installed time zone", RuntimeError),
    ]
    for said, kind in cases:
        with pytest.raises(kind):
            tl.Backend(run=Run(rc=1, err=said + "\n")).set_ntp(True)
    assert issubclass(tl.NoAgent, PermissionError)

    def slow(argv, **kwargs):
        if argv[1] == "set-ntp":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return Run()(argv, **kwargs)
    with pytest.raises(TimeoutError):
        tl.Backend(run=slow).set_ntp(True)


def test_history_reads_and_puts_back():
    run = Run()
    backend = tl.Backend(run=run)
    values = backend.read(["timezone", "ntp", "locale", "login-keys", "nope"])
    assert values == {"timezone": "Europe/Oslo", "ntp": True,
                      "locale": {"LANG": "ru_RU.UTF-8", "LC_TIME": "en_GB.UTF-8"},
                      "login-keys": ["ru,us", "pc105", ",",
                                     "terminate:ctrl_alt_bksp,grp:shifts_toggle"]}
    backend.apply({"timezone": "UTC", "ntp": False, "locale": {"LANG": "en_US.UTF-8"},
                   "login-keys": ["us", "pc105", "", "grp:alt_shift_toggle"]})
    changes = [c[1:3] for c in run.calls if c[1] in ("set-timezone", "set-ntp", "set-locale")]
    assert changes == [["set-timezone", "UTC"], ["set-ntp", "false"],
                       ["set-locale", "LANG=en_US.UTF-8"]]


def test_layout_switch_helpers():
    assert tl.switch_of("terminate:ctrl_alt_bksp,grp:shifts_toggle") == "grp:shifts_toggle"
    assert tl.switch_of("caps:escape") == ""
    assert tl.with_switch("terminate:ctrl_alt_bksp,grp:shifts_toggle,grp_led:scroll",
                          "grp:win_space_toggle") == \
        "terminate:ctrl_alt_bksp,grp_led:scroll,grp:win_space_toggle"
    assert tl.with_switch("grp:caps_toggle", "") == ""
    names = tl.xkb_layouts("! model\n  pc105  Generic\n\n! layout\n  us  English (US)\n"
                           "  ru              Russian\n\n! variant\n  chr  us: Cherokee\n")
    assert names == {"us": "English (US)", "ru": "Russian"}


def test_page_words():
    pytest.importorskip("gi")
    from settings_hub.pages import datetime as page

    assert page.offset_text(timedelta(hours=1)) == "+01:00"
    assert page.offset_text(timedelta(hours=-3, minutes=-30)) == "-03:30"
    assert page.offset_text(None) == "+00:00"
    assert page.zone_offset("UTC") == "+00:00"
    assert page.zone_offset("Nowhere/City") == ""
    assert page.layout_name("ru", {}) == "Русская"
    assert page.layout_name("al", {"al": "Albanian"}) == "Albanian"
    assert page.layout_name("us(intl)", {}) == "Английская (США)"
    assert page.locale_name("ru_RU.UTF-8") == "Русский"
    assert page.switch_name("grp:menu_toggle") == "grp:menu_toggle"
