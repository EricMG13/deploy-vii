"""The extraction benchmark's scorer, and the product extractor's baseline on it.

The baseline assertions pin what `pdf_content` does today on each failure class from probes 4-5.
A change to extraction that moves a number here is the measurement: update the pin with the
before/after in the change's review record.
"""

import json
from pathlib import Path

from tests.product.extraction_bench import (
    continued,
    load_extractor,
    load_gold,
    main,
    pypdf_layout,
    score,
    synthetic_pdf,
)

GOLD = Path(__file__).parent / "fixtures" / "extraction-gold-probe-filing.json"


def test_truth_passes_everything_it_can_see() -> None:
    corpus = synthetic_pdf()
    result = score(
        "truth", load_extractor("truth", corpus), corpus.raw, corpus.gold, corpus.artifacts
    )
    failed = {gold_id for gold_id, ok in result.passed.items() if not ok}
    # The image has no text layer, and a straddling quote is on no single page.
    assert failed == {"image-kpi", "straddle"}
    assert result.passed_joined == {"straddle": True}
    assert result.artifacts_found == []
    assert result.empty_pages == 1


def test_pypdf_layout_baseline() -> None:
    corpus = synthetic_pdf()
    truth = score("truth", load_extractor("truth", corpus), corpus.raw, corpus.gold)
    result = score("pypdf-layout", pypdf_layout, corpus.raw, corpus.gold, corpus.artifacts)
    assert result.by_category == {
        "column_prose": "0/2",  # lines of both columns interleave
        "column_table": "0/2",  # the p102/p104 exhibit stitch
        "financial_rows": "2/2",
        "hyphen_wrap": "1/1",  # task 2.10 matcher
        "ocr": "0/1",
        "page_straddle": "0/1",
    }
    assert result.passed_joined == {"straddle": True}
    assert result.artifacts_found == ["futureremaining"]
    assert result.empty_pages == 1
    # Layout whitespace inflates what the model reads.
    assert result.estimated_tokens > 1.4 * truth.estimated_tokens
    assert result.whitespace_share > 0.4


def test_synthetic_pdf_is_deterministic() -> None:
    assert synthetic_pdf().raw == synthetic_pdf().raw


def test_continued_needs_the_prefix_to_end_the_first_page() -> None:
    quote = "cash uses include capital expenditures."
    assert continued(
        quote, "Page 4\nOther uses: cash uses include", "Header\ncapital expenditures."
    )
    assert not continued(quote, "cash uses include more text", "capital expenditures.")
    assert not continued(quote, "cash uses include", "x" * 400 + " capital expenditures.")


def test_probe_filing_gold_loads() -> None:
    gold, artifacts = load_gold(GOLD)
    assert len({item.gold_id for item in gold}) == len(gold) > 0
    assert all(item.pages and all(page > 0 for page in item.pages) for item in gold)
    assert artifacts == ("futureremaining",)


def test_cli_writes_results(tmp_path: Path) -> None:
    out = tmp_path / "results.json"
    assert main(["--extractor", "pypdf-layout", "--extractor", "truth", "--json", str(out)]) == 0
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert [row["extractor"] for row in rows] == ["pypdf-layout", "truth"]
