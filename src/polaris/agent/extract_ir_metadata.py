"""EDINETから取り込んだIR文書(有価証券報告書等)の書誌情報・要約を抽出する(013-ir-analysis-domain).

`agent/extract_metadata.py`(非arXiv論文の書誌情報抽出)と同じProtocol+Agentパターンを
踏襲するが、フィールドはIR文書固有(企業名/書類種別/対象期間/要約)にしたため
再利用ではなく新規に書く。要約は投資助言そのものにならないよう「書かれている事実の整理」に
留める注意をinstructionsに明記する(spec「背景・判断」参照。chat_agent.py側の
_INSTRUCTIONSにも同様の注意を重ねて入れており、要約生成・QA両方の入口で守らせる)。
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
あなたは、EDINET(金融庁の開示書類システム)から取得した有価証券報告書等のPDFの
書誌情報を整理するアシスタントです。文書冒頭部分のテキストが渡されるので、
そこから情報を抜き出してください。

- filer_name: 提出者名(企業名)
- edinet_code: EDINETコード(6桁の英数字、例: E01234)。読み取れなければ null
- doc_type_code: 有価証券報告書/四半期報告書/半期報告書等の書類種別が分かる場合は
  その名称を短く記入(例: "有価証券報告書")。分からなければ null
- period_start: 対象期間の開始日(ISO 8601形式、例: "2025-04-01")。読み取れなければ null
- period_end: 対象期間の終了日(ISO 8601形式)。読み取れなければ null
- submit_datetime: 表紙に記載されている提出日(例: "令和6年6月27日提出"のような表記)を
  ISO 8601形式の日付(例: "2024-06-27")に変換して記入。読み取れなければ null
- summary: 日本語で3〜5文程度の簡潔な要約。書かれている事実の整理に徹し、
  「買うべきか」「投資に値するか」等の投資判断・価格予想には一切踏み込まないこと

読み取れない項目は推測で埋めず、null にしてください。
"""


# extract_metadata.py と同じ理由(構造化出力が安定して返れば十分でreasoningは不要)で
# 明示的に無効化する。
_EXTRACT_MODEL_SETTINGS = OpenRouterModelSettings(
    openrouter_reasoning={"enabled": False},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


class ExtractedIrDocument(BaseModel):
    """IR文書メタデータ抽出ステップの出力."""

    filer_name: str
    edinet_code: str | None
    doc_type_code: str | None
    period_start: str | None
    period_end: str | None
    submit_datetime: str | None
    summary: str


class IrMetadataExtractor(Protocol):
    """ExtractedIrDocument を生成する抽象(テスト時にフェイクへ差し替えるため)."""

    async def extract(self, *, body_head: str) -> ExtractedIrDocument:
        """本文冒頭のテキストから書誌情報・要約を生成する."""
        ...


def build_extract_ir_metadata_agent(settings: Settings) -> Agent[None, ExtractedIrDocument]:
    """設定値からIR文書メタデータ抽出用の pydantic-ai エージェントを組み立てる(reasoningは無効化)."""
    return Agent(
        build_model(settings),
        output_type=ExtractedIrDocument,
        instructions=_INSTRUCTIONS,
        model_settings=_EXTRACT_MODEL_SETTINGS,
    )


class AgentIrMetadataExtractor:
    """pydantic-ai エージェントをラップした IrMetadataExtractor 実装."""

    def __init__(self, agent: Agent[None, ExtractedIrDocument]) -> None:
        """IR文書メタデータ抽出エージェントを受け取って初期化する."""
        self._agent = agent

    async def extract(self, *, body_head: str) -> ExtractedIrDocument:
        """本文冒頭のテキストをプロンプトにしてエージェントを実行する."""
        result = await self._agent.run(body_head)
        return result.output
