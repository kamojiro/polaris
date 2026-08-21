"""arXiv 以外(URL直リンク・ローカルPDF)から取り込んだ論文の書誌情報・要約を抽出する.

arXiv 経由は arXiv API から title/abstract が得られるため `structure_paper.py`
(title/abstractを入力として要約・venueだけを生成)で足りるが、非arXivは
そもそも title/abstract が無い。本文冒頭のテキストから LLM 1回で
title/authors/year/abstract/doi/venue と summary をまとめて生成する
(014-paper-url-pdf-ingest)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModelSettings

from .model import build_model

if TYPE_CHECKING:
    from polaris.settings import Settings

_INSTRUCTIONS = """\
あなたは学術論文のメタデータを整理するアシスタントです。
論文PDFの冒頭部分のテキストが渡されるので、そこから書誌情報を抜き出してください。

- title: 論文タイトル
- authors: 著者名のリスト(読み取れなければ空リスト)
- year: 発表年(西暦4桁の数値。読み取れなければ null)
- abstract: Abstract(要旨)の本文。無ければ本文冒頭から要旨に相当する部分を短く引用する
- doi: DOIが明記されていれば記入、無ければ null
- venue: 掲載先の会議・ジャーナル名が明確に読み取れる場合のみ記入し、分からなければ null
- summary: 日本語で3〜5文程度の簡潔な要約

読み取れない項目は推測で埋めず、null または空リストにしてください。
"""


# structure_paper.py と同じ理由(構造化出力が安定して返れば十分で reasoning は不要)で
# 明示的に無効化する。
_EXTRACT_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class ExtractedPaper(BaseModel):
    """メタデータ抽出ステップの出力."""

    title: str
    authors: list[str]
    year: int | None
    abstract: str
    doi: str | None
    venue: str | None
    summary: str


class PaperMetadataExtractor(Protocol):
    """ExtractedPaper を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def extract(self, *, body_head: str) -> ExtractedPaper:
        """本文冒頭のテキストから書誌情報・要約を生成する."""
        ...


def build_extract_metadata_agent(settings: Settings) -> Agent[None, ExtractedPaper]:
    """設定値からメタデータ抽出用の pydantic-ai エージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=ExtractedPaper,
        instructions=_INSTRUCTIONS,
        model_settings=_EXTRACT_MODEL_SETTINGS,
    )


class AgentPaperMetadataExtractor:
    """pydantic-ai エージェントをラップした PaperMetadataExtractor 実装."""

    def __init__(self, agent: Agent[None, ExtractedPaper]) -> None:
        """メタデータ抽出エージェントを受け取って初期化する."""
        self._agent = agent

    async def extract(self, *, body_head: str) -> ExtractedPaper:
        """本文冒頭のテキストをプロンプトにしてエージェントを実行する."""
        result = await self._agent.run(body_head)
        return result.output
