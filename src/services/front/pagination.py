from __future__ import annotations


def parse_positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default


def parse_per_page(value, default: int) -> int:
    parsed = parse_positive_int(value, default)
    return min(max(parsed, 10), 100)


def total_pages(total: int, per_page: int) -> int:
    return per_page and (total + per_page - 1) // per_page or 0


def build_page_items(total_pages: int, page: int, window: int = 2) -> list[int | None]:
    if total_pages <= 1:
        return []
    pages = set(range(max(1, page - window), min(total_pages, page + window) + 1))
    pages.add(1)
    pages.add(total_pages)
    ordered = sorted(pages)
    items: list[int | None] = []
    previous = 0
    for p in ordered:
        if p - previous > 1:
            items.append(None)
        items.append(p)
        previous = p
    return items
