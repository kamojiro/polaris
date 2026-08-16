"""arxiv パーサーの純ロジックテスト."""

from pathlib import Path

import pytest

from polaris.adapters.arxiv.parser import PaperNotFoundError, extract_arxiv_id, parse_atom_entry

_FIXTURE_DIR = Path(__file__).parent


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://arxiv.org/abs/1706.03762", "1706.03762"),
        ("https://arxiv.org/abs/1706.03762v7", "1706.03762"),
        ("https://arxiv.org/pdf/1706.03762", "1706.03762"),
        ("https://arxiv.org/pdf/1706.03762v3.pdf", "1706.03762"),
        ("arXiv:1706.03762", "1706.03762"),
        ("https://arxiv.org/abs/cs/0301015", "cs/0301015"),
        ("https://arxiv.org/abs/cs/0301015v2", "cs/0301015"),
        ("https://example.com/not-arxiv", None),
        ("", None),
    ],
)
def test_extract_arxiv_id(url: str, expected: str | None) -> None:
    """新旧の arXiv ID 形式・バージョン付き URL を正しく判定できる."""
    assert extract_arxiv_id(url) == expected


def test_parse_atom_entry_reads_real_response() -> None:
    """ArXiv API の実レスポンス形式(1706.03762)からメタデータを取り出せる."""
    xml_text = (_FIXTURE_DIR / "fixture_1706.03762.xml").read_text(encoding="utf-8")

    metadata = parse_atom_entry(xml_text)

    assert metadata.arxiv_id == "1706.03762"
    assert metadata.title == "Attention Is All You Need"
    assert metadata.authors == [
        "Ashish Vaswani",
        "Noam Shazeer",
        "Niki Parmar",
        "Jakob Uszkoreit",
        "Llion Jones",
        "Aidan N. Gomez",
        "Lukasz Kaiser",
        "Illia Polosukhin",
    ]
    assert metadata.year == 2017  # noqa: PLR2004
    assert "Transformer" in metadata.abstract
    assert "\n" not in metadata.abstract


def test_parse_atom_entry_raises_when_no_entry() -> None:
    """該当論文が無い(entry が無い)フィードは PaperNotFoundError を送出する."""
    xml_text = (_FIXTURE_DIR / "fixture_empty.xml").read_text(encoding="utf-8")

    with pytest.raises(PaperNotFoundError):
        parse_atom_entry(xml_text)
