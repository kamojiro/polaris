"""チャット長期記憶(017-chat-memory)の抽出・書き直し(後処理段).

2つの狭いタスクをまとめて置く(常にセットで呼ばれるため):

1. 分類+抽出: 直近のやり取りが記憶に値するか判定し、値するなら既存テーマ/新規テーマの
   どちらかに分類して短い記述(raw_text)を作る
2. 書き直し: 対象テーマの全ログ(raw_textの集合)から、現在状態ファイルの全文を合成する
   (event sourcing の materialized view を作り直す)

`承認ゲート方式は採用しない`(spec)。「記憶に値するか」の判断自体をこのLLM呼び出しに
担わせることで、不要な内容を記録しない防波堤にする。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModelSettings

from .model import build_model

if TYPE_CHECKING:
    from collections.abc import Sequence

    from polaris.settings import Settings

_EXTRACT_INSTRUCTIONS = """\
あなたはチャットの長期記憶システムの一部として、直近のやり取りが将来の会話でも
参照する価値のある知識かどうかを判定し、値するなら抽出するアシスタントです。

- 単なる挨拶・雑談・その場限りの作業指示(「これを保存して」等)は記憶に値しません。
  worth_remembering は false にし、他のフィールドは省略してください
- 「ローカルLLMをRTX 2060 SUPERで動かしている」「Macを使っている」のような、繰り返し
  話題に上がりそうな継続的な知識・状況・好みは記憶に値します
- 記憶に値する場合、既存テーマ一覧のいずれかに合致すればその slug を theme_slug に、
  is_new_theme は false にしてください
- 既存テーマのどれにも合致しなければ、新しいテーマとして slug(英数字とハイフンのみ、
  簡潔に)と一行説明を作り、is_new_theme を true にしてください
- content には、このやり取りから学んだ内容を1〜2文程度の日本語で簡潔に記述してください
  (会話をそのまま引用するのではなく、記憶として蓄積すべき事実だけを抜き出す)
"""

_REWRITE_INSTRUCTIONS = """\
あなたはチャットの長期記憶システムの一部として、あるテーマについて蓄積された記録
(時系列順)から、そのテーマの「現在の理解」をまとめたMarkdown文書を1つ作るアシスタントです。

- 出力はMarkdown本文のみ(見出し等は自由に使ってよい)
- 時系列の記録を単純に列挙するのではなく、矛盾があれば新しい情報を優先し、
  重複や古くなった内容は統合・削除して、今の状態を過不足なく表す文書にしてください
- 簡潔に。冗長な前置きや結びの言葉は不要です
"""

_MEMORY_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class ExtractionResult(BaseModel):
    """分類+抽出ステップの出力."""

    worth_remembering: bool
    theme_slug: str | None = None
    is_new_theme: bool = False
    theme_description: str | None = None
    content: str | None = None


class MemoryExtractor(Protocol):
    """ExtractionResult を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def extract(
        self, *, user_text: str, assistant_text: str, themes: Sequence[tuple[str, str]]
    ) -> ExtractionResult:
        """直近のやり取りとテーマ一覧から、記憶に値するかどうかと抽出内容を判定する."""
        ...


class MemoryRewriter(Protocol):
    """現在状態ファイルの全文を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def rewrite(self, *, theme_description: str, raw_texts: Sequence[str]) -> str:
        """テーマの説明と時系列の記録から、現在状態ファイルの全文を合成する."""
        ...


def build_memory_extract_agent(settings: Settings) -> Agent[None, ExtractionResult]:
    """設定値から分類+抽出用の pydantic-ai エージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=ExtractionResult,
        instructions=_EXTRACT_INSTRUCTIONS,
        model_settings=_MEMORY_MODEL_SETTINGS,
    )


def build_memory_rewrite_agent(settings: Settings) -> Agent[None, str]:
    """設定値から書き直し用の pydantic-ai エージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=str,
        instructions=_REWRITE_INSTRUCTIONS,
        model_settings=_MEMORY_MODEL_SETTINGS,
    )


def _format_themes(themes: Sequence[tuple[str, str]]) -> str:
    if not themes:
        return "(テーマなし)"
    return "\n".join(f"- {slug}: {description}" for slug, description in themes)


class AgentMemoryExtractor:
    """pydantic-ai エージェントをラップした MemoryExtractor 実装."""

    def __init__(self, agent: Agent[None, ExtractionResult]) -> None:
        """分類+抽出エージェントを受け取って初期化する."""
        self._agent = agent

    async def extract(
        self, *, user_text: str, assistant_text: str, themes: Sequence[tuple[str, str]]
    ) -> ExtractionResult:
        """直近のやり取りとテーマ一覧をプロンプトにまとめてエージェントを実行する."""
        prompt = (
            f"テーマ一覧:\n{_format_themes(themes)}\n\n"
            f"直近のやり取り:\nユーザー: {user_text}\nアシスタント: {assistant_text}"
        )
        result = await self._agent.run(prompt)
        return result.output


class AgentMemoryRewriter:
    """pydantic-ai エージェントをラップした MemoryRewriter 実装."""

    def __init__(self, agent: Agent[None, str]) -> None:
        """書き直しエージェントを受け取って初期化する."""
        self._agent = agent

    async def rewrite(self, *, theme_description: str, raw_texts: Sequence[str]) -> str:
        """テーマの説明と時系列の記録をプロンプトにまとめてエージェントを実行する."""
        history = "\n".join(f"- {text}" for text in raw_texts)
        prompt = f"テーマ: {theme_description}\n\n時系列の記録:\n{history}"
        result = await self._agent.run(prompt)
        return result.output
