"""adapters/semantic_scholar/client.py のテスト.

`fields`パラメータの実データはSemantic Scholar実機で確認済み(2026-09-02)。
バックオフは必須要件(027のユーザー確認)のため厚めに検証する。テストを遅くしない
よう`asyncio.sleep`をmonkeypatchで差し替え、実際には眠らせず渡された秒数だけ記録する。
"""

from __future__ import annotations

import httpx
import pytest
import respx

from polaris.adapters.semantic_scholar.client import (
    SemanticScholarError,
    fetch_citations,
    fetch_paper_by_arxiv_id,
    fetch_references,
    search_papers,
)
from polaris.settings import SemanticScholarSettings

_BASE_URL = "https://api.semanticscholar.org/graph/v1"
_FAKE_API_KEY = "fake-api-key"


def _settings(**overrides: object) -> SemanticScholarSettings:
    base = {
        "api_key": _FAKE_API_KEY,
        "base_url": _BASE_URL,
        "max_attempts": 3,
        "backoff_base_seconds": 2.0,
        "backoff_max_seconds": 30.0,
    }
    base.update(overrides)
    return SemanticScholarSettings(**base)  # type: ignore[arg-type]


def _paper_json(paper_id: str, *, arxiv_id: str | None = None, abstract: str | None = "some abstract") -> dict:
    return {
        "paperId": paper_id,
        "title": f"Paper {paper_id}",
        "abstract": abstract,
        "year": 2024,
        "citationCount": 12,
        "externalIds": ({"ArXiv": arxiv_id} if arxiv_id else {}),
        "openAccessPdf": {"url": "", "status": None},
    }


def _disable_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """`asyncio.sleep`を差し替え、実際には眠らせず呼ばれた秒数だけ記録する."""
    recorded: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr("polaris.adapters.semantic_scholar.client.asyncio.sleep", _fake_sleep)
    return recorded


async def test_fetch_references_flattens_cited_paper_nesting() -> None:
    """referencesは`citedPaper`にネストする形を平坦化して返す."""
    body = {"offset": 0, "data": [{"citedPaper": _paper_json("p1", arxiv_id="1234.5678")}]}
    with respx.mock:
        respx.get(f"{_BASE_URL}/paper/seed/references").mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as client:
            papers = await fetch_references("seed", limit=30, client=client, settings=_settings())

    assert len(papers) == 1
    assert papers[0].paper_id == "p1"
    assert papers[0].arxiv_id == "1234.5678"


async def test_fetch_citations_flattens_citing_paper_nesting() -> None:
    """citationsは`citingPaper`にネストする形を平坦化して返す(内側にabstractを含む)."""
    body = {"offset": 0, "data": [{"citingPaper": _paper_json("p2", abstract="citing paper abstract")}]}
    with respx.mock:
        respx.get(f"{_BASE_URL}/paper/seed/citations").mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as client:
            papers = await fetch_citations("seed", limit=30, client=client, settings=_settings())

    assert len(papers) == 1
    assert papers[0].paper_id == "p2"
    assert papers[0].abstract == "citing paper abstract"


async def test_fetch_references_filters_null_nested_papers() -> None:
    """ネストした論文がnullの要素は除外する."""
    body = {"offset": 0, "data": [{"citedPaper": None}, {"citedPaper": _paper_json("p1")}]}
    with respx.mock:
        respx.get(f"{_BASE_URL}/paper/seed/references").mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as client:
            papers = await fetch_references("seed", limit=30, client=client, settings=_settings())

    assert len(papers) == 1
    assert papers[0].paper_id == "p1"


async def test_fetch_references_filters_papers_with_null_paper_id() -> None:
    """citedPaper自体は非nullでも、内側のpaperId/citationCountがnullな要素は除外する(実機ラン、2026-09-12).

    S2が完全に解決できなかった参照文献はこの形で返ってくる(paperId/citationCountの
    みnull、title等は入っていることもある)。
    """
    unresolved = {
        "paperId": None,
        "title": "Some Unresolved Reference",
        "abstract": None,
        "year": None,
        "citationCount": None,
        "externalIds": None,
        "openAccessPdf": None,
    }
    body = {"offset": 0, "data": [{"citedPaper": unresolved}, {"citedPaper": _paper_json("p1")}]}
    with respx.mock:
        respx.get(f"{_BASE_URL}/paper/seed/references").mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as client:
            papers = await fetch_references("seed", limit=30, client=client, settings=_settings())

    assert len(papers) == 1
    assert papers[0].paper_id == "p1"


async def test_paper_with_null_citation_count_defaults_to_zero() -> None:
    """paperIdはあるがcitationCountがnullの場合は0として扱う(単独のnullフィールドも許容する)."""
    body = {"offset": 0, "data": [{"citedPaper": {**_paper_json("p1"), "citationCount": None}}]}
    with respx.mock:
        respx.get(f"{_BASE_URL}/paper/seed/references").mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as client:
            papers = await fetch_references("seed", limit=30, client=client, settings=_settings())

    assert len(papers) == 1
    assert papers[0].citation_count == 0


async def test_search_papers_parses_flat_data() -> None:
    """searchは`data`配列がフラット(ネストなし)な形で返る."""
    body = {"total": 1, "offset": 0, "data": [_paper_json("p3")]}
    with respx.mock:
        respx.get(f"{_BASE_URL}/paper/search").mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as client:
            papers = await search_papers("transformer", limit=10, client=client, settings=_settings())

    assert len(papers) == 1
    assert papers[0].paper_id == "p3"


async def test_search_papers_filters_items_with_null_paper_id() -> None:
    """data配列の要素自体にpaperIdが無いものは除外する(references/citationsと同じ実機事象への備え)."""
    unresolved = {"paperId": None, "title": "Unresolved", "citationCount": None}
    body = {"total": 2, "offset": 0, "data": [unresolved, _paper_json("p3")]}
    with respx.mock:
        respx.get(f"{_BASE_URL}/paper/search").mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as client:
            papers = await search_papers("transformer", limit=10, client=client, settings=_settings())

    assert len(papers) == 1
    assert papers[0].paper_id == "p3"


async def test_requests_send_x_api_key_header() -> None:
    """全リクエストに`x-api-key`ヘッダが付く."""
    with respx.mock:
        route = respx.get(f"{_BASE_URL}/paper/arXiv:1706.03762").mock(
            return_value=httpx.Response(200, json=_paper_json("p1", arxiv_id="1706.03762")),
        )
        async with httpx.AsyncClient() as client:
            await fetch_paper_by_arxiv_id("1706.03762", client=client, settings=_settings())

    assert route.calls.last.request.headers["x-api-key"] == _FAKE_API_KEY


async def test_fetch_paper_by_arxiv_id_returns_none_on_404() -> None:
    """404はリトライせず、`None`として扱う."""
    with respx.mock:
        route = respx.get(f"{_BASE_URL}/paper/arXiv:9999.99999").mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            paper = await fetch_paper_by_arxiv_id("9999.99999", client=client, settings=_settings())

    assert paper is None
    assert route.call_count == 1  # リトライしていないこと


async def test_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """429を挟んでも、最終的に成功すれば結果を返す."""
    recorded = _disable_sleep(monkeypatch)
    responses = [httpx.Response(429), httpx.Response(200, json=_paper_json("p1", arxiv_id="1706.03762"))]
    with respx.mock:
        respx.get(f"{_BASE_URL}/paper/arXiv:1706.03762").mock(side_effect=responses)
        async with httpx.AsyncClient() as client:
            paper = await fetch_paper_by_arxiv_id("1706.03762", client=client, settings=_settings())

    assert paper is not None
    assert paper.paper_id == "p1"
    assert len(recorded) == 1  # 1回だけ待った


async def test_raises_after_max_attempts_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """429が続くとmax_attempts回で諦めてSemanticScholarErrorを送出する."""
    recorded = _disable_sleep(monkeypatch)
    with respx.mock:
        respx.get(f"{_BASE_URL}/paper/arXiv:1706.03762").mock(return_value=httpx.Response(429))
        async with httpx.AsyncClient() as client:
            with pytest.raises(SemanticScholarError):
                await fetch_paper_by_arxiv_id(
                    "1706.03762", client=client, settings=_settings(max_attempts=3)
                )

    assert len(recorded) == 2  # noqa: PLR2004 - 3回試行、2回だけ待つ(最後は待たずに諦める)


async def test_backoff_delay_increases_exponentially(monkeypatch: pytest.MonkeyPatch) -> None:
    """バックオフの待ち時間が試行ごとに指数的に増える(2s→4s、ジッタを除く整数部分で確認)."""
    recorded = _disable_sleep(monkeypatch)
    with respx.mock:
        respx.get(f"{_BASE_URL}/paper/arXiv:1706.03762").mock(return_value=httpx.Response(429))
        async with httpx.AsyncClient() as client:
            with pytest.raises(SemanticScholarError):
                await fetch_paper_by_arxiv_id(
                    "1706.03762", client=client, settings=_settings(max_attempts=3, backoff_base_seconds=2.0)
                )

    assert len(recorded) == 2  # noqa: PLR2004
    # ジッタ(0〜1秒)を差し引いても2回目の待ちの方が明確に長いはず(2s→4s)。
    assert recorded[1] - recorded[0] > 1.0


async def test_honors_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Retry-After`ヘッダがあれば、指数バックオフの計算値より優先してその秒数を待つ."""
    recorded = _disable_sleep(monkeypatch)
    responses = [
        httpx.Response(429, headers={"Retry-After": "5"}),
        httpx.Response(200, json=_paper_json("p1", arxiv_id="1706.03762")),
    ]
    with respx.mock:
        respx.get(f"{_BASE_URL}/paper/arXiv:1706.03762").mock(side_effect=responses)
        async with httpx.AsyncClient() as client:
            await fetch_paper_by_arxiv_id("1706.03762", client=client, settings=_settings())

    assert len(recorded) == 1
    assert 5.0 <= recorded[0] < 6.0  # noqa: PLR2004 - Retry-After=5秒 + ジッタ(0〜1秒)


async def test_does_not_retry_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """401(認証エラー)は即座に諦め、リトライしない."""
    recorded = _disable_sleep(monkeypatch)
    with respx.mock:
        route = respx.get(f"{_BASE_URL}/paper/arXiv:1706.03762").mock(return_value=httpx.Response(401))
        async with httpx.AsyncClient() as client:
            with pytest.raises(SemanticScholarError):
                await fetch_paper_by_arxiv_id("1706.03762", client=client, settings=_settings())

    assert route.call_count == 1
    assert recorded == []
