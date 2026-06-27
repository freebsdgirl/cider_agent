"""Small, dependency-free helpers shared across the service and session layers.

These were previously defined as private helpers in :mod:`vesper.service` and
imported from there by the session modules, which created a circular import
with :class:`vesper.service.CiderAgentService` (issue #44). Moving them here
breaks that cycle: :mod:`vesper.session` and its mixins import from this module
instead of ``vesper.service``, and ``vesper.service`` itself imports them from
here as well.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote


def _elapsed_ms(start: float) -> float:
    """Elapsed time in milliseconds since *start* (a ``perf_counter`` value)."""
    return round((time.perf_counter() - start) * 1000.0, 2)


def _encode_query(query: str) -> str:
    """URL-encode a query term with no safe characters."""
    return quote(query, safe="")


def _clean_id(value: Any) -> str:
    """Normalize an id-like value to a stripped string.

    ``None`` (and the literal string ``"none"``) collapse to the empty string so
    callers can treat missing ids uniformly.
    """
    if value is None:
        return ""
    cleaned = str(value).strip()
    return "" if cleaned.lower() == "none" else cleaned
