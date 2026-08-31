"""メインのチャットエージェント(ADR-0013: ドメインごとのtool登録は`agent/tools/`に分割済み).

各ドメインのtool・応答モデル・instructions断片は`agent/tools/<domain>.py`が持つ。
このファイルは`ChatDeps`/`ChatUIState`(実体は`.chat_state`、循環import回避のため
別モジュール、ここから再エクスポートする)と、各ドメインファイルを集めて
`build_chat_agent()`を組み立てるだけの薄い役割に留める(実行時のエージェント構成・
LLMへ渡る最終的なinstructionsの内容は分割前と変えていない)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai.common_tools.web_fetch import web_fetch_tool
from pydantic_ai.models.openrouter import OpenRouterModelSettings

from .chat_state import ChatDeps, ChatUIState
from .model import build_model
from .tools import diary, ir, memory, news, paper, paper_qa, todo, web_search

if TYPE_CHECKING:
    from polaris.adapters.embeddings import EmbeddingModel
    from polaris.agent.extract_ir_metadata import IrMetadataExtractor
    from polaris.agent.extract_metadata import PaperMetadataExtractor
    from polaris.agent.structure_paper import PaperStructurer
    from polaris.db.diary_repository import DiaryRepository
    from polaris.db.ir_repository import IrRepository
    from polaris.db.news_repository import NewsRepository
    from polaris.db.repository import PaperRepository
    from polaris.db.todo_repository import TodoRepository
    from polaris.settings import Settings

__all__ = ["ChatDeps", "ChatUIState", "build_chat_agent"]

_INSTRUCTIONS_HEADER = "あなたは個人用の論文管理・TODO管理アシスタントです。次のルールに従ってください。"
_INSTRUCTIONS_FOOTER = (
    "- 回答はツールの結果だけを根拠にし、推測で情報を補わないでください。\n- 日本語で簡潔に答えてください。"
)

_INSTRUCTIONS = (
    f"{_INSTRUCTIONS_HEADER}\n\n"
    f"{paper.INSTRUCTIONS}\n{todo.INSTRUCTIONS}\n{paper_qa.INSTRUCTIONS}\n{web_search.INSTRUCTIONS}\n"
    f"{news.INSTRUCTIONS}\n{ir.INSTRUCTIONS}\n{diary.INSTRUCTIONS}\n"
    f"{_INSTRUCTIONS_FOOTER}\n"
)

# メインのチャットエージェントは(他の構造化抽出系エージェントと違い)reasoningを無効化しない
# ままにしているが、上限を設けないと「対応手段の無い要求」に対してモデルが延々と思考し続け、
# 1ターンの完了トークン予算(OpenRouterのprovider default、明示しないとルーティング先の
# プロバイダごとに変動しうる)をreasoningだけで使い切り、"Model token limit (provider default)
# exceeded before any response was generated" という応答すら生成されないエラーになることを
# 実機検証で確認した(2026-08-31、set_diary_modeツール追加のきっかけになった不具合)。
# reasoning自体は複雑な判断に必要なため無効化せず、予算に上限だけ設けて歯止めをかける。
_CHAT_MODEL_SETTINGS = OpenRouterModelSettings(
    max_tokens=8000,
    openrouter_reasoning={"max_tokens": 3000},
)


def build_chat_agent(
    settings: Settings,
    repo: PaperRepository,
    *,
    embedder: EmbeddingModel,
    structurer: PaperStructurer,
    extractor: PaperMetadataExtractor,
    todo_repo: TodoRepository,
    news_repo: NewsRepository,
    ir_repo: IrRepository,
    ir_extractor: IrMetadataExtractor,
    diary_repo: DiaryRepository,
) -> Agent[ChatDeps, str]:
    """設定とリポジトリ・Embedding/Structure/メタデータ抽出・TODO/ニュース/IR/日記リポジトリ依存からチャットエージェントを組み立てる."""
    model = build_model(settings)
    # web_fetch はpydantic-ai同梱のツール(SSRF対策済みhttps取得+markdown変換)。
    # 具体的なURLの内容を尋ねられたとき、web_searchで近似せず直接読ませるために使う
    # (008拡張のニュースサイドバー「クリックで詳しく教えて」導線での実運用から着想)。
    agent = Agent(
        model,
        deps_type=ChatDeps,
        instructions=_INSTRUCTIONS,
        tools=[web_fetch_tool()],
        model_settings=_CHAT_MODEL_SETTINGS,
    )
    memory.register(agent)
    paper.register(
        agent,
        repo,
        settings=settings,
        embedder=embedder,
        structurer=structurer,
        extractor=extractor,
    )
    todo.register_read(agent, todo_repo)
    todo.register_write(agent, todo_repo)
    paper_qa.register(agent, repo, settings=settings)
    web_search.register(agent, settings=settings)
    news.register(agent, news_repo)
    ir.register(agent, ir_repo, settings=settings, ir_extractor=ir_extractor)
    diary.register(agent, diary_repo, settings=settings)
    return agent
