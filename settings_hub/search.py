"""Search over pages and their rows. No GTK.

Case-insensitive, treats the Russian "yo" as "ye", and also tries the query as if it had been
typed in the wrong keyboard layout (QWERTY <-> the Russian JCUKEN), so "cjy"
finds the same as the Russian word for "sleep" typed with the Russian layout.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import registry, strings

_EN_TO_RU = str.maketrans(
    strings.LAYOUT_EN + strings.LAYOUT_EN_SHIFTED, strings.LAYOUT_RU + strings.LAYOUT_RU_SHIFTED
)
_RU_TO_EN = str.maketrans(strings.LAYOUT_RU, strings.LAYOUT_EN)


def normalize(text: str) -> str:
    return " ".join(text.casefold().replace(strings.YO, strings.YE).split())


def to_russian_layout(text: str) -> str:
    """What the keys would have typed with the Russian layout on."""
    return text.casefold().translate(_EN_TO_RU)


def to_english_layout(text: str) -> str:
    """What the keys would have typed with the US layout on."""
    return text.casefold().translate(_RU_TO_EN)


@dataclass(frozen=True)
class Result:
    page_id: str
    row_id: str | None
    score: int
    title: str
    row_title: str | None = None


@dataclass(frozen=True)
class _Entry:
    page_id: str
    row_id: str | None
    title: str  # normalised label of the page or row
    keywords: tuple[str, ...]  # normalised
    order: int


def _build_index() -> list[_Entry]:
    entries = []
    for order, page in enumerate(registry.PAGES):
        entries.append(_Entry(
            page.id, None, normalize(registry.title(page.id)),
            tuple(normalize(k) for k in registry.keywords(page.id)), order,
        ))
        for row_id, (label, words) in registry.rows(page.id).items():
            entries.append(_Entry(
                page.id, row_id, normalize(label),
                tuple(normalize(k) for k in words), order,
            ))
    return entries


def _score(entry: _Entry, query: str) -> int:
    """0 means no match. Every query word must match somewhere in the entry."""
    words = query.split()
    if not words:
        return 0
    title_words = entry.title.split()
    keyword_words = [w for k in entry.keywords for w in k.split()]
    haystack = " ".join((entry.title, *entry.keywords))
    total = 0
    for word in words:
        if any(w.startswith(word) for w in title_words):
            total += 80
        elif any(w.startswith(word) for w in keyword_words):
            total += 60
        elif word in haystack:
            total += 40
        else:
            return 0
    score = total // len(words)
    if entry.title.startswith(query):
        score += 20
    if entry.row_id is not None:
        score -= 5  # a page outranks one of its rows on a tie
    return score


class Index:
    def __init__(self) -> None:
        self._entries = _build_index()

    def search(self, text: str, limit: int = 20) -> list[Result]:
        raw = text.strip()
        if not raw:
            return []
        variants = [(normalize(raw), 0)]
        for converted in (to_russian_layout(raw), to_english_layout(raw)):
            norm = normalize(converted)
            if norm and norm not in (v for v, _ in variants):
                variants.append((norm, 1))  # small penalty: the layout was a guess
        best: dict[tuple[str, str | None], tuple[int, _Entry]] = {}
        for query, penalty in variants:
            for entry in self._entries:
                score = _score(entry, query)
                if score <= 0:
                    continue
                score -= penalty
                key = (entry.page_id, entry.row_id)
                if key not in best or best[key][0] < score:
                    best[key] = (score, entry)
        ranked = sorted(best.values(), key=lambda se: (-se[0], se[1].order, se[1].row_id or ""))
        results = []
        for score, entry in ranked[:limit]:
            row_title = registry.rows(entry.page_id)[entry.row_id][0] if entry.row_id else None
            results.append(Result(
                entry.page_id, entry.row_id, score, registry.title(entry.page_id), row_title,
            ))
        return results


_default: Index | None = None


def search(text: str, limit: int = 20) -> list[Result]:
    global _default
    if _default is None:
        _default = Index()
    return _default.search(text, limit)
