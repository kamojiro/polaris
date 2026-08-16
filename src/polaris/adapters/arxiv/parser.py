"""arXiv URL / Atom フィードのパース(純粋関数).

外部への通信を行わない関数だけをここに置き、テストしやすくする。
"""

import re
import xml.etree.ElementTree as ET

from pydantic import BaseModel

_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"
_NAMESPACES = {"atom": _ATOM_NS, "arxiv": _ARXIV_NS}

# https://arxiv.org/abs/2401.12345, /pdf/2401.12345v2, 旧形式 cs/0301015, "arXiv:2401.12345"
_NEW_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
_OLD_ID_RE = re.compile(r"([a-z-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?")


class ArxivMetadata(BaseModel):
    """arXiv から取得した論文メタデータ."""

    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    year: int | None
    doi: str | None


class PaperNotFoundError(Exception):
    """arXiv フィードに該当する論文が無かった場合の例外."""


def extract_arxiv_id(url: str) -> str | None:
    """URL または "arXiv:xxxx" 形式の文字列から arxiv_id(バージョン抜き)を取り出す."""
    text = url.strip()
    match = _NEW_ID_RE.search(text) or _OLD_ID_RE.search(text)
    if match is None:
        return None
    return match.group(1)


def _clean_text(text: str | None) -> str:
    """改行・連続空白を1スペースに正規化する(arXiv の生 XML は折り返されている)."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def parse_atom_entry(xml_text: str) -> ArxivMetadata:
    """ArXiv API が返す Atom フィードの XML から1件分のメタデータを取り出す."""
    root = ET.fromstring(xml_text)  # noqa: S314 - arXiv 公式APIの応答のみを対象とする
    entry = root.find("atom:entry", _NAMESPACES)
    if entry is None:
        raise PaperNotFoundError(xml_text)

    id_url = _clean_text(entry.findtext("atom:id", namespaces=_NAMESPACES))
    arxiv_id = extract_arxiv_id(id_url)
    if arxiv_id is None:
        raise PaperNotFoundError(xml_text)

    title = _clean_text(entry.findtext("atom:title", namespaces=_NAMESPACES))
    abstract = _clean_text(entry.findtext("atom:summary", namespaces=_NAMESPACES))
    authors = [
        _clean_text(name.text) for name in entry.findall("atom:author/atom:name", _NAMESPACES) if _clean_text(name.text)
    ]
    published = _clean_text(entry.findtext("atom:published", namespaces=_NAMESPACES))
    year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None  # noqa: PLR2004
    doi = _clean_text(entry.findtext("arxiv:doi", namespaces=_NAMESPACES)) or None

    return ArxivMetadata(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors,
        abstract=abstract,
        year=year,
        doi=doi,
    )
