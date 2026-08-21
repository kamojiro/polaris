"""paper_source.resolve_source(実質の InputKind 判定)の純ロジックテスト."""

import pytest

from polaris.services.paper_source import (
    ArxivSource,
    InvalidPaperUrlError,
    UploadSource,
    UrlSource,
    resolve_source,
)


def test_resolve_source_arxiv_url() -> None:
    """arxiv.org の URL は ArxivSource になる."""
    source = resolve_source("https://arxiv.org/abs/1706.03762")
    assert source == ArxivSource(arxiv_id="1706.03762")


def test_resolve_source_bare_arxiv_id() -> None:
    """裸の arXiv ID も ArxivSource になる."""
    source = resolve_source("arXiv:1706.03762")
    assert source == ArxivSource(arxiv_id="1706.03762")


def test_resolve_source_pdf_url() -> None:
    """arxiv.org 以外の http(s) URL は UrlSource になる."""
    source = resolve_source("https://example.com/papers/some-paper.pdf")
    assert source == UrlSource(url="https://example.com/papers/some-paper.pdf")


def test_resolve_source_upload() -> None:
    """upload:// 擬似スキームは UploadSource になる."""
    source = resolve_source("upload://abc123")
    assert source == UploadSource(upload_id="abc123")


def test_resolve_source_rejects_empty_upload_id() -> None:
    """upload:// の後に ID が無ければ無効な入力として扱う."""
    with pytest.raises(InvalidPaperUrlError):
        resolve_source("upload://")


def test_resolve_source_rejects_unrecognized_text() -> None:
    """URL でも arXiv ID でも upload:// でもない文字列は InvalidPaperUrlError になる."""
    with pytest.raises(InvalidPaperUrlError):
        resolve_source("not a url or id")
