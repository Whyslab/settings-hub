"""Backends: the only code that calls into other projects.

Each backend wraps one source of settings (screen-sleep's config.json, the
wallpaper and theme CLIs, the animations module, the binds block) and offers a
history.Applier -- read(keys) / apply(values) -- that the window registers with
History under the backend's name (see strings.BACKENDS for the names).
Slow applies go through workers.Workers, one thread per backend.
"""
