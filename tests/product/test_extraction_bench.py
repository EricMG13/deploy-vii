"""The extraction benchmark's scorer, and the product extractor's baseline on it.

The baseline assertions pin what `pdf_content` does today on each failure class from probes 4-5.
A change to extraction that moves a number here is the measurement: update the pin with the
before/after in the change's review record.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from deploy_vii.contracts import Run
from deploy_vii.execution import Execution
from deploy_vii.preparation import PreparedPack, SourceRequest, prepare_source
from tests.product.extraction_bench import (
    continued,
    load_extractor,
    load_gold,
    main,
    pypdf_layout,
    score,
    synthetic_pdf,
    variant_journal,
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


def test_variant_journal_pack(tmp_path: Path) -> None:
    corpus = synthetic_pdf()
    pdf = tmp_path / "filing.pdf"
    pdf.write_bytes(corpus.raw)
    filing = prepare_source(
        SourceRequest(source_id="filing", path="filing.pdf", media_type="application/pdf"),
        corpus.raw,
    )
    other = prepare_source(
        SourceRequest(source_id="notes", path="notes.txt", media_type="text/plain"), b"Cash 0\n"
    )
    run = Run(
        run_id="bench",
        issuer_id="synthetic",
        issuer_name="Synthetic Issuer plc",
        as_of=date(2025, 12, 31),
        case_kind="synthetic",
    )
    base = Execution.create(tmp_path / "base", PreparedPack(run=run, sources=(filing, other)))
    truth = load_extractor("truth", corpus)
    digest = variant_journal(base.directory, tmp_path / "arm", pdf, "truth", truth)
    pack = Execution(tmp_path / "arm").pack()
    assert digest == Execution(tmp_path / "arm").read().pack_sha256 != base.read().pack_sha256
    variant, kept = pack.sources
    assert kept == other
    assert variant.sha256 == filing.sha256 and variant.extractor == "benchmark:truth"
    assert [span.text for span in variant.spans] == list(corpus.truth)
    assert [item.status for item in variant.coverage][-1] == "empty"
    stranger = tmp_path / "other.pdf"
    stranger.write_bytes(corpus.raw + b"\n")
    with pytest.raises(ValueError, match="matches no source"):
        variant_journal(base.directory, tmp_path / "none", stranger, "truth", truth)
    assert not (tmp_path / "none").exists()


def test_variant_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus = synthetic_pdf()
    pdf = tmp_path / "filing.pdf"
    pdf.write_bytes(corpus.raw)
    filing = prepare_source(
        SourceRequest(source_id="filing", path="filing.pdf", media_type="application/pdf"),
        corpus.raw,
    )
    run = Run(
        run_id="bench",
        issuer_id="synthetic",
        issuer_name="Synthetic Issuer plc",
        as_of=date(2025, 12, 31),
        case_kind="synthetic",
    )
    base = Execution.create(tmp_path / "base", PreparedPack(run=run, sources=(filing,)))
    argv = ["variant", "--base", str(base.directory), "--out", str(tmp_path / "arm")]
    assert main([*argv, "--pdf", str(pdf), "--extractor", "pypdf-layout"]) == 0
    assert "variant pack" in capsys.readouterr().out
    # The product extractor reproduces the base pack's spans exactly.
    assert Execution(tmp_path / "arm").pack().sources[0].spans == filing.spans
