"""Charge of the mouse and headphones: reading and the low charge warnings."""

import json
from pathlib import Path

from settings_hub.backends import devices as dev


def power_supply(base: Path, name: str, **values: str) -> None:
    entry = base / name
    entry.mkdir(parents=True)
    entry.joinpath("uevent").write_text(
        "".join(f"POWER_SUPPLY_{k}={v}\n" for k, v in values.items()), encoding="utf-8")


def hid(base: Path, name: str, hid_id: str) -> None:
    entry = base / name
    entry.mkdir(parents=True)
    entry.joinpath("uevent").write_text(f"HID_ID={hid_id}\nHID_NAME=x\n", encoding="utf-8")


def bluez(objects: dict) -> dev.Runner:
    out = json.dumps({"type": "a{oa{sa{sv}}}", "data": [objects]})
    return lambda argv: (0, out, "")


def var(value):
    return {"type": "s" if isinstance(value, str) else "y", "data": value}


AIRPODS = {
    "/org/bluez/hci0/dev_08_E6": {
        "org.bluez.Device1": {"Alias": var("AirPods"), "Address": var("08:E6"),
                              "Icon": var("audio-headphones")},
        "org.bluez.Battery1": {"Percentage": var(64)},
    },
    "/org/bluez/hci0/dev_AA": {  # paired, no battery: not shown
        "org.bluez.Device1": {"Alias": var("Speaker")},
    },
}

def NO_BLUEZ(argv):
    return 1, "", "no bluez"


def test_mouse_from_kernel_laptop_battery_skipped(tmp_path):
    power = tmp_path / "power"
    power_supply(power, "BAT0", NAME="BAT0", CAPACITY="100", SCOPE="System")
    power_supply(power, "AC", NAME="AC", ONLINE="1")
    power_supply(power, "hidpp_battery_0", NAME="hidpp_battery_0", MODEL_NAME="PRO X 2",
                 CAPACITY="27", STATUS="Discharging", ONLINE="1", SCOPE="Device")
    found = dev.probe(NO_BLUEZ, power, tmp_path / "hid")
    assert found == [dev.Device(key="sys:hidpp_battery_0", name="PRO X 2", kind="mouse",
                                percent=27)]


def test_asleep_and_charging_flags(tmp_path):
    power = tmp_path / "power"
    power_supply(power, "hidpp_battery_0", MODEL_NAME="PRO X 2", CAPACITY="27",
                 STATUS="Unknown", ONLINE="0", SCOPE="Device")
    power_supply(power, "hidpp_battery_1", MODEL_NAME="MX Keys Keyboard", CAPACITY="80",
                 STATUS="Charging", ONLINE="1", SCOPE="Device")
    # Older receivers say online=0 while charging: that is not "asleep".
    power_supply(power, "hidpp_battery_2", MODEL_NAME="M705", CAPACITY="50",
                 STATUS="Charging", ONLINE="0", SCOPE="Device")
    mouse, keyboard, old = dev.from_sysfs(power)
    assert mouse.asleep and not mouse.charging
    assert keyboard.charging and not keyboard.asleep and keyboard.kind == "keyboard"
    assert old.charging and not old.asleep


def test_bluetooth_headphones_from_bluez(tmp_path):
    found = dev.probe(bluez(AIRPODS), tmp_path / "power", tmp_path / "hid")
    assert found == [dev.Device(key="bt:08:E6", name="AirPods", kind="headphones",
                                percent=64)]


def test_same_device_from_kernel_and_bluez_is_shown_once(tmp_path):
    power = tmp_path / "power"
    power_supply(power, "hid-aa-battery", MODEL_NAME="airpods", CAPACITY="60",
                 SCOPE="Device")
    found = dev.probe(bluez(AIRPODS), power, tmp_path / "hid")
    assert [d.key for d in found] == ["sys:hid-aa-battery"]


def test_g435_is_listed_as_unreadable_once(tmp_path):
    hids = tmp_path / "hid"
    hid(hids, "0003:046D:0ACB.0004", "0003:0000046D:00000ACB")
    hid(hids, "0003:046D:0ACB.0005", "0003:0000046D:00000ACB")  # second interface
    hid(hids, "0003:046D:C54D.0001", "0003:0000046D:0000C54D")  # the mouse receiver
    found = dev.probe(NO_BLUEZ, tmp_path / "power", hids)
    assert found == [dev.Device(key="usb:046d:0acb", name="Logitech G435",
                                kind="headphones", percent=None)]


def test_broken_sources_give_nothing(tmp_path):
    power = tmp_path / "power"
    power_supply(power, "hidpp_battery_0", MODEL_NAME="M", CAPACITY="?", SCOPE="Device")
    def garbage(argv):
        return 0, "not json", ""

    found = dev.probe(garbage, power, tmp_path / "missing")
    assert [d.percent for d in found] == [None]
    assert dev.probe(NO_BLUEZ, tmp_path / "nope", tmp_path / "nope") == []


# ---- warnings -----------------------------------------------------------------

def mouse(percent, charging=False):
    return dev.Device(key="sys:m", name="Mouse", percent=percent, charging=charging)


def test_warns_once_at_20_then_once_at_5():
    alerts = dev.Alerts()
    said = []
    for percent in (30, 21, 20, 19, 18, 6, 5, 4, 3):
        said += [(d.percent, lvl) for d, lvl in alerts.check([mouse(percent)])]
    assert said == [(20, 20), (5, 5)]


def test_first_seen_low_gives_one_message_not_two():
    alerts = dev.Alerts()
    assert [lvl for _d, lvl in alerts.check([mouse(3)])] == [5]
    assert alerts.check([mouse(3)]) == []


def test_charging_resets_and_warns_again_next_time():
    alerts = dev.Alerts()
    assert alerts.check([mouse(18)])
    assert alerts.check([mouse(19, charging=True)]) == []
    assert [lvl for _d, lvl in alerts.check([mouse(18)])] == [20]


def test_small_wobble_above_level_does_not_repeat():
    alerts = dev.Alerts()
    assert alerts.check([mouse(20)])
    assert alerts.check([mouse(23)]) == []
    assert alerts.check([mouse(20)]) == []
    assert alerts.check([mouse(30)]) == []
    assert alerts.check([mouse(20)])  # charged back up: a new cycle


def test_unreadable_devices_never_warn():
    alerts = dev.Alerts()
    assert alerts.check([dev.Device(key="usb:x", name="G435", percent=None)]) == []


def test_usb_c_ports_and_absent_batteries_are_skipped(tmp_path):
    power = tmp_path / "power"
    power_supply(power, "ucsi-source-psy-USBC000:001", TYPE="USB", SCOPE="Device",
                 ONLINE="0")
    power_supply(power, "hid-touch-battery", TYPE="Battery", SCOPE="Device",
                 PRESENT="0", CAPACITY="0", MODEL_NAME="Pen")
    assert dev.from_sysfs(power) == []


def test_key_follows_serial_number_not_the_entry_number(tmp_path):
    power = tmp_path / "power"
    power_supply(power, "hidpp_battery_1", MODEL_NAME="PRO X 2", CAPACITY="18",
                 SERIAL_NUMBER="fb-97-c1-5d", SCOPE="Device")
    (found,) = dev.from_sysfs(power)
    assert found.key == "sys:fb-97-c1-5d"


def test_asleep_device_does_not_warn_and_failed_warning_is_retried():
    alerts = dev.Alerts()
    sleeping = dev.Device(key="sys:m", name="Mouse", percent=4, asleep=True)
    assert alerts.check([sleeping]) == []
    ((device, level),) = alerts.check([mouse(4)])
    alerts.forget(device)  # notify-send failed
    assert [lvl for _d, lvl in alerts.check([mouse(4)])] == [5]
