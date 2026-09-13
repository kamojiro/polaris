"""関連論文調査バッチ(027-related-paper-research ユーザーストーリー1)のCLIエントリポイント.

`uv run python -m polaris.cli.run_paper_research` で実行する。008/023/024と同じ
OS cron駆動のCLI(例: crontabに
`*/30 * * * * cd /path/to/polaris && uv run python -m polaris.cli.run_paper_research`)。
1回の実行で`settings.paper_research.max_records_per_run`件(既定1件)を消化する
(1レコードでSemantic Scholar呼び出し約10回・PDF取り込み最大8本・LLM呼び出し約20回、
10〜30分かかる想定)。`--max-records`でデバッグ時だけ上書きできる。

Semantic ScholarのAPIキー(`settings.semantic_scholar.api_key`)が未設定の場合は、
何もせず即座に終了する(discord/api/app.pyの`GET /api/discord/recent`と同じ
「未設定なら機能無効」方針)。

FastAPIサーバーの生存に依存させないため、`api/app.py`とは別にEngine・Repository・
Agentを自前で組み立てる。GPUは使わないため`QwenEmbedder`はロードしない。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import TYPE_CHECKING

import httpx

from polaris.agent.extract_metadata import AgentPaperMetadataExtractor, build_extract_metadata_agent
from polaris.agent.extract_problem_solution import (
    AgentPaperProblemSolutionExtractor,
    build_extract_problem_solution_agent,
)
from polaris.agent.paper_triage import AgentPaperTriager, build_paper_triage_agent
from polaris.agent.research_keywords import AgentResearchKeywordExtractor, build_research_keywords_agent
from polaris.agent.research_synthesis import (
    AgentResearchSynthesizer,
    build_research_outline_agent,
    build_research_synthesis_agent,
)
from polaris.agent.structure_paper import AgentPaperStructurer, build_structure_agent
from polaris.db.paper_research_repository import (
    PaperDeepAnalysisRepository,
    PaperResearchDiscoveredRepository,
    PaperResearchRepository,
)
from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.services.ingest_paper import ingest_paper_from_url
from polaris.services.paper_research import run_paper_research_batch
from polaris.settings import Settings

if TYPE_CHECKING:
    from polaris.agent.extract_metadata import PaperMetadataExtractor
    from polaris.agent.structure_paper import PaperStructurer
    from polaris.services.ingest_paper import IngestResult

logger = logging.getLogger(__name__)


class _IngestPaperAdapter:
    """`services.paper_research.PaperIngester` Protocolを既存の002/014パイプラインで満たす薄いアダプタ."""

    def __init__(
        self,
        *,
        repo: PaperRepository,
        http_client: httpx.AsyncClient,
        structurer: PaperStructurer,
        extractor: PaperMetadataExtractor,
        settings: Settings,
    ) -> None:
        self._repo = repo
        self._http_client = http_client
        self._structurer = structurer
        self._extractor = extractor
        self._settings = settings

    async def ingest(self, url: str) -> IngestResult:
        """ArXiv URL/ID または PDF直リンクURLから論文を取り込む."""
        return await ingest_paper_from_url(
            url,
            repo=self._repo,
            http_client=self._http_client,
            structurer=self._structurer,
            extractor=self._extractor,
            settings=self._settings,
        )


async def _run(settings: Settings, *, max_records: int | None) -> None:
    engine = create_db_engine(settings.DB_PATH, embedding_dim=settings.ingest.embedding_dim)
    paper_repo = PaperRepository(engine)
    research_repo = PaperResearchRepository(engine)
    deep_repo = PaperDeepAnalysisRepository(engine)
    discovered_repo = PaperResearchDiscoveredRepository(engine)

    structurer = AgentPaperStructurer(build_structure_agent(settings))
    metadata_extractor = AgentPaperMetadataExtractor(build_extract_metadata_agent(settings))
    triager = AgentPaperTriager(build_paper_triage_agent(settings))
    problem_solution_extractor = AgentPaperProblemSolutionExtractor(build_extract_problem_solution_agent(settings))
    synthesizer = AgentResearchSynthesizer(
        build_research_outline_agent(settings), build_research_synthesis_agent(settings)
    )
    keyword_extractor = AgentResearchKeywordExtractor(build_research_keywords_agent(settings))

    async with httpx.AsyncClient() as http_client:
        ingester = _IngestPaperAdapter(
            repo=paper_repo,
            http_client=http_client,
            structurer=structurer,
            extractor=metadata_extractor,
            settings=settings,
        )
        result = await run_paper_research_batch(
            research_repo=research_repo,
            deep_repo=deep_repo,
            discovered_repo=discovered_repo,
            paper_repo=paper_repo,
            triager=triager,
            extractor=problem_solution_extractor,
            synthesizer=synthesizer,
            keyword_extractor=keyword_extractor,
            ingester=ingester,
            http_client=http_client,
            settings=settings,
            max_records=max_records,
        )
    logger.info(
        "調査バッチ完了: reclaimed=%d, processed=%d, done=%d, failed=%d",
        result.reclaimed,
        result.processed,
        result.done,
        result.failed,
    )


def main() -> None:
    """`python -m polaris.cli.run_paper_research` のエントリポイント."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-records", type=int, default=None, help="このバッチで消化する最大件数(既定は設定値)"
    )
    args = parser.parse_args()

    settings = Settings()
    logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not settings.semantic_scholar.api_key:
        logger.info("Semantic ScholarのAPIキーが未設定のため、関連論文調査バッチをスキップします")
        return

    asyncio.run(_run(settings, max_records=args.max_records))


if __name__ == "__main__":
    main()
