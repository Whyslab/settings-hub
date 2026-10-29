"""Pages of the window. Each module defines PAGE, a base.Page subclass.

Pages are built lazily, on first visit (or by the idle prebuild after start).
"""

from __future__ import annotations

import importlib

from .. import registry
from .base import Context, Page


def create(page_id: str, ctx: Context) -> Page:
    info = registry.get(page_id)
    if info is None:
        raise KeyError(page_id)
    module = importlib.import_module(f"{__name__}.{info.module}")
    return module.PAGE(page_id, ctx)


__all__ = ["Context", "Page", "create"]
