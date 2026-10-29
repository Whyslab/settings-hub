"""Search: case, the yo/ye letter, wrong keyboard layout, page -> row results."""

import pytest
from conftest import load_json

from settings_hub import search

CASES = load_json("search_cases.json")


@pytest.mark.parametrize("case", CASES["find"], ids=lambda c: c["query"])
def test_query_finds_page_first(case):
    results = search.search(case["query"])
    assert results, f"nothing found for {case['query']!r}"
    assert results[0].page_id == case["page"]


@pytest.mark.parametrize("case", CASES["rows"], ids=lambda c: c["query"])
def test_query_finds_row(case):
    results = search.search(case["query"])
    hits = [(r.page_id, r.row_id) for r in results]
    assert (case["page"], case["row"]) in hits
    row = next(r for r in results if r.row_id == case["row"])
    assert row.row_title  # "Page -> row" needs the row's label
    assert row.title


@pytest.mark.parametrize("query", CASES["nothing"])
def test_unknown_or_blank_finds_nothing(query):
    assert search.search(query) == []


@pytest.mark.parametrize("pair", CASES["layout"], ids=lambda p: p["en"])
def test_layout_conversion(pair):
    assert search.to_russian_layout(pair["en"]) == pair["ru"]
    if not set(pair["en"]) & set('~{}:"<>'):  # shifted keys convert one way only
        assert search.to_english_layout(pair["ru"]) == pair["en"]


def test_normalize_treats_yo_as_ye_and_ignores_case():
    yo = CASES["yo"]
    assert search.normalize(yo["with"]) == yo["without"]


def test_layout_guess_ranks_below_exact_match():
    exact = search.search(CASES["find"][0]["query"])[0]
    guessed = search.search("cjy")[0]
    assert exact.page_id == guessed.page_id
    assert guessed.score < exact.score


def test_results_are_unique_and_limited():
    everything = search.search(CASES["broad"])
    assert len(everything) > 3
    assert len(search.search(CASES["broad"], limit=3)) == 3
    keys = [(r.page_id, r.row_id) for r in everything]
    assert len(keys) == len(set(keys))
