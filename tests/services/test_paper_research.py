"""run_one_research(027-related-paper-research ユーザーストーリー1)の純ロジックテスト.

Semantic Scholarはrespxでモックし、triager/extractor/synthesizer/keyword_extractor/
ingesterはすべて入力を記録するprivateフェイク(Protocolを継承しない構造的型付け、
`tests/services/test_memory_housekeeping.py`と同じ形)を注入する。実LLMは使わない。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import respx

from polaris.agent.extract_problem_solution import ProblemSolution
from polaris.agent.paper_triage import TriageItem, TriageResult
from polaris.agent.research_keywords import ResearchKeywords
from polaris.db.paper_research_repository import (
    PaperDeepAnalysisRepository,
    PaperResearchDiscoveredRepository,
    PaperResearchRepository,
)
from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.domain.entities import Item, ItemType, PaperDeepAnalysisRecord, PaperRecord, PaperResearchRecord
from polaris.services.ingest_paper import IngestResult
from polaris.services.paper_research import run_one_research
from polaris.settings import PaperResearchSettings, SemanticScholarSettings, Settings

if TYPE_CHECKING:
    from collections.abc import Sequence

_BASE_URL = "https://api.semanticscholar.org/graph/v1"
_NOW = datetime(2026, 9, 12, 4, 0, tzinfo=UTC)


def _s2_paper(
    paper_id: str, *, arxiv_id: str | None = None, abstract: str = "abstract", citation_count: int = 1
) -> dict:
    return {
        "paperId": paper_id,
        "title": f"Paper {paper_id}",
        "abstract": abstract,
        "year": 2024,
        "citationCount": citation_count,
        "externalIds": ({"ArXiv": arxiv_id} if arxiv_id else {}),
        "openAccessPdf": {"url": "", "status": None},
    }


class _FakeTriager:
    """全ての候補を関連ありと判定するフェイク(渡された候補数を記録する)."""

    def __init__(self) -> None:
        self.batches: list[int] = []

    async def triage(
        self,
        *,
        seed_title: str,  # noqa: ARG002
        seed_abstract: str,  # noqa: ARG002
        candidates: Sequence[tuple[str, str]],
    ) -> TriageResult:
        self.batches.append(len(candidates))
        return TriageResult(
            items=[TriageItem(index=i, relevant=True, reason="") for i in range(1, len(candidates) + 1)]
        )


class _FakeExtractor:
    """呼び出されたタイトルを記録し、固定のProblemSolutionを返すフェイク."""

    def __init__(self) -> None:
        self.called_titles: list[str] = []

    async def extract(self, *, title: str, body_text: str) -> ProblemSolution:  # noqa: ARG002
        self.called_titles.append(title)
        return ProblemSolution(problem=f"{title}の課題", solution=f"{title}の解決")


class _FakeSynthesizer:
    """outline/synthesizeの呼び出し引数を記録し、渡された論文タイトルを含む文字列を返すフェイク."""

    def __init__(self) -> None:
        self.outline_calls: list[list[tuple[str, str]]] = []
        self.synthesize_calls: list[tuple[str, list[tuple[str, str, str]]]] = []

    async def outline(self, *, seed_title: str, outcomes: Sequence[tuple[str, str]]) -> str:  # noqa: ARG002
        self.outline_calls.append(list(outcomes))
        return "outline: " + ", ".join(title for title, _ in outcomes)

    async def synthesize(self, *, seed_title: str, outline: str, outcomes: Sequence[tuple[str, str, str]]) -> str:  # noqa: ARG002
        self.synthesize_calls.append((outline, list(outcomes)))
        return "\n".join(f"[{title}]" for title, _problem, _solution in outcomes)


class _FakeKeywordExtractor:
    """固定のキーワード1件を返すフェイク."""

    async def extract(self, *, title: str, abstract: str) -> ResearchKeywords:  # noqa: ARG002
        return ResearchKeywords(keywords=["attention"])


class _FakeIngester:
    """特定のURLで例外を送出する以外は、paper_repoに新規Item/PaperRecordを保存するフェイク."""

    def __init__(self, paper_repo: PaperRepository, *, fail_url_substring: str) -> None:
        self._paper_repo = paper_repo
        self._fail_url_substring = fail_url_substring
        self.called_urls: list[str] = []

    async def ingest(self, url: str) -> IngestResult:
        self.called_urls.append(url)
        if self._fail_url_substring in url:
            msg = "取り込み失敗(テスト用)"
            raise RuntimeError(msg)
        arxiv_id = url.rsplit("/", 1)[-1]  # "https://arxiv.org/abs/{arxiv_id}" の末尾から取り出す
        title = "New Paper" if arxiv_id == "2000.00002" else f"Ingested Paper {arxiv_id}"
        now = datetime.now(UTC)
        item = Item(
            id=uuid.uuid4().hex,
            item_type=ItemType.paper,
            title=title,
            summary="ingested paper summary",
            created_at=now,
            source_ref="paper:new",
        )
        record = PaperRecord(
            id=uuid.uuid4().hex,
            item_id=item.id,
            authors=[],
            year=2024,
            arxiv_id=arxiv_id,
            abstract="ingested paper abstract",
            source_url=url,
            ingested_at=now,
        )
        self._paper_repo.save_paper(item, record)
        return IngestResult(item=item, record=record, chunks=[], created=True)


def _setup(
    tmp_path: Path,
) -> tuple[
    PaperRepository, PaperResearchRepository, PaperDeepAnalysisRepository, PaperResearchDiscoveredRepository, Settings
]:
    engine = create_db_engine(str(tmp_path / "test.db"))
    settings = Settings(
        semantic_scholar=SemanticScholarSettings(api_key="fake-key", base_url=_BASE_URL),
        paper_research=PaperResearchSettings(hop2_seed_count=0, triage_batch_size=10),
    )
    return (
        PaperRepository(engine),
        PaperResearchRepository(engine),
        PaperDeepAnalysisRepository(engine),
        PaperResearchDiscoveredRepository(engine),
        settings,
    )


def _make_seed(paper_repo: PaperRepository) -> Item:
    now = datetime.now(UTC)
    item = Item(
        id="seed-item",
        item_type=ItemType.paper,
        title="Seed Paper",
        summary="seed summary",
        created_at=now,
        source_ref="paper:seed-rec",
    )
    record = PaperRecord(
        id="seed-rec",
        item_id="seed-item",
        authors=[],
        year=2024,
        arxiv_id="1000.00001",
        abstract="seed abstract",
        source_url="https://arxiv.org/abs/1000.00001",
        ingested_at=now,
    )
    paper_repo.save_paper(item, record)
    return item


def _mock_semantic_scholar() -> None:
    respx.get(f"{_BASE_URL}/paper/arXiv:1000.00001").mock(
        return_value=httpx.Response(200, json=_s2_paper("seed-id", arxiv_id="1000.00001"))
    )
    respx.get(f"{_BASE_URL}/paper/seed-id/references").mock(
        return_value=httpx.Response(200, json={"data": [{"citedPaper": _s2_paper("p-cached", arxiv_id="2000.00001")}]})
    )
    respx.get(f"{_BASE_URL}/paper/seed-id/citations").mock(
        return_value=httpx.Response(200, json={"data": [{"citingPaper": _s2_paper("p-new", arxiv_id="2000.00002")}]})
    )
    respx.get(f"{_BASE_URL}/paper/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    _s2_paper("p-abstract-only", abstract="abstract only paper abstract"),
                    _s2_paper("p-fail", arxiv_id="2000.00004", abstract="fail paper abstract"),
                ]
            },
        )
    )


async def test_cached_deep_analysis_skips_extractor(tmp_path: Path) -> None:
    """既にPaperDeepAnalysisRecordがある論文は、extractorを呼ばずキャッシュを再利用する."""
    paper_repo, _research_repo, deep_repo, discovered_repo, settings = _setup(tmp_path)
    seed = _make_seed(paper_repo)

    # p-cachedを既存論文として保存し、精読結果もキャッシュ済みにしておく。
    now = datetime.now(UTC)
    cached_item = Item(
        id="cached-item",
        item_type=ItemType.paper,
        title="Cached Paper",
        summary="cached summary",
        created_at=now,
        source_ref="paper:cached-rec",
    )
    cached_record = PaperRecord(
        id="cached-rec",
        item_id="cached-item",
        authors=[],
        year=2023,
        arxiv_id="2000.00001",
        abstract="cached abstract",
        source_url="https://arxiv.org/abs/2000.00001",
        ingested_at=now,
    )
    paper_repo.save_paper(cached_item, cached_record)
    deep_repo.save(
        PaperDeepAnalysisRecord(
            id="deep-cached", item_id="cached-item", problem="既知の課題", solution="既知の解決", created_at=now
        )
    )

    triager, extractor, synthesizer, keyword_extractor = (
        _FakeTriager(),
        _FakeExtractor(),
        _FakeSynthesizer(),
        _FakeKeywordExtractor(),
    )
    ingester = _FakeIngester(paper_repo, fail_url_substring="2000.00004")
    record = PaperResearchRecord(
        id="res-1", seed_item_id=seed.id, seed_title=seed.title, status="in_progress", created_at=_NOW
    )

    with respx.mock:
        _mock_semantic_scholar()
        async with httpx.AsyncClient() as client:
            await run_one_research(
                record,
                deep_repo=deep_repo,
                discovered_repo=discovered_repo,
                paper_repo=paper_repo,
                triager=triager,
                extractor=extractor,
                synthesizer=synthesizer,
                keyword_extractor=keyword_extractor,
                ingester=ingester,
                http_client=client,
                settings=settings,
            )

    assert "Cached Paper" not in extractor.called_titles


async def test_already_ingested_paper_skips_ingester(tmp_path: Path) -> None:
    """ArXiv IDで既に取り込み済みの論文は、ingesterを呼ばず既存Itemを再利用する."""
    paper_repo, _research_repo, deep_repo, discovered_repo, settings = _setup(tmp_path)
    seed = _make_seed(paper_repo)

    now = datetime.now(UTC)
    existing_item = Item(
        id="cached-item",
        item_type=ItemType.paper,
        title="Cached Paper",
        summary="cached summary",
        created_at=now,
        source_ref="paper:cached-rec",
    )
    existing_record = PaperRecord(
        id="cached-rec",
        item_id="cached-item",
        authors=[],
        year=2023,
        arxiv_id="2000.00001",
        abstract="cached abstract",
        source_url="https://arxiv.org/abs/2000.00001",
        ingested_at=now,
    )
    paper_repo.save_paper(existing_item, existing_record)
    # PaperDeepAnalysisRecordは作らない: extractorは呼ばれるがingesterは呼ばれないことを確認する。

    triager, extractor, synthesizer, keyword_extractor = (
        _FakeTriager(),
        _FakeExtractor(),
        _FakeSynthesizer(),
        _FakeKeywordExtractor(),
    )
    ingester = _FakeIngester(paper_repo, fail_url_substring="2000.00004")
    record = PaperResearchRecord(
        id="res-1", seed_item_id=seed.id, seed_title=seed.title, status="in_progress", created_at=_NOW
    )

    with respx.mock:
        _mock_semantic_scholar()
        async with httpx.AsyncClient() as client:
            await run_one_research(
                record,
                deep_repo=deep_repo,
                discovered_repo=discovered_repo,
                paper_repo=paper_repo,
                triager=triager,
                extractor=extractor,
                synthesizer=synthesizer,
                keyword_extractor=keyword_extractor,
                ingester=ingester,
                http_client=client,
                settings=settings,
            )

    assert "https://arxiv.org/abs/2000.00001" not in ingester.called_urls
    assert "Cached Paper" in extractor.called_titles


async def test_paper_without_arxiv_or_pdf_reaches_synthesis_without_cache_row(tmp_path: Path) -> None:
    """ArXiv IDもオープンアクセスPDFも無い論文は、キャッシュ行を作らずabstractのみで統合段に届く."""
    paper_repo, _research_repo, deep_repo, discovered_repo, settings = _setup(tmp_path)
    seed = _make_seed(paper_repo)

    triager, extractor, synthesizer, keyword_extractor = (
        _FakeTriager(),
        _FakeExtractor(),
        _FakeSynthesizer(),
        _FakeKeywordExtractor(),
    )
    ingester = _FakeIngester(paper_repo, fail_url_substring="2000.00004")
    record = PaperResearchRecord(
        id="res-1", seed_item_id=seed.id, seed_title=seed.title, status="in_progress", created_at=_NOW
    )

    with respx.mock:
        _mock_semantic_scholar()
        async with httpx.AsyncClient() as client:
            summary = await run_one_research(
                record,
                deep_repo=deep_repo,
                discovered_repo=discovered_repo,
                paper_repo=paper_repo,
                triager=triager,
                extractor=extractor,
                synthesizer=synthesizer,
                keyword_extractor=keyword_extractor,
                ingester=ingester,
                http_client=client,
                settings=settings,
            )

    assert "(abstractのみ)" in summary
    synthesize_titles = [title for title, _problem, _solution in synthesizer.synthesize_calls[0][1]]
    assert any("(abstractのみ)" in title for title in synthesize_titles)


async def test_one_candidate_ingest_failure_does_not_abort_research(tmp_path: Path) -> None:
    """1候補(p-fail)の取り込み失敗があっても、他の候補の統合結果は得られる."""
    paper_repo, _research_repo, deep_repo, discovered_repo, settings = _setup(tmp_path)
    seed = _make_seed(paper_repo)

    triager, extractor, synthesizer, keyword_extractor = (
        _FakeTriager(),
        _FakeExtractor(),
        _FakeSynthesizer(),
        _FakeKeywordExtractor(),
    )
    ingester = _FakeIngester(paper_repo, fail_url_substring="2000.00004")
    record = PaperResearchRecord(
        id="res-1", seed_item_id=seed.id, seed_title=seed.title, status="in_progress", created_at=_NOW
    )

    with respx.mock:
        _mock_semantic_scholar()
        async with httpx.AsyncClient() as client:
            summary = await run_one_research(
                record,
                deep_repo=deep_repo,
                discovered_repo=discovered_repo,
                paper_repo=paper_repo,
                triager=triager,
                extractor=extractor,
                synthesizer=synthesizer,
                keyword_extractor=keyword_extractor,
                ingester=ingester,
                http_client=client,
                settings=settings,
            )

    # p-fail(2000.00004)は例外を送出するため統合結果に含まれない。
    assert "Paper p-fail" not in summary
    # p-new(2000.00002)は正常に取り込まれ、統合結果に含まれる。
    assert summary  # 空文字列や「見つかりませんでした」ではないこと
    assert "見つかりませんでした" not in summary
    assert "New Paper" in [title for title, _problem, _solution in synthesizer.synthesize_calls[0][1]]
    assert "https://arxiv.org/abs/2000.00002" in ingester.called_urls
    assert discovered_repo.list_item_ids()  # 新規取り込みされた論文の出自が記録されている


async def test_synthesis_uses_outline_then_synthesize_exactly_once(tmp_path: Path) -> None:
    """統合は1論文ずつのfold()ではなく、outline→synthesizeの2段階を1回ずつ呼ぶ(2026-09-13改訂)."""
    paper_repo, _research_repo, deep_repo, discovered_repo, settings = _setup(tmp_path)
    seed = _make_seed(paper_repo)

    triager, extractor, synthesizer, keyword_extractor = (
        _FakeTriager(),
        _FakeExtractor(),
        _FakeSynthesizer(),
        _FakeKeywordExtractor(),
    )
    ingester = _FakeIngester(paper_repo, fail_url_substring="2000.00004")
    record = PaperResearchRecord(
        id="res-1", seed_item_id=seed.id, seed_title=seed.title, status="in_progress", created_at=_NOW
    )

    with respx.mock:
        _mock_semantic_scholar()
        async with httpx.AsyncClient() as client:
            summary = await run_one_research(
                record,
                deep_repo=deep_repo,
                discovered_repo=discovered_repo,
                paper_repo=paper_repo,
                triager=triager,
                extractor=extractor,
                synthesizer=synthesizer,
                keyword_extractor=keyword_extractor,
                ingester=ingester,
                http_client=client,
                settings=settings,
            )

    # 1論文ごとにfold()するのではなく、outline/synthesizeともちょうど1回ずつ呼ばれる。
    assert len(synthesizer.outline_calls) == 1
    assert len(synthesizer.synthesize_calls) == 1

    # Step A(outline)には(title, problem)のペアのみが渡り、solutionは含まれない。
    outline_input = synthesizer.outline_calls[0]
    assert all(len(pair) == 2 for pair in outline_input)  # noqa: PLR2004
    outline_titles = [title for title, _problem in outline_input]

    # Step B(synthesize)には全論文の(title, problem, solution)が渡り、Step Aと同じ論文集合。
    synth_outline_arg, synth_outcomes = synthesizer.synthesize_calls[0]
    synth_titles = [title for title, _problem, _solution in synth_outcomes]
    assert set(synth_titles) == set(outline_titles)
    assert synth_outline_arg.startswith("outline: ")  # _FakeSynthesizer.outline()の戻り値がそのまま渡っている

    # 最終summaryはsynthesize()の戻り値であり、outline()の戻り値ではない。
    assert summary == "\n".join(f"[{title}]" for title in synth_titles)
