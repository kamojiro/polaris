"""論文の取り込み元の判定(実質的な InputKind).

002 の spec は「入力判定(arxiv / url / local_pdf)」を将来拡張できる形で
用意したとしていたが、実際には `extract_arxiv_id` の二値判定しか無かった
(014-paper-url-pdf-ingest着手時の調査で判明)。ここで3種類の入力を
明示的な型として分離する。arxiv_id や url のように種別ごとに保持したい
データが異なるため、enum ではなくタグ付き dataclass の union にしている。
"""

from __future__ import annotations

from dataclasses import dataclass

from polaris.adapters.arxiv.parser import extract_arxiv_id

# チャットからのアップロード連携は `upload://<upload_id>` という擬似スキームで表す
# (`POST /api/papers/upload` が発行した upload_id をチャットメッセージに埋め込んで渡す)。
_UPLOAD_SCHEME_PREFIX = "upload://"


class InvalidPaperUrlError(Exception):
    """arXiv の URL/ID、PDF直リンクURL、upload:// のいずれとしても解釈できなかった場合の例外."""


@dataclass(frozen=True)
class ArxivSource:
    """arXiv の URL/ID から取り込む."""

    arxiv_id: str


@dataclass(frozen=True)
class UrlSource:
    """PDF直リンクURLから取り込む."""

    url: str


@dataclass(frozen=True)
class UploadSource:
    """`POST /api/papers/upload` でアップロード済みのファイルから取り込む."""

    upload_id: str


PaperSource = ArxivSource | UrlSource | UploadSource


def resolve_source(text: str) -> PaperSource:
    """入力文字列(チャットメッセージ中の1トークン)から取り込み元を判定する.

    判定順: upload:// 擬似スキーム → arXiv(ホスト厳格化済みの extract_arxiv_id)
    → http(s):// の URL → どれにも当てはまらなければ例外。
    """
    stripped = text.strip()

    if stripped.startswith(_UPLOAD_SCHEME_PREFIX):
        upload_id = stripped[len(_UPLOAD_SCHEME_PREFIX) :]
        if not upload_id:
            raise InvalidPaperUrlError(text)
        return UploadSource(upload_id=upload_id)

    arxiv_id = extract_arxiv_id(stripped)
    if arxiv_id is not None:
        return ArxivSource(arxiv_id=arxiv_id)

    if stripped.startswith(("http://", "https://")):
        return UrlSource(url=stripped)

    raise InvalidPaperUrlError(text)
