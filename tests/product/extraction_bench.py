"""Offline extraction benchmark: does a PDF extractor let a correctly copied citation pass?

Live probes 4 and 5 rejected citations mostly for extraction reasons, not reasoning ones: a
two-column exhibit table read across its columns (p102/p104), a sentence that crosses a page
break (p43/44, p76/77), merged headings and layout whitespace that inflate the prompt. This
module measures an extractor against those failure classes without any model call (US$0):

- `synthetic_pdf()` builds a deterministic PDF, one page per class, with its gold quotes and the
  artifact strings that must not appear. Every text page carries a running header; the
  image-only page has no text layer at all, as a scan has none.
- `score()` renders each page as the prompt does (`locator=page:N | <text>`) and checks every
  gold quote with `deploy_vii.quotes.quoted`, the matcher the validator holds models to, on the
  page its locator names. A quote that crosses a page break is also checked with `continued`,
  which measures a validator rule that accepts a continuation onto the next page.
- Extractors are `bytes -> per-page texts`. `pypdf-layout` is the product path (`pdf_content`);
  `truth` returns the builder's own text and proves the scorer (it must pass everything but
  nothing it cannot see). `pdftotext` (poppler's reading order, a system tool), `docling` and
  any `module:function` load lazily, so a candidate runs without entering the lock:
  `uv run --locked --with docling python -m tests.product.extraction_bench --extractor docling`.

`variant --base JOURNAL --out JOURNAL --pdf FILE --extractor NAME` writes a copy of an execution
journal whose PDF source is re-extracted, so `make live-probe DIRECTORY=<out>` runs arm L1 of the
live A/B probe against the unchanged base journal (arm L0).

`--pdf FILE --gold FILE` scores a real filing instead (kept outside Git); the probe filing's
gold quotes are in `tests/product/fixtures/extraction-gold-probe-filing.json`. Size is reported
as rendered characters and an estimate of tokens (characters / 4, labelled as an estimate);
the live A/B probe in `docs/development/tasks/implementation/extraction-benchmark-brief.md`
measures real tokens and latency.
"""

import argparse
import hashlib
import importlib
import io
import json
import subprocess
import sys
import tempfile
import time
import zlib
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    StreamObject,
)

from deploy_vii.contracts import Coverage, Span
from deploy_vii.execution import Execution
from deploy_vii.preparation import PreparedPack, pdf_content
from deploy_vii.quotes import normalise, quoted

Extractor = Callable[[bytes], Sequence[str]]
WIDTH, HEIGHT = 612, 792
HEADER = "Synthetic Issuer plc - Annual Report and Lender Presentation 2025"


@dataclass(frozen=True)
class Gold:
    """A verbatim quote a careful model would copy, and the page(s) it sits on."""

    gold_id: str
    category: str
    quote: str
    pages: tuple[int, ...]


@dataclass(frozen=True)
class Corpus:
    raw: bytes
    gold: tuple[Gold, ...]
    artifacts: tuple[str, ...] = ()
    truth: tuple[str, ...] = ()  # reading-order text per page; image text is not visible


@dataclass
class Result:
    extractor: str
    seconds: float
    pages: int
    empty_pages: int
    rendered_chars: int
    estimated_tokens: int
    whitespace_share: float
    passed: dict[str, bool] = field(default_factory=dict)
    passed_joined: dict[str, bool] = field(default_factory=dict)
    by_category: dict[str, str] = field(default_factory=dict)
    artifacts_found: list[str] = field(default_factory=list)


# --- synthetic corpus -------------------------------------------------------------------------


def _pdf_string(text: str) -> str:
    return "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


@dataclass
class _Page:
    runs: list[tuple[float, float, float, str]] = field(default_factory=list)  # x, y, size, text
    reading: list[str] = field(default_factory=list)
    image: tuple[int, int, bytes, tuple[float, float, float, float]] | None = None

    def text(self, x: float, y: float, text: str, size: float = 10) -> None:
        self.runs.append((x, y, size, text))


# 5x7 glyphs for the image-only page (no imaging dependency); "#" is ink.
_GLYPHS = {
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "I": (".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    ",": (".....", ".....", ".....", ".....", ".##..", "..#..", ".#..."),
    " ": (".....",) * 7,
}


def _raster(text: str, scale: int = 6) -> tuple[int, int, bytes]:
    """Black-on-white 8-bit greyscale pixels for `text`, `scale` pixels per glyph dot."""
    cols, rows = 6 * len(text) + 1, 9
    dots = [[False] * cols for _ in range(rows)]
    for index, char in enumerate(text):
        for r, row in enumerate(_GLYPHS[char]):
            for c, dot in enumerate(row):
                dots[r + 1][index * 6 + 1 + c] = dot == "#"
    lines = []
    for row in dots:
        line = bytes(0 if ink else 255 for ink in row for _ in range(scale))
        lines.extend([line] * scale)
    return cols * scale, rows * scale, b"".join(lines)


def _pages() -> tuple[list[_Page], list[Gold], list[str]]:
    pages: list[_Page] = []
    gold: list[Gold] = []

    # 1. Financial table: labels, two period columns, bracketed negatives.
    page = _Page()
    page.text(72, 700, "Consolidated statement of operations (USD millions)", 12)
    rows = [
        ("", "FY2025", "FY2024"),
        ("Net revenues", "11,245", "11,528"),
        ("Adjusted EBITDA", "3,612", "3,741"),
        ("Interest expense, net", "(2,341)", "(2,301)"),
        ("Net loss", "(278)", "(1,234)"),
    ]
    for i, (label, fy25, fy24) in enumerate(rows):
        y = 670 - 18 * i
        page.text(72, y, label)
        page.text(400, y, fy25)
        page.text(480, y, fy24)
        page.reading.append(" ".join(item for item in (label, fy25, fy24) if item))
    pages.append(page)
    gold += [
        Gold("table-net-loss", "financial_rows", "Net loss (278) (1,234)", (1,)),
        Gold("table-interest", "financial_rows", "Interest expense, net (2,341) (2,301)", (1,)),
    ]

    # 2. Two-column exhibit table whose cells wrap over different numbers of lines (p102/p104).
    page = _Page()
    page.text(72, 700, "Exhibit index", 12)
    left = [
        "Indenture, dated as of September 18, 2023,",
        "among the Company, the guarantors party",
        "thereto and the trustee.",
    ]
    right = ["Previously filed on Form 8-K filed", "on September 27, 2021."]
    for i, line in enumerate(left):
        page.text(72, 670 - 14 * i, line)
    for i, line in enumerate(right):
        page.text(330, 670 - 14 * i, line)
    page.reading += [" ".join(left), " ".join(right)]
    pages.append(page)
    gold += [
        Gold(
            "exhibit-left",
            "column_table",
            "Indenture, dated as of September 18, 2023, among the Company, the guarantors "
            "party thereto and the trustee.",
            (2,),
        ),
        Gold(
            "exhibit-right",
            "column_table",
            "Previously filed on Form 8-K filed on September 27, 2021.",
            (2,),
        ),
    ]

    # 3. Two-column prose, the annual-report and lender-deck pattern.
    page = _Page()
    left = [
        "Liquidity remained strong: the revolving",
        "credit facility was undrawn at year end",
        "and total liquidity was $1.9 billion.",
    ]
    right = [
        "Net leverage fell to 4.1x from 4.6x as",
        "Adjusted EBITDA grew and term loans",
        "were repaid from disposal proceeds.",
    ]
    for i, (a, b) in enumerate(zip(left, right, strict=True)):
        page.text(72, 680 - 14 * i, a)
        page.text(330, 680 - 14 * i, b)
    page.reading += [" ".join(left), " ".join(right)]
    pages.append(page)
    gold += [
        Gold("prose-left", "column_prose", " ".join(left), (3,)),
        Gold("prose-right", "column_prose", " ".join(right), (3,)),
    ]

    # 4-5. A sentence that starts at the foot of one page and ends at the top of the next.
    first, second = _Page(), _Page()
    first.text(72, 90, "Uses of cash flows that are not reflected in Adjusted EBITDA include")
    second.text(72, 700, "capital expenditures, interest payments and lease obligations.")
    first.reading.append("Uses of cash flows that are not reflected in Adjusted EBITDA include")
    second.reading.append("capital expenditures, interest payments and lease obligations.")
    pages += [first, second]
    gold.append(
        Gold(
            "straddle",
            "page_straddle",
            "Uses of cash flows that are not reflected in Adjusted EBITDA include capital "
            "expenditures, interest payments and lease obligations.",
            (4, 5),
        )
    )

    # 6. A hyphenated line wrap (p135) and a heading pair set flush against each other (p99).
    page = _Page()
    page.text(72, 700, "Amended and Restated PUT-")
    page.text(72, 686, "CALL RIGHT AGREEMENT, dated as of July 20, 2024.")
    page.text(72, 640, "available for future", 9)
    page.text(145, 640, "remaining", 9)  # overlaps "future" slightly, as merged headings do
    page.reading += [
        "Amended and Restated PUT-CALL RIGHT AGREEMENT, dated as of July 20, 2024.",
        "available for future remaining",
    ]
    pages.append(page)
    gold.append(Gold("hyphen-wrap", "hyphen_wrap", "PUT-CALL RIGHT AGREEMENT", (6,)))

    # 7. Image-only page (a scanned or flattened slide): only OCR or a vision model sees it.
    page = _Page()
    width, height, pixels = _raster("EBITDA 1,234")
    page.image = (width, height, pixels, (72, 600, width * 0.5, height * 0.5))
    pages.append(page)
    gold.append(Gold("image-kpi", "ocr", "EBITDA 1,234", (7,)))

    return pages, gold, ["futureremaining"]


def synthetic_pdf() -> Corpus:
    """The benchmark PDF, its gold quotes, forbidden artifacts and per-page reading text."""
    pages, gold, artifacts = _pages()
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }
    )
    truth = []
    for number, spec in enumerate(pages, 1):
        page = writer.add_blank_page(width=WIDTH, height=HEIGHT)
        resources = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        header = "" if spec.image is not None else f"{HEADER}    Page {number}"
        parts = [f"BT /F1 8 Tf 72 760 Td {_pdf_string(header)} Tj ET"] if header else []
        parts += [
            f"BT /F1 {size:g} Tf {x:g} {y:g} Td {_pdf_string(text)} Tj ET"
            for x, y, size, text in spec.runs
        ]
        if spec.image is not None:
            width, height, pixels, (x, y, w, h) = spec.image
            image = StreamObject()
            image._data = zlib.compress(pixels)
            image.update(
                {
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Image"),
                    NameObject("/Width"): NumberObject(width),
                    NameObject("/Height"): NumberObject(height),
                    NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                    NameObject("/BitsPerComponent"): NumberObject(8),
                    NameObject("/Filter"): ArrayObject([NameObject("/FlateDecode")]),
                }
            )
            resources[NameObject("/XObject")] = DictionaryObject(
                {NameObject("/Im1"): writer._add_object(image)}
            )
            parts.append(f"q {w:g} 0 0 {h:g} {x:g} {y:g} cm /Im1 Do Q")
        page[NameObject("/Resources")] = resources
        content = DecodedStreamObject()
        content.set_data("\n".join(parts).encode("cp1252"))
        page[NameObject("/Contents")] = writer._add_object(content)
        truth.append("\n".join(line for line in (header, *spec.reading) if line))
    output = io.BytesIO()
    writer.write(output)
    return Corpus(output.getvalue(), tuple(gold), tuple(artifacts), tuple(truth))


# --- extractors -------------------------------------------------------------------------------


def pypdf_layout(raw: bytes) -> list[str]:
    """The product path: `deploy_vii.preparation.pdf_content`, one text per page."""
    extraction = pdf_content(raw)
    texts = {span.locator: span.text for span in extraction.spans}
    return [texts.get(item.locator, "") for item in extraction.coverage]


def pdftotext(raw: bytes) -> list[str]:  # pragma: no cover - needs poppler on PATH
    """Poppler's reading-order mode (no `-layout`): a system tool, no model, no lock entry."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "source.pdf"
        path.write_bytes(raw)
        output = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    return output.split("\f")[:-1] if output.endswith("\f") else output.split("\f")


def docling(raw: bytes) -> list[str]:  # pragma: no cover - optional, outside the lock
    """Docling's Markdown, one export per page (needs `--with docling` and its model files)."""
    from docling.datamodel.base_models import DocumentStream
    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(DocumentStream(name="source.pdf", stream=io.BytesIO(raw)))
    document = result.document
    return [document.export_to_markdown(page_no=n) for n in range(1, len(document.pages) + 1)]


def load_extractor(name: str, corpus: Corpus | None = None) -> Extractor:
    if name == "pypdf-layout":
        return pypdf_layout
    if name == "docling":
        return docling
    if name == "pdftotext":
        return pdftotext
    if name == "truth":
        if corpus is None or not corpus.truth:
            raise ValueError("truth needs the synthetic corpus")
        texts = list(corpus.truth)
        return lambda _raw: texts
    module, _, function = name.partition(":")
    if not function:
        raise ValueError(
            f"unknown extractor {name!r}: use pypdf-layout, truth, pdftotext, docling or "
            "module:function"
        )
    extractor: Extractor = getattr(importlib.import_module(module), function)
    return extractor


# --- scoring ----------------------------------------------------------------------------------


def render(texts: Sequence[str]) -> str:
    """Pages as the prompt renders spans (`deploy_vii.live.prompts._source_body`)."""
    return "\n".join(f"locator=page:{n} | {text}" for n, text in enumerate(texts, 1))


def continued(quote: str, first: str, second: str, window: int = 300) -> bool:
    """A candidate validator rule for a quote that crosses a page break: some prefix of it
    ends the first page and the rest sits within the first `window` normalised characters of
    the next (room for a running header). Not the product rule; it measures what one would buy."""
    needle, tail, head = normalise(quote), normalise(first), normalise(second)[:window]
    return any(
        tail.endswith(needle[:cut].rstrip()) and needle[cut:].strip() in head
        for cut in range(1, len(needle))
        if needle[cut - 1] == " "
    )


def score(
    name: str, extractor: Extractor, raw: bytes, gold: Sequence[Gold], artifacts: Sequence[str] = ()
) -> Result:
    started = time.perf_counter()
    texts = list(extractor(raw))
    seconds = time.perf_counter() - started
    body = render(texts)
    result = Result(
        extractor=name,
        seconds=round(seconds, 3),
        pages=len(texts),
        empty_pages=sum(1 for text in texts if not text.strip()),
        rendered_chars=len(body),
        estimated_tokens=-(-len(body) // 4),
        whitespace_share=round(sum(c.isspace() for c in body) / max(len(body), 1), 3),
    )

    def page(n: int) -> str:
        return texts[n - 1] if 0 < n <= len(texts) else ""

    for item in gold:
        result.passed[item.gold_id] = quoted(item.quote, page(item.pages[0]))
        if len(item.pages) == 2:
            result.passed_joined[item.gold_id] = continued(item.quote, *map(page, item.pages))
    for category in sorted({item.category for item in gold}):
        ids = [item.gold_id for item in gold if item.category == category]
        result.by_category[category] = f"{sum(result.passed[i] for i in ids)}/{len(ids)}"
    result.artifacts_found = [a for a in artifacts if a in body]
    return result


def load_gold(path: Path) -> tuple[tuple[Gold, ...], tuple[str, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    gold = tuple(
        Gold(item["id"], item["category"], item["quote"], tuple(item["pages"]))
        for item in data["gold"]
    )
    return gold, tuple(data.get("artifacts", ()))


def table(results: Sequence[Result]) -> str:
    categories = sorted({c for r in results for c in r.by_category})
    head = [
        "extractor",
        "s",
        "est. tokens",
        "whitespace",
        "empty pages",
        *categories,
        "straddle joined",
        "artifacts",
    ]
    lines = ["| " + " | ".join(head) + " |", "|" + " --- |" * len(head)]
    for r in results:
        joined = f"{sum(r.passed_joined.values())}/{len(r.passed_joined)}"
        cells = [
            r.extractor,
            f"{r.seconds:g}",
            str(r.estimated_tokens),
            f"{r.whitespace_share:.0%}",
            f"{r.empty_pages}/{r.pages}",
            *(r.by_category.get(c, "-") for c in categories),
            joined,
            ", ".join(r.artifacts_found) or "none",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def variant_journal(base: Path, out: Path, pdf: Path, name: str, extractor: Extractor) -> str:
    """A new execution journal: `base`'s pack with the source whose hash is `pdf`'s re-extracted
    by `extractor`, for a live A/B probe arm. Locators stay `page:N`, so the validator holds the
    arm to its own text. Returns the variant pack's content hash."""
    raw = pdf.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    pack = Execution(base).pack()
    if not any(source.sha256 == digest for source in pack.sources):
        raise ValueError(f"{pdf} matches no source in {base}: hash {digest}")
    texts = list(extractor(raw))
    spans = tuple(Span(locator=f"page:{n}", text=text) for n, text in enumerate(texts, 1))
    coverage = tuple(
        Coverage(
            locator=span.locator,
            status="retained" if span.text.strip() else "empty",
            limitation=None if span.text.strip() else "No extractable text",
        )
        for span in spans
    )
    sources = tuple(
        source.model_copy(
            update={
                "spans": spans,
                "coverage": coverage,
                "extractor": f"benchmark:{name}",
                "extraction_status": "degraded",
                "limitation": f"Benchmark variant: page text from {name}, not the product "
                "extractor; fidelity review still applies.",
            }
        )
        if source.sha256 == digest
        else source
        for source in pack.sources
    )
    variant = PreparedPack.model_validate_json(
        pack.model_copy(update={"sources": sources}).model_dump_json()
    )
    return Execution.create(out, variant).read().pack_sha256


def variant_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="extraction_bench variant",
        description="Write a probe journal whose PDF source is re-extracted (live A/B arm).",
    )
    parser.add_argument("--base", type=Path, required=True, help="existing execution journal")
    parser.add_argument("--out", type=Path, required=True, help="new journal directory")
    parser.add_argument("--pdf", type=Path, required=True, help="the source's original bytes")
    parser.add_argument("--extractor", required=True, help="as for the benchmark")
    args = parser.parse_args(argv)
    base_hash = Execution(args.base).read().pack_sha256
    variant_hash = variant_journal(
        args.base, args.out, args.pdf, args.extractor, load_extractor(args.extractor)
    )
    print(f"base pack {base_hash}\nvariant pack {variant_hash} ({args.extractor}) at {args.out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["variant"]:
        return variant_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--extractor",
        action="append",
        default=None,
        help="pypdf-layout (default), truth, pdftotext, docling or module:function; repeat",
    )
    parser.add_argument("--pdf", type=Path, help="score this PDF instead of the synthetic one")
    parser.add_argument("--gold", type=Path, help="gold quotes for --pdf")
    parser.add_argument("--json", type=Path, help="also write the results here")
    args = parser.parse_args(argv)
    if (args.pdf is None) != (args.gold is None):
        parser.error("--pdf and --gold go together")
    if args.pdf is not None:
        corpus = Corpus(args.pdf.read_bytes(), *load_gold(args.gold))
    else:
        corpus = synthetic_pdf()
    names = args.extractor or ["pypdf-layout"]
    results = [
        score(n, load_extractor(n, corpus), corpus.raw, corpus.gold, corpus.artifacts)
        for n in names
    ]
    print(table(results))
    for r in results:
        failed = [i for i, ok in r.passed.items() if not ok]
        print(f"\n{r.extractor}: failed {', '.join(failed) or 'none'}")
    if args.json is not None:
        args.json.write_text(
            json.dumps([asdict(r) for r in results], indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
