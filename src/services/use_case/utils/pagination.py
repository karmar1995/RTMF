from __future__ import annotations

from collections.abc import Sequence


def paginate(
    items: Sequence,
    page: int,
    per_page: int,
) -> tuple[Sequence, int]:
    total = len(items)
    if per_page <= 0:
        return items, total
    start = max(0, (page - 1) * per_page)
    return items[start : start + per_page], total
