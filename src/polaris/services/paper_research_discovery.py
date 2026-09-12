"""関連論文調査の発見段(引用チェイニング/スノーボール法、027-related-paper-research).

論文Aを起点に4つの経路で候補プールを集める(spec §2):

- backward: Aのreferences(参考文献)
- forward: Aのcitations(Aを引用している論文)
- 2hop: 1hopで見つかった論文のうち被引用数上位N件それぞれのcitations
- keyword: タイトル・abstractからLLMで抽出したキーワードでの検索

Semantic Scholarは429が起こりやすい(`adapters/semantic_scholar/client.py`参照)ため、
全リクエストを逐次`await`し、各リクエスト間に`min_interval_seconds`だけ待つ
(`asyncio.gather`は使わない)。1経路が失敗しても他の経路は続行し、発見全体は
落とさない。候補プールはこの関数の戻り値としてのみ存在し、DBには永続化しない
(2026-09-12にユーザー確認、ストーリー2の継続調査機能が必要になったら再検討)。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from polaris.adapters.semantic_scholar.client import (
    SemanticScholarError,
    fetch_citations,
    fetch_paper_by_arxiv_id,
    fetch_references,
    search_papers,
)

if TYPE_CHECKING:
    import httpx

    from polaris.adapters.semantic_scholar.client import SemanticScholarPaper
    from polaris.agent.research_keywords import ResearchKeywordExtractor
    from polaris.settings import PaperResearchSettings, SemanticScholarSettings, Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candidate:
    """発見段で集めた候補論文1件(どの経路で見つかったかを保持する)."""

    paper: SemanticScholarPaper
    source: str  # "backward" | "forward" | "2hop" | "keyword"


def _register(pool: dict[str, Candidate], papers: list[SemanticScholarPaper], source: str) -> None:
    """候補プールへ登録する(abstractが無い論文はtriageできないため除外、paperIdで重複排除)."""
    for paper in papers:
        if not paper.abstract or not paper.abstract.strip():
            continue
        if paper.paper_id in pool:
            continue
        pool[paper.paper_id] = Candidate(paper=paper, source=source)


async def _discover_citation_chain(
    seed: SemanticScholarPaper,
    *,
    pool: dict[str, Candidate],
    http_client: httpx.AsyncClient,
    s2: SemanticScholarSettings,
    research: PaperResearchSettings,
) -> None:
    """backward(references)/forward(citations)/2hopを辿ってpoolに登録する."""
    one_hop: list[SemanticScholarPaper] = []
    pace = s2.min_interval_seconds

    await asyncio.sleep(pace)
    try:
        references = await fetch_references(
            seed.paper_id, limit=research.references_limit, client=http_client, settings=s2
        )
        _register(pool, references, "backward")
        one_hop.extend(references)
    except SemanticScholarError:
        logger.warning("references取得に失敗しました: paper_id=%s", seed.paper_id, exc_info=True)

    await asyncio.sleep(pace)
    try:
        citations = await fetch_citations(
            seed.paper_id, limit=research.citations_limit, client=http_client, settings=s2
        )
        _register(pool, citations, "forward")
        one_hop.extend(citations)
    except SemanticScholarError:
        logger.warning("citations取得に失敗しました: paper_id=%s", seed.paper_id, exc_info=True)

    # 2hop: 1hopの被引用数上位N件それぞれのcitationsを辿る(組み合わせ爆発を避けるため絞り込む)。
    top_papers = sorted(one_hop, key=lambda p: p.citation_count, reverse=True)[: research.hop2_seed_count]
    for hop1_paper in top_papers:
        await asyncio.sleep(pace)
        try:
            hop2 = await fetch_citations(
                hop1_paper.paper_id, limit=research.hop2_citations_limit, client=http_client, settings=s2
            )
            _register(pool, hop2, "2hop")
        except SemanticScholarError:
            logger.warning("2hop citations取得に失敗しました: paper_id=%s", hop1_paper.paper_id, exc_info=True)


async def _discover_by_keywords(
    *,
    seed_title: str,
    seed_abstract: str,
    keyword_extractor: ResearchKeywordExtractor,
    pool: dict[str, Candidate],
    http_client: httpx.AsyncClient,
    s2: SemanticScholarSettings,
    research: PaperResearchSettings,
) -> None:
    """タイトル・abstractからLLMでキーワードを抽出し、Semantic Scholar検索でpoolに登録する."""
    try:
        keywords = (await keyword_extractor.extract(title=seed_title, abstract=seed_abstract)).keywords
    except Exception:
        logger.warning("キーワード抽出に失敗したため、キーワード検索経路をスキップします", exc_info=True)
        return

    for keyword in keywords:
        await asyncio.sleep(s2.min_interval_seconds)
        try:
            found = await search_papers(keyword, limit=research.search_limit, client=http_client, settings=s2)
            _register(pool, found, "keyword")
        except SemanticScholarError:
            logger.warning("キーワード検索に失敗しました: keyword=%s", keyword, exc_info=True)


async def discover_candidates(
    seed_arxiv_id: str,
    *,
    seed_title: str,
    seed_abstract: str,
    keyword_extractor: ResearchKeywordExtractor,
    http_client: httpx.AsyncClient,
    settings: Settings,
) -> list[Candidate]:
    """論文Aを起点に引用チェイニングで関連論文の候補プールを集める(発見段本体)."""
    s2 = settings.semantic_scholar
    research = settings.paper_research
    pool: dict[str, Candidate] = {}

    seed = None
    try:
        seed = await fetch_paper_by_arxiv_id(seed_arxiv_id, client=http_client, settings=s2)
    except SemanticScholarError:
        logger.warning("起点論文のSemantic Scholar解決に失敗しました: arxiv_id=%s", seed_arxiv_id, exc_info=True)

    if seed is not None:
        await _discover_citation_chain(seed, pool=pool, http_client=http_client, s2=s2, research=research)
    else:
        logger.warning("起点論文がSemantic Scholar上で見つからないため、backward/forward/2hopをスキップします")

    await _discover_by_keywords(
        seed_title=seed_title,
        seed_abstract=seed_abstract,
        keyword_extractor=keyword_extractor,
        pool=pool,
        http_client=http_client,
        s2=s2,
        research=research,
    )

    if seed is not None:
        pool.pop(seed.paper_id, None)  # 起点論文自身は候補から除く

    result = list(pool.values())[: research.max_candidates]
    logger.info("発見段完了: %d件の候補(seed_arxiv_id=%s)", len(result), seed_arxiv_id)
    return result
