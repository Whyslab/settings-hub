"""The "Lock screen" page: a hyprlock look built from a preset and a few choices.

The logic is controllers.lockscreen. Choices only redraw the preview (drawn by
the simulator; hyprlock itself is never started); "Apply" writes the config,
one History item.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import lockscreen as lk  # noqa: E402
from ..controllers import lockscreen as ctl  # noqa: E402
from ..variables import Var  # noqa: E402
from ..widgets import fields  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

PREVIEW_W, PREVIEW_H = 560, 315
SETTLE_MS = 500  # a number is applied to the draft once it has been still this long


def example(fmt: str) -> str:
    """What a date or clock format shows now (GLib's strftime), first letter capital."""
    try:
        text = GLib.DateTime.new_now_local().format(fmt) or fmt
    except (TypeError, GLib.Error):
        return fmt
    return text[:1].upper() + text[1:]


def preview_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "settings-hub" / "lockscreen"


class LockscreenPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(lk.BACKEND)
        if backend is None:
            backend = lk.Backend(self.ctx.workers)
            lk.register(self.ctx.history, backend)
            self.ctx.backends[lk.BACKEND] = backend
        self.lock = ctl.Controller(backend, self.ctx.history, self, preview_dir())
        self._quiet = False
        self._settle: dict[str, tuple[int, Any]] = {}  # key -> (timer, value) still moving
        self.theme_font = ""

        # ---- the picture and the state
        shown = self.add_group(Group(strings.LOCK_PREVIEW, strings.LOCK_PREVIEW_NOTE))
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True,
                                   hexpand=True)
        self.picture.set_size_request(PREVIEW_W, PREVIEW_H)
        self.picture.add_css_class("sh-lock-preview")
        self.picture_note = Gtk.Label(label=strings.LOCK_PREVIEW_BUSY, wrap=True,
                                      xalign=0)
        self.picture_note.add_css_class("sh-dim")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("sh-row-inner")
        box.append(self.picture)
        box.append(self.picture_note)
        holder = Gtk.ListBoxRow(activatable=False)
        holder.set_child(box)
        shown.list.append(holder)
        self.state_row = shown.add(Row(""))

        self.controls: dict[str, fields.Control] = {}

        def control(group: Group, row_id: str, key: str, var: Var, title: str, hint: str,
                    choices: list[tuple[str, str]] | None = None) -> Row:
            widget = fields.make(var, lambda value, k=key: self._changed(k, value), choices)
            self.controls[key] = widget
            row = group.add(Row(title, hint or None, suffix=widget.widget, row_id=row_id))
            if row_id:
                self.rows[row_id] = row
            return row

        # ---- look
        look = self.add_group(Group(strings.LOCK_LOOK))
        control(look, "preset", "preset", Var("preset", "choice", "dock", choices=lk.PRESETS),
                strings.LOCK_PRESET, strings.LOCK_PRESET_HINT,
                [(p, strings.LOCK_PRESETS[p]) for p in lk.PRESETS])

        # ---- parts
        parts = self.add_group(Group(strings.LOCK_PARTS, strings.LOCK_PARTS_NOTE))
        for index, part in enumerate(lk.PARTS):
            title, hint = strings.LOCK_PART[part]
            control(parts, "parts" if index == 0 else "", part,
                    Var(part, "bool", lk.DEFAULTS.shown(part)), title, hint)

        # ---- clock and date
        when = self.add_group(Group(strings.LOCK_TIME))
        control(when, "clock_format", "clock_format",
                Var("clock_format", "choice", lk.CLOCKS[0], choices=lk.CLOCKS),
                strings.LOCK_CLOCK_FORMAT, "",
                [(f, f"{example(f)} — {strings.LOCK_CLOCK_NAMES[f]}") for f in lk.CLOCKS])
        control(when, "date_format", "date_format",
                Var("date_format", "choice", lk.DATES[0], choices=lk.DATES),
                strings.LOCK_DATE_FORMAT, "", [(f, example(f)) for f in lk.DATES])

        # ---- font and sizes
        font = self.add_group(Group(strings.LOCK_FONT_GROUP))
        dialog = Gtk.FontDialog(modal=True)
        self.font_button = Gtk.FontDialogButton(dialog=dialog, valign=Gtk.Align.CENTER)
        self.font_button.set_level(Gtk.FontLevel.FAMILY)
        self.font_button.connect("notify::font-desc", self._on_font)
        self.font_reset = Gtk.Button(label=strings.LOCK_FONT_RESET, valign=Gtk.Align.CENTER)
        self.font_reset.connect("clicked", lambda *_: self._changed("font", ""))
        font_box = Gtk.Box(spacing=8)
        font_box.append(self.font_button)
        font_box.append(self.font_reset)
        self.font_row = font.add(Row(strings.LOCK_FONT, strings.LOCK_FONT_HINT,
                                     suffix=font_box, row_id="font"))
        self.rows["font"] = self.font_row
        control(font, "clock_size", "clock_size",
                Var("clock_size", "int", lk.DEFAULTS.clock_size, lo=lk.CLOCK_SIZE[0],
                    hi=lk.CLOCK_SIZE[1], step=4),
                strings.LOCK_CLOCK_SIZE, strings.LOCK_SIZE_HINT)
        control(font, "text_size", "text_size",
                Var("text_size", "int", lk.DEFAULTS.text_size, lo=lk.TEXT_SIZE[0],
                    hi=lk.TEXT_SIZE[1], step=1),
                strings.LOCK_TEXT_SIZE, strings.LOCK_SIZE_HINT)

        # ---- background
        back = self.add_group(Group(strings.LOCK_BACKGROUND))
        control(back, "blur", "blur",
                Var("blur", "int", lk.DEFAULTS.blur, lo=lk.BLUR[0], hi=lk.BLUR[1], step=1),
                strings.LOCK_BLUR, strings.LOCK_BLUR_HINT)
        control(back, "dim", "dim",
                Var("dim", "int", lk.DEFAULTS.dim, lo=lk.DIM[0], hi=lk.DIM[1], step=5,
                    unit="%"),
                strings.LOCK_DIM, strings.LOCK_DIM_HINT)

        # ---- apply
        apply = self.add_group(Group(strings.LOCK_APPLY_GROUP))
        self.apply_button = Gtk.Button(label=strings.LOCK_APPLY, valign=Gtk.Align.CENTER)
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", lambda *_: self._apply())
        self.rows["apply"] = apply.add(Row(strings.LOCK_APPLY_ROW, strings.LOCK_APPLY_HINT,
                                           suffix=self.apply_button, row_id="apply"))
        self.restore_button = Gtk.Button(label=strings.LOCK_RESTORE, valign=Gtk.Align.CENTER)
        self.restore_button.connect("clicked", lambda *_: self.lock.restore())
        self.restore_row = apply.add(Row(strings.LOCK_RESTORE_ROW, "",
                                         suffix=self.restore_button, row_id="restore"))
        self.rows["restore"] = self.restore_row
        self.restore_row.set_visible(False)

    def refresh(self) -> None:
        self.lock.refresh()

    def status(self, text: str) -> None:
        self.ctx.status(text)

    # ---- the controller's view -----------------------------------------------------

    def show_lock(self, info: lk.Info, options: lk.Options) -> None:
        if not info.found:
            state = strings.LOCK_STATE_NONE
        elif not info.ours or info.edited:
            state = strings.LOCK_STATE_HAND
        elif info.applied:
            state = strings.LOCK_STATE_OURS
        else:
            state = strings.LOCK_STATE_PENDING
        self.state_row.title_label.set_label(state)
        self._quiet = True
        try:
            for key, control in self.controls.items():
                if key not in self._settle:  # a number still moving keeps its place
                    control.set(getattr(options, key))
            self.theme_font = info.theme_font
            desc = Pango.FontDescription()
            desc.set_family(self._installed(options.font or info.theme_font))
            self.font_button.set_font_desc(desc)
        finally:
            self._quiet = False
        self.font_reset.set_sensitive(bool(options.font))
        self.apply_button.set_sensitive(info.colors)
        self.rows["apply"].subtitle_label.set_label(
            strings.LOCK_APPLY_HINT if info.colors else strings.LOCK_NO_COLORS)
        self.restore_row.set_visible(bool(info.backup))
        if info.backup:
            self.restore_row.subtitle_label.set_label(
                strings.LOCK_RESTORE_HINT.format(path=info.backup))
            self.restore_row.subtitle_label.set_visible(True)

    def show_preview(self, path: Path | None, error: str) -> None:
        if path is not None:
            try:
                self.picture.set_paintable(Gdk.Texture.new_from_filename(str(path)))
            except GLib.Error as exc:
                error = strings.LOCK_PREVIEW_FAILED.format(error=exc.message)
        self.picture_note.set_label(error)
        self.picture_note.set_visible(bool(error))
        # no picture at all yet (no simulator): no empty frame either
        self.picture.set_visible(self.picture.get_paintable() is not None)

    # ---- changes -----------------------------------------------------------------

    def _changed(self, key: str, value: Any) -> None:
        if self._quiet:
            return
        if key in ("clock_size", "text_size", "blur", "dim"):  # spin clicks settle first
            pending = self._settle.pop(key, None)
            if pending:
                GLib.source_remove(pending[0])
            self._settle[key] = (GLib.timeout_add(SETTLE_MS, self._settled, key, value), value)
            return
        self._set(key, value)

    def _settled(self, key: str, value: Any) -> bool:
        self._settle.pop(key, None)
        self._set(key, value)
        return False

    def _set(self, key: str, value: Any) -> None:
        """Into the draft; "Drawing…" under the picture only when a new one is coming."""
        before = self.lock.options
        self.lock.set(key, value)
        if self.lock.options != before and self.picture.get_visible():
            self.picture_note.set_label(strings.LOCK_PREVIEW_BUSY)
            self.picture_note.set_visible(True)

    def _apply(self) -> None:
        """Apply with every number still moving taken in first."""
        for key, (source, value) in list(self._settle.items()):
            GLib.source_remove(source)
            del self._settle[key]
            self.lock.set(key, value)
        self.lock.apply()

    def _installed(self, family: str) -> str:
        """family if the font button can name it, else "Sans" (not GTK's "None")."""
        names = {f.get_name().casefold()
                 for f in self.font_button.get_pango_context().get_font_map().list_families()}
        return family if family and family.casefold() in names else "Sans"

    def _on_font(self, button: Gtk.FontDialogButton, _pspec) -> None:
        if self._quiet:
            return
        desc = button.get_font_desc()
        family = desc.get_family() if desc is not None else ""
        if family and not (family == self.theme_font and not self.lock.options.font):
            self._changed("font", family)


PAGE = LockscreenPage
