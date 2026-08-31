"""chat_agentの完了トークン予算(`_CHAT_MODEL_SETTINGS`)の実LLM回帰テスト.

`llm`マーカー(既定では除外、`uv run nox -s test_llm`で明示実行、`pyproject.toml`参照)。

2026-08-31、`_CHAT_MODEL_SETTINGS`の`max_tokens`を8000に設定した際、「表形式で詳しく
比較して」のような正当に長い応答が必要な質問でも
"Model token limit exceeded before any response was generated"エラーで応答生成自体が
失敗する不具合が実機で発生した(`specs/019-diary-domain/research.md` Decision 11の
「実装時の訂正」参照)。原因は`openrouter_reasoning.max_tokens`がAnthropicの
`budget_tokens`のような厳密なハード上限ではなく、OpenRouter経由のオープンウェイト
モデルに対してはソフトな目安に留まること(reasoningだけで設定値を超えて消費しうる)。
フェイクでは再現できない、実際のreasoning/出力トークン消費量に依存する不具合のため、
実LLM呼び出しでこの種の質問が完了することを確認する。

初版(2026-09-01)は`build_chat_agent()`を経由せずbare Agentに`_INSTRUCTIONS`だけを
渡していたが、それだと`_INSTRUCTIONS`が言及するweb_search等のtoolが実際には
登録されておらず、モデルが「toolを呼び出したつもり」のJSON文字列をテキスト出力として
返してしまい(本来toolを実際に呼べば起きない現象)、意図と無関係な理由で失敗した。
`tests/services/test_ingest_paper.py`と同じフェイクEmbedder/Structurer/Extractorパターンで
実際に`build_chat_agent()`を組み立て、本番と同じtool群(web_search含む)を登録した上で
検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from polaris.agent.chat_agent import build_chat_agent
from polaris.agent.chat_state import ChatDeps, ChatUIState
from polaris.agent.extract_ir_metadata import ExtractedIrDocument
from polaris.agent.extract_metadata import ExtractedPaper
from polaris.agent.structure_paper import StructuredPaper
from polaris.db.diary_repository import DiaryRepository
from polaris.db.ir_repository import IrRepository
from polaris.db.news_repository import NewsRepository
from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.db.todo_repository import TodoRepository
from polaris.settings import IngestSettings, Settings

pytestmark = pytest.mark.llm

_EMBEDDING_DIM = 4
_LONG_ANSWER_PROMPT = (
    "大阪でつけ麺食べたいんだけど、有名店を5つくらい挙げて、それぞれの特徴と選び方の"
    "ポイントを詳しく表形式で整理して説明して"
)
# 空応答や極端な短文(エラーメッセージ相当)ではないことだけを確認する最低限のしきい値。
_MIN_OUTPUT_CHARS = 200


class _FakeEmbedder:
    """使われない想定のフェイク Embedding モデル(save_paperを呼ばないため未呼び出しで終わる)."""

    model_id = "fake-embedder"

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """テキスト数と同じ数だけ固定ベクトルを返す(このテストでは呼ばれない想定)."""
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


class _FakeStructurer:
    """使われない想定のフェイク Structure エージェント."""

    async def structure(self, *, title: str, abstract: str, comment: str | None) -> StructuredPaper:  # noqa: ARG002
        return StructuredPaper(summary=f"要約: {title}", venue=None)


class _FakeExtractor:
    """使われない想定のフェイク 論文メタデータ抽出エージェント."""

    async def extract(self, *, body_head: str) -> ExtractedPaper:  # noqa: ARG002
        return ExtractedPaper(
            title="Fake Paper Title", authors=["Fake Author"], year=2024,
            abstract="fake abstract", doi=None, venue=None, summary="要約: Fake Paper Title",
        )


class _FakeIrExtractor:
    """使われない想定のフェイク IR文書メタデータ抽出エージェント."""

    async def extract(self, *, body_head: str) -> ExtractedIrDocument:  # noqa: ARG002
        return ExtractedIrDocument(
            filer_name="Fake Filer", edinet_code=None, doc_type_code=None,
            period_start=None, period_end=None, submit_datetime=None, summary="要約: Fake Filer",
        )


async def test_chat_model_settings_allow_long_structured_answer(tmp_path: Path) -> None:
    """`_CHAT_MODEL_SETTINGS`の完了トークン上限が、正当に長い応答を妨げないことを確認する.

    本番と同じ`build_chat_agent()`(web_search等の実toolを含む)で組み立てたエージェントに
    長文が必要な質問を投げ、"Model token limit exceeded"にならず完了することを確認する。
    """
    engine = create_db_engine(str(tmp_path / "test.db"), embedding_dim=_EMBEDDING_DIM)
    settings = Settings(ingest=IngestSettings(embedding_dim=_EMBEDDING_DIM))
    agent = build_chat_agent(
        settings,
        PaperRepository(engine),
        embedder=_FakeEmbedder(),
        structurer=_FakeStructurer(),
        extractor=_FakeExtractor(),
        todo_repo=TodoRepository(engine),
        news_repo=NewsRepository(engine),
        ir_repo=IrRepository(engine),
        ir_extractor=_FakeIrExtractor(),
        diary_repo=DiaryRepository(engine),
    )
    deps = ChatDeps(state=ChatUIState())

    result = await agent.run(_LONG_ANSWER_PROMPT, deps=deps)

    assert len(result.output) > _MIN_OUTPUT_CHARS
