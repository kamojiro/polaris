"""論文本文のチャンク分割(純粋関数).

セクション見出し(「1 Introduction」「3.2.1 Scaled Dot-Product Attention」等の
番号付き見出しや「References」等の既知の見出し語)を検出できればセクション単位で
分割し、長いセクションはオーバーラップ付きの固定長でサブ分割する。見出しが1つも
見つからない場合は全文を固定長で分割する(spec の「セクション単位、フォールバック
で固定長」に対応)。

チャンク分割の粒度(chunk_chars / overlap_chars)は spec 上も未確定事項として
残っており、実データを見ながら設定値で調整する前提。
"""

import re

from pydantic import BaseModel

# 例: "1 Introduction", "3.2.1 Scaled Dot-Product Attention"
_NUMBERED_HEADER_RE = re.compile(r"^(\d+(\.\d+)*)\s+[A-Z][A-Za-z ,\-]{2,60}$")
_KNOWN_BARE_HEADERS = {"Abstract", "References", "Acknowledgments", "Acknowledgements"}


class ChunkDraft(BaseModel):
    """永続化前のチャンク(id / item_id はサービス層で付与する)."""

    section: str | None
    order: int
    text: str


def _is_header_line(line: str) -> bool:
    """行がセクション見出しらしいかを判定する."""
    stripped = line.strip()
    if not stripped:
        return False
    return (
        bool(_NUMBERED_HEADER_RE.match(stripped)) or stripped in _KNOWN_BARE_HEADERS or stripped.startswith("Appendix")
    )


def _split_fixed_length(text: str, *, chunk_chars: int, overlap_chars: int) -> list[str]:
    """1本のテキストをオーバーラップ付き固定長で分割する."""
    text = text.strip()
    if not text:
        return []
    step = max(chunk_chars - overlap_chars, 1)
    pieces: list[str] = []
    start = 0
    while start < len(text):
        piece = text[start : start + chunk_chars].strip()
        if piece:
            pieces.append(piece)
        start += step
    return pieces


def _split_by_section(text: str) -> list[tuple[str | None, str]]:
    """見出し行をもとに (section, section_text) のリストへ分割する."""
    lines = text.split("\n")
    header_indices = [i for i, line in enumerate(lines) if _is_header_line(line)]
    if not header_indices:
        return []

    segments: list[tuple[str | None, str]] = []
    if header_indices[0] > 0:
        preamble = "\n".join(lines[: header_indices[0]]).strip()
        if preamble:
            segments.append((None, preamble))

    for idx, start in enumerate(header_indices):
        end = header_indices[idx + 1] if idx + 1 < len(header_indices) else len(lines)
        section_title = lines[start].strip()
        body = "\n".join(lines[start + 1 : end]).strip()
        if not body:
            # 見出し直後にすぐ次の見出しが来て本文が無いセクションは、見出し文字列
            # だけの無意味なチャンクになるため出力しない(次のセクションに吸収される)。
            continue
        segments.append((section_title, f"{section_title}\n{body}"))
    return segments


def split_into_chunks(text: str, *, chunk_chars: int, overlap_chars: int) -> list[ChunkDraft]:
    """本文をチャンクに分割する.

    Args:
        text: PDF から抽出した本文(または abstract フォールバック)。
        chunk_chars: 1チャンクあたりの目安文字数。
        overlap_chars: 固定長分割時に隣接チャンク間で重複させる文字数。

    Returns:
        order 昇順の ChunkDraft のリスト。

    """
    segments = _split_by_section(text)
    if not segments:
        segments = [(None, text)]

    drafts: list[ChunkDraft] = []
    order = 0
    for section, section_text in segments:
        if len(section_text) <= chunk_chars:
            pieces = [section_text] if section_text.strip() else []
        else:
            pieces = _split_fixed_length(section_text, chunk_chars=chunk_chars, overlap_chars=overlap_chars)
        for piece in pieces:
            drafts.append(ChunkDraft(section=section, order=order, text=piece))
            order += 1
    return drafts
