"""Form controls for one setting: a switch, a number, a choice or a line.

A control knows its variable (variables.Var), shows the stored value and calls
on_change(value) when a person changes it. set() never calls back: the page
uses it to show a fresh value read from the source of truth, and a re-read must
not look like an edit.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ..variables import Var  # noqa: E402

OnChange = Callable[[Any], None]


class Control:
    """A widget, its variable and the quiet re-read."""

    def __init__(self, var: Var, on_change: OnChange) -> None:
        self.var = var
        self.on_change = on_change
        self._quiet = False
        self.widget: Gtk.Widget = self._build()

    # ---- for subclasses ------------------------------------------------

    def _build(self) -> Gtk.Widget:
        raise NotImplementedError

    def _show(self, value: Any) -> None:
        raise NotImplementedError

    def _value(self) -> Any:
        raise NotImplementedError

    # ---- used by the page ----------------------------------------------

    def set(self, value: Any) -> None:
        self._quiet = True
        try:
            self._show(value)
        finally:
            self._quiet = False

    def value(self) -> Any:
        return self._value()

    def _changed(self) -> None:
        if not self._quiet:
            self.on_change(self._value())


class SwitchControl(Control):
    def _build(self) -> Gtk.Widget:
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", lambda *_: self._changed())
        return self.switch

    def _show(self, value: Any) -> None:
        self.switch.set_active(bool(value))

    def _value(self) -> Any:
        return self.switch.get_active()


class SpinControl(Control):
    """An int or a float. A float with unit "%" is shown as 0..100 percent."""

    def _build(self) -> Gtk.Widget:
        var = self.var
        lo = float(var.lo if var.lo is not None else 0)
        hi = float(var.hi if var.hi is not None else 100)
        step = float(var.step or 1)
        self.percent = var.kind == "float" and var.unit == "%"
        if self.percent:
            lo, hi, step = lo * 100, hi * 100, max(step * 100, 1)
        spin = Gtk.SpinButton.new_with_range(lo, hi, step)
        spin.set_numeric(True)
        spin.set_digits(0 if var.kind == "int" or self.percent else _digits(step))
        spin.set_width_chars(5)
        spin.set_alignment(1.0)
        spin.set_valign(Gtk.Align.CENTER)
        spin.connect("value-changed", lambda *_: self._changed())
        self.spin = spin
        if not var.unit:
            return spin
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(spin)
        unit = Gtk.Label(label=var.unit)
        unit.add_css_class("sh-dim")
        box.append(unit)
        self.widget_box = box
        return box

    def _show(self, value: Any) -> None:
        number = float(value)
        self.spin.set_value(number * 100 if self.percent else number)

    def _value(self) -> Any:
        number = self.spin.get_value()
        if self.var.kind == "int":
            return int(round(number))
        return round(number / 100, 4) if self.percent else round(number, 4)


def _digits(step: float) -> int:
    text = f"{step:.4f}".rstrip("0")
    return max(0, len(text.split(".")[1]) if "." in text else 0)


class ChoiceControl(Control):
    def __init__(self, var: Var, on_change: OnChange,
                 choices: list[tuple[str, str]]) -> None:
        """choices: [(value, label)] in the order the drop-down shows them."""
        self.choices = choices
        super().__init__(var, on_change)

    def _build(self) -> Gtk.Widget:
        self.dropdown = Gtk.DropDown.new_from_strings([label for _v, label in self.choices])
        self.dropdown.set_valign(Gtk.Align.CENTER)
        self.dropdown.connect("notify::selected", lambda *_: self._changed())
        return self.dropdown

    def _show(self, value: Any) -> None:
        for index, (choice, _label) in enumerate(self.choices):
            if choice == value or str(choice) == str(value):
                self.dropdown.set_selected(index)
                return

    def _value(self) -> Any:
        index = self.dropdown.get_selected()
        if index == Gtk.INVALID_LIST_POSITION or index >= len(self.choices):
            return self.var.default
        return self.choices[index][0]


class EntryControl(Control):
    def _build(self) -> Gtk.Widget:
        self.entry = Gtk.Entry()
        self.entry.set_width_chars(18)
        self.entry.set_placeholder_text(self.var.default or "")
        self.entry.set_valign(Gtk.Align.CENTER)
        self.entry.connect("activate", lambda *_: self._changed())
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self._changed())
        self.entry.add_controller(focus)
        return self.entry

    def _show(self, value: Any) -> None:
        self.entry.set_text("" if value is None else str(value))

    def _value(self) -> Any:
        return self.entry.get_text()


def make(var: Var, on_change: OnChange,
         choices: list[tuple[str, str]] | None = None) -> Control:
    """The control for a variable. `choices` overrides the labels of a choice."""
    if var.kind == "bool":
        return SwitchControl(var, on_change)
    if var.kind in ("int", "float"):
        return SpinControl(var, on_change)
    if var.kind == "choice":
        return ChoiceControl(var, on_change, choices or [(c, c) for c in var.choices])
    return EntryControl(var, on_change)
