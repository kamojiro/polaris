"""split_into_chunks の純ロジックテスト."""

from polaris.services.chunking import split_into_chunks


def test_split_into_chunks_by_detected_sections() -> None:
    """番号付き見出しが検出できれば、セクション単位でチャンク化される."""
    text = (
        "1 Introduction\nThis is the introduction paragraph.\n\n"
        "2 Related Work\nThis discusses prior work in the field.\n\n"
        "References\nSome citation list here."
    )

    chunks = split_into_chunks(text, chunk_chars=1000, overlap_chars=100)

    sections = [c.section for c in chunks]
    assert sections == ["1 Introduction", "2 Related Work", "References"]
    assert [c.order for c in chunks] == [0, 1, 2]
    assert "introduction paragraph" in chunks[0].text


def test_split_into_chunks_subsplits_long_section_with_overlap() -> None:
    """1セクションが chunk_chars を超えたら、オーバーラップ付き固定長でサブ分割される."""
    long_body = "A" * 50 + "B" * 50 + "C" * 50 + "D" * 50  # 200 chars
    text = f"1 Introduction\n{long_body}"

    chunks = split_into_chunks(text, chunk_chars=100, overlap_chars=20)

    assert len(chunks) > 1
    assert all(c.section == "1 Introduction" for c in chunks)
    # order が 0 始まりの通し番号であること
    assert [c.order for c in chunks] == list(range(len(chunks)))
    # 隣接チャンクが overlap_chars 分重なっていること
    assert chunks[0].text[-20:] == chunks[1].text[:20]


def test_split_into_chunks_falls_back_to_fixed_length_without_headers() -> None:
    """見出しが1つも検出できない場合は全文を固定長でフォールバック分割する."""
    text = "x" * 250

    chunks = split_into_chunks(text, chunk_chars=100, overlap_chars=0)

    assert len(chunks) == 3  # noqa: PLR2004 - 100 + 100 + 50
    assert all(c.section is None for c in chunks)
    assert sum(len(c.text) for c in chunks) == len(text)


def test_split_into_chunks_empty_text_returns_empty_list() -> None:
    """空文字列を渡した場合は空のリストを返す."""
    assert split_into_chunks("", chunk_chars=100, overlap_chars=10) == []


def test_split_into_chunks_drops_header_only_sections() -> None:
    """見出し直後にすぐ次の見出しが来て本文が無いセクションは出力されない."""
    text = "6 Results\n7 Discussion\nActual discussion content here."

    chunks = split_into_chunks(text, chunk_chars=1000, overlap_chars=100)

    sections = [c.section for c in chunks]
    assert sections == ["7 Discussion"]
    assert "Actual discussion content" in chunks[0].text
    assert "6 Results" not in chunks[0].text
