"""Fetch the public policy corpus and extract its text, with provenance.

The corpus is four states' fee-for-service provider manuals, downloaded from the payers'
own sites. Each document is stored as the original PDF, its extracted text with page
markers, and a manifest row (source URL, sha256, fetch date, page count) so an index and an
eval run can say exactly which version of which document they used (ADR-017).

Everything downloaded here is third-party text and is untrusted from this point on
(ADR-020): it is data for retrieval, never instruction. Extraction is pypdf, nothing
smarter; the section-aware chunker works on the numbered headings these manuals carry.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader

PAGE_MARKER = "\n\n<<page {n}>>\n\n"


@dataclass(frozen=True)
class Source:
    id: str
    payer: str
    title: str
    url: str


# Public documents only. Cited in reference/payers.json and docs/notes/2026-11-11-research.md.
SOURCES: tuple[Source, ...] = (
    Source(
        "ut-section-1",
        "UT",
        "Utah Medicaid Provider Manual, Section I: General Information",
        "https://medicaid.utah.gov/Documents/manuals/pdfs/Medicaid%20Provider%20Manuals/"
        "All%20Providers%20General%20Information%20Section%20I/AllProvidersGeneralInfo_Section_1.pdf",
    ),
    Source(
        "az-ffs-ch04",
        "AZ",
        "AHCCCS FFS Provider Billing Manual, Chapter 4: General Billing Rules",
        "https://azahcccs.gov/PlansProviders/Downloads/FFSProviderManual/FFS_Chap04GeneralBillingRules.pdf",
    ),
    Source(
        "az-ffs-ch28",
        "AZ",
        "AHCCCS FFS Provider Billing Manual, Chapter 28: Claim Disputes",
        "https://azahcccs.gov/PlansProviders/Downloads/FFSProviderManual/FFS_Chap28ClaimDisputes.pdf",
    ),
    Source(
        "nv-billing-manual",
        "NV",
        "Nevada Medicaid and Nevada Check Up Billing Manual (02/20/2026)",
        "https://www.medicaid.nv.gov/Downloads/provider/NV_Billing_General_20260220.pdf",
    ),
    Source(
        "id-general-billing",
        "ID",
        "Idaho Medicaid Provider Handbook: General Billing Instructions",
        "https://www.idmedicaid.com/General%20Information/General%20Billing%20Instructions.pdf",
    ),
)


@dataclass(frozen=True)
class CorpusDocument:
    id: str
    payer: str
    title: str
    url: str
    sha256: str
    fetched_at: str
    pages: int
    chars: int


def pages_to_text(pages: list[str]) -> str:
    """Join page texts with a marker a chunker can keep, so a citation can name a page."""
    return "".join(PAGE_MARKER.format(n=i + 1) + (page or "") for i, page in enumerate(pages))


def extract(pdf_path: Path) -> list[str]:
    reader = PdfReader(str(pdf_path))
    return [page.extract_text() or "" for page in reader.pages]


def fetch(source: Source, out_dir: Path) -> CorpusDocument:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{source.id}.pdf"
    if not pdf_path.exists():
        with urllib.request.urlopen(source.url, timeout=60) as resp:
            pdf_path.write_bytes(resp.read())
    pages = extract(pdf_path)
    text = pages_to_text(pages)
    (out_dir / f"{source.id}.txt").write_text(text)
    return CorpusDocument(
        id=source.id,
        payer=source.payer,
        title=source.title,
        url=source.url,
        sha256=hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
        pages=len(pages),
        chars=len(text),
    )


def fetch_corpus(out_dir: Path, sources: tuple[Source, ...] = SOURCES) -> list[CorpusDocument]:
    """Download (once; existing PDFs are kept) and extract every source; write the manifest."""
    docs = [fetch(source, out_dir) for source in sources]
    manifest = {"fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "documents": [asdict(d) for d in docs]}  # fmt: skip
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return docs
