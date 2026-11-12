"""Corpus plumbing without the network: page markers and the manifest shape."""

from pathlib import Path

import pytest

from denial_desk.retrieval.corpus import SOURCES, Source, fetch_corpus, pages_to_text


def test_page_markers_let_a_citation_name_a_page() -> None:
    text = pages_to_text(["1.12 Timely Filing Limit", "", "1.13 Fees"])
    assert "<<page 1>>" in text and "<<page 3>>" in text
    assert text.index("1.12") < text.index("<<page 2>>") < text.index("1.13")


def test_sources_are_public_pdfs_for_the_four_payers() -> None:
    assert {s.payer for s in SOURCES} == {"UT", "AZ", "NV", "ID"}
    assert all(s.url.startswith("https://") and s.url.lower().endswith(".pdf") for s in SOURCES)
    assert len({s.id for s in SOURCES}) == len(SOURCES)


@pytest.mark.integration
def test_fetch_one_document(tmp_path: Path) -> None:
    source = next(s for s in SOURCES if s.id == "az-ffs-ch28")
    [doc] = fetch_corpus(tmp_path, (source,))
    assert doc.pages > 0 and "Claim Disputes" in (tmp_path / "az-ffs-ch28.txt").read_text()


def test_fetch_corpus_writes_a_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import denial_desk.retrieval.corpus as corpus

    monkeypatch.setattr(corpus, "extract", lambda _path: ["page one", "page two"])
    (tmp_path / "fake.pdf").write_bytes(b"%PDF-1.4 fake")
    [doc] = fetch_corpus(tmp_path, (Source("fake", "UT", "Fake", "https://example.test/x.pdf"),))
    assert doc.pages == 2 and (tmp_path / "manifest.json").exists()
    assert (tmp_path / "fake.txt").read_text().count("<<page") == 2
