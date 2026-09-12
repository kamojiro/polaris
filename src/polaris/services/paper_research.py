"""関連論文調査のオーケストレーション(027-related-paper-research ユーザーストーリー1).

発見(`paper_research_discovery.py`)→粗い判定(`agent/paper_triage.py`)→精読+
キャッシュ(既存の002/014取り込みパイプライン+`agent/extract_problem_solution.py`)
→統合(`agent/research_synthesis.py`)を1レコード分実行し、`cli/run_paper_research.py`
から呼ばれる。008/023と同じ「1件の失敗でバッチ全体を落とさない」方針
(`run_one_research`の失敗は`mark_failed`にして次のバッチ実行で再試行)。このパイプライン
全体で`asyncio.gather`は使わない(無料枠モデルは同時実行で非決定的に落ちることを
021-discord-integrationの実機検証で確認済み。cronバッチにレイテンシ要件は無いため
逐次実行で困らない)。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple, Protocol

from polaris.domain.entities import PaperDeepAnalysisRecord, PaperResearchDiscoveredPaper
from polaris.services.paper_full_text import load_full_text
from polaris.services.paper_research_discovery import discover_candidates

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx

    from polaris.adapters.semantic_scholar.client import SemanticScholarPaper
    from polaris.agent.extract_problem_solution import PaperProblemSolutionExtractor
    from polaris.agent.paper_triage import PaperTriager
    from polaris.agent.research_keywords import ResearchKeywordExtractor
    from polaris.agent.research_synthesis import ResearchSynthesizer
    from polaris.db.paper_research_repository import (
        PaperDeepAnalysisRepository,
        PaperResearchDiscoveredRepository,
        PaperResearchRepository,
    )
    from polaris.db.repository import PaperRepository
    from polaris.domain.entities import PaperResearchRecord
    from polaris.services.ingest_paper import IngestResult
    from polaris.services.paper_research_discovery import Candidate
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

__all__ = [
    "PaperIngester",
    "PaperResearchBatchResult",
    "run_one_research",
    "run_paper_research_batch",
]


class PaperIngester(Protocol):
    """論文取り込み(002/014パイプライン)の抽象(テスト時にフェイクへ差し替えるため)."""

    async def ingest(self, url: str) -> IngestResult:
        """ArXiv URL/ID または PDF直リンクURLから論文を取り込む."""
        ...


class PaperResearchBatchResult(NamedTuple):
    """`run_paper_research_batch` の戻り値(バッチ実行の統計)."""

    reclaimed: int
    processed: int
    done: int
    failed: int


@dataclass(frozen=True)
class _DeepReadOutcome:
    """精読段の結果(統合段への入力). abstractのみの場合もこの形に揃える."""

    paper_title: str
    problem: str
    solution: str


def _resolve_ingest_url(paper: SemanticScholarPaper) -> str | None:
    """候補論文の取り込み先URLを決める(arXiv優先、次点でオープンアクセスPDF).

    `openAccessPdf.url`は存在してもキーが空文字列で返ることがある(実測、2026-09-12)ため、
    空文字列は「未取得」として扱う。
    """
    if paper.arxiv_id:
        return f"https://arxiv.org/abs/{paper.arxiv_id}"
    if paper.open_access_pdf is not None and paper.open_access_pdf.url:
        return paper.open_access_pdf.url
    return None


async def _triage_all(
    candidates: Sequence[Candidate],
    *,
    seed_title: str,
    seed_abstract: str,
    triager: PaperTriager,
    batch_size: int,
) -> list[Candidate]:
    """候補プールを`batch_size`件ずつtriageし、関連ありと判定された候補だけを元の順序で返す.

    1バッチの失敗は、そのバッチだけスキップして続行する(発見した候補が多い調査ほど
    バッチ数が増えるため、1バッチの失敗で調査全体を止めない)。
    """
    relevant: list[Candidate] = []
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start : start + batch_size]
        pairs = [(c.paper.title, c.paper.abstract or "") for c in batch]
        try:
            result = await triager.triage(seed_title=seed_title, seed_abstract=seed_abstract, candidates=pairs)
        except Exception:
            logger.warning("triageに失敗したため、このバッチ(%d件)をスキップします", len(batch), exc_info=True)
            continue
        relevant_indices = {item.index for item in result.items if item.relevant}
        relevant.extend(candidate for i, candidate in enumerate(batch, 1) if i in relevant_indices)
    return relevant


async def _deep_read_one(
    candidate: Candidate,
    *,
    paper_repo: PaperRepository,
    deep_repo: PaperDeepAnalysisRepository,
    discovered_repo: PaperResearchDiscoveredRepository,
    ingester: PaperIngester,
    extractor: PaperProblemSolutionExtractor,
    research_id: str,
    settings: Settings,
) -> _DeepReadOutcome | None:
    """1候補を精読する(既存論文の再利用→キャッシュ再利用→新規取り込みの順で重複を避ける).

    取り込み・抽出に失敗した場合は`None`を返し、呼び出し側で数えるだけに留める
    (1候補の失敗で調査全体を止めない)。
    """
    paper = candidate.paper
    existing = paper_repo.find_by_arxiv_id(paper.arxiv_id) if paper.arxiv_id else None
    item, record = existing if existing is not None else (None, None)

    if item is not None:
        cached = deep_repo.find_by_item_id(item.id)
        if cached is not None:
            return _DeepReadOutcome(paper_title=item.title, problem=cached.problem, solution=cached.solution)

    if item is None:
        url = _resolve_ingest_url(paper)
        if url is None:
            # arXiv IDもオープンアクセスPDFも無く取り込めない: abstractのみで統合段に持ち込む。
            return _DeepReadOutcome(
                paper_title=f"{paper.title}(abstractのみ)",
                problem="(精読していないため不明)",
                solution=paper.abstract or "",
            )
        try:
            result = await ingester.ingest(url)
        except Exception:
            logger.warning("論文の取り込みに失敗しました: paper_id=%s", paper.paper_id, exc_info=True)
            return None
        item, record = result.item, result.record
        if result.created:
            discovered_repo.save(
                PaperResearchDiscoveredPaper(
                    id=uuid.uuid4().hex, item_id=item.id, research_id=research_id, discovered_at=datetime.now(UTC)
                )
            )
        cached = deep_repo.find_by_item_id(item.id)
        if cached is not None:
            return _DeepReadOutcome(paper_title=item.title, problem=cached.problem, solution=cached.solution)

    assert record is not None  # item is not None の分岐は常にrecordも伴う  # noqa: S101
    try:
        full_text = await load_full_text(
            item, record, repo=paper_repo, max_chars=settings.paper_research.analysis_max_chars
        )
        extracted = await extractor.extract(title=item.title, body_text=full_text.text)
    except Exception:
        logger.warning("課題/解決の抽出に失敗しました: item_id=%s", item.id, exc_info=True)
        return None

    deep_repo.save(
        PaperDeepAnalysisRecord(
            id=uuid.uuid4().hex,
            item_id=item.id,
            problem=extracted.problem,
            solution=extracted.solution,
            created_at=datetime.now(UTC),
        )
    )
    return _DeepReadOutcome(paper_title=item.title, problem=extracted.problem, solution=extracted.solution)


async def run_one_research(
    record: PaperResearchRecord,
    *,
    deep_repo: PaperDeepAnalysisRepository,
    discovered_repo: PaperResearchDiscoveredRepository,
    paper_repo: PaperRepository,
    triager: PaperTriager,
    extractor: PaperProblemSolutionExtractor,
    synthesizer: ResearchSynthesizer,
    keyword_extractor: ResearchKeywordExtractor,
    ingester: PaperIngester,
    http_client: httpx.AsyncClient,
    settings: Settings,
) -> str:
    """1件の調査依頼を最後まで実行し、統合結果の本文を返す.

    例外は呼び出し側(`run_paper_research_batch`)がcatchして`mark_failed`する想定で、
    ここでは握りつぶさない。
    """
    seed = paper_repo.find_by_item_id(record.seed_item_id)
    if seed is None:
        msg = f"起点論文が見つかりません(item_id={record.seed_item_id})"
        raise ValueError(msg)
    seed_item, seed_record = seed
    if seed_record.arxiv_id is None:
        msg = "起点論文のarXiv IDが無いため、Semantic Scholarでの解決ができません"
        raise ValueError(msg)

    candidates = await discover_candidates(
        seed_record.arxiv_id,
        seed_title=seed_item.title,
        seed_abstract=seed_record.abstract,
        keyword_extractor=keyword_extractor,
        http_client=http_client,
        settings=settings,
    )

    relevant = await _triage_all(
        candidates,
        seed_title=seed_item.title,
        seed_abstract=seed_record.abstract,
        triager=triager,
        batch_size=settings.paper_research.triage_batch_size,
    )

    selected = sorted(relevant, key=lambda c: c.paper.citation_count, reverse=True)[
        : settings.paper_research.max_deep_read
    ]

    outcomes: list[_DeepReadOutcome] = []
    for candidate in selected:
        outcome = await _deep_read_one(
            candidate,
            paper_repo=paper_repo,
            deep_repo=deep_repo,
            discovered_repo=discovered_repo,
            ingester=ingester,
            extractor=extractor,
            research_id=record.id,
            settings=settings,
        )
        if outcome is not None:
            outcomes.append(outcome)

    summary: str | None = None
    for outcome in outcomes:
        summary = await synthesizer.fold(
            seed_title=seed_item.title,
            previous=summary,
            paper_title=outcome.paper_title,
            problem=outcome.problem,
            solution=outcome.solution,
        )

    if summary is None:
        summary = f"『{seed_item.title}』に関連する論文で、精読に値すると判定されたものは見つかりませんでした。"

    logger.info(
        "調査完了: research_id=%s, candidates=%d, relevant=%d, deep_read=%d",
        record.id,
        len(candidates),
        len(relevant),
        len(outcomes),
    )
    return summary


async def run_paper_research_batch(
    *,
    research_repo: PaperResearchRepository,
    deep_repo: PaperDeepAnalysisRepository,
    discovered_repo: PaperResearchDiscoveredRepository,
    paper_repo: PaperRepository,
    triager: PaperTriager,
    extractor: PaperProblemSolutionExtractor,
    synthesizer: ResearchSynthesizer,
    keyword_extractor: ResearchKeywordExtractor,
    ingester: PaperIngester,
    http_client: httpx.AsyncClient,
    settings: Settings,
    max_records: int | None = None,
) -> PaperResearchBatchResult:
    """キューのstale回収→多重起動ガード→`max_records`件の処理、を1回のバッチとして行う.

    `max_records`を省略した場合は`settings.paper_research.max_records_per_run`を使う
    (CLIの`--max-records`でデバッグ時だけ上書きできるようにするための引数)。
    """
    if max_records is None:
        max_records = settings.paper_research.max_records_per_run
    now = datetime.now(UTC)
    reclaimed = research_repo.reclaim_stale(
        now=now,
        older_than_minutes=settings.paper_research.stale_in_progress_minutes,
        max_attempts=settings.paper_research.max_record_attempts,
    )
    if research_repo.has_fresh_in_progress(
        now=now, older_than_minutes=settings.paper_research.stale_in_progress_minutes
    ):
        logger.info("実行中の調査があるため、このバッチはスキップします")
        return PaperResearchBatchResult(reclaimed=reclaimed, processed=0, done=0, failed=0)

    processed = done = failed = 0
    for _ in range(max_records):
        record = research_repo.claim_next_pending(now=datetime.now(UTC))
        if record is None:
            break
        processed += 1
        try:
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
                http_client=http_client,
                settings=settings,
            )
        except Exception as exc:
            logger.exception("調査の実行に失敗しました: research_id=%s", record.id)
            research_repo.mark_failed(record.id, error=str(exc)[:500], completed_at=datetime.now(UTC))
            failed += 1
            continue
        research_repo.mark_done(record.id, result_summary=summary, completed_at=datetime.now(UTC))
        done += 1

    logger.info(
        "調査バッチ完了: reclaimed=%d, processed=%d, done=%d, failed=%d", reclaimed, processed, done, failed
    )
    return PaperResearchBatchResult(reclaimed=reclaimed, processed=processed, done=done, failed=failed)
