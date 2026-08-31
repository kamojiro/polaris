"""IR文書ツール(save_ir_document/get_ir_full_text/list_ir_documents、ADR-0013で chat_agent.py から分割).

013-ir-analysis-domain で追加した。EDINETから取り込んだ有価証券報告書等を
015(論文QA)と同じ「全文をそのままコンテキストに渡す」方式で扱うが、論文モードのような
state駆動の動的instructions・モード終了toolは持たない(spec「未決定事項」で
v1は見送りと明記されているため、YAGNI)。要約・QAが投資助言(売買判断等)に
踏み込まないよう、指示文に明記して回答を事実の整理に留めさせる。
"""

from __future__ import annotations

import logging
from datetime import date, datetime  # noqa: TC003 - IrSummaryのフィールド型としてランタイムに解決される必要がある
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel

from polaris.services.ingest_ir import ingest_ir_document
from polaris.services.ir_full_text import load_ir_full_text
from polaris.services.progress import set_progress

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from polaris.agent.chat_state import ChatDeps
    from polaris.agent.extract_ir_metadata import IrMetadataExtractor
    from polaris.db.ir_repository import IrRepository
    from polaris.domain.entities import IrRecord, Item
    from polaris.services.ir_full_text import IrFullText
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

# 一覧表示の上限(_RECENT_PAPERS_LIMITと同じ理由)。
_RECENT_IR_LIMIT = 20

INSTRUCTIONS = """\
- ユーザーのメッセージにEDINETの書類管理番号(`S100XXXX`のような形式のdocID)が
  含まれていたら、必ず save_ir_document ツールを呼び出して保存してください。確認は不要です。
  save_ir_document の結果に含まれる要約は省略せずそのままユーザーに伝えてください。
- 「保存したIR文書」「有価証券報告書の一覧」のように尋ねられたら list_ir_documents ツールを
  呼び出してください。list_ir_documents の結果は画面側で一覧表示されるため、あなたは結果を
  文章で列挙せず、「保存済みのIR文書一覧を表示しました」程度の一言だけ返してください。
- 特定のIR文書の内容について質問されたら(「〇〇社の有価証券報告書の売上は?」等)、まず
  get_ir_full_text で全文を会話に取り込んでから答えてください。同じ文書について続けて
  質問された場合、全文は既に会話履歴に残っているのでツールを再度呼ぶ必要はありません。
- IR文書に関する要約・QAは、書かれている事実の整理に徹してください。「株を買うべきか」
  「今が売り時か」等の投資助言(売買判断・価格予想)を求められても、判断そのものは
  行わず、事実の整理に留める旨を答えてください。"""


class IrSummary(BaseModel):
    """一覧表示用のIR文書サマリ."""

    filer_name: str
    doc_type_code: str | None
    period_start: date | None
    period_end: date | None
    submit_datetime: datetime
    doc_id: str


class IrListResult(BaseModel):
    """list_ir_documents の戻り値.

    `documents` は直近 `_RECENT_IR_LIMIT` 件のみ、`total_count` は保存済みの
    総件数(list_papers/PaperListResultと同じ形)。
    """

    documents: list[IrSummary]
    total_count: int


def _format_ir_full_text(item: Item, record: IrRecord, full_text: IrFullText) -> str:
    """get_ir_full_text の戻り値を組み立てる(ヘッダ+本文)."""
    header = f"# 『{item.title}』(提出者: {record.filer_name}, doc_id: {record.doc_id})"
    truncated_note = "\n(全文が長いため先頭部分のみ表示しています)" if full_text.truncated else ""
    return f"{header}{truncated_note}\n---\n{full_text.text}"


def register(
    agent: Agent[ChatDeps, str],
    ir_repo: IrRepository,
    *,
    settings: Settings,
    ir_extractor: IrMetadataExtractor,
) -> None:
    """save_ir_document/get_ir_full_text/list_ir_documents ツールを登録する(013-ir-analysis-domain)."""
    http_client = httpx.AsyncClient()

    @agent.tool_plain
    async def save_ir_document(doc_id: str) -> str:
        """EDINETのdocID(書類管理番号)からIR文書(有価証券報告書等)のPDFを取得し保存する.

        Args:
            doc_id: EDINETの書類管理番号(例: S100XXXX)。

        Returns:
            保存結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: save_ir_document(doc_id=%s)", doc_id)
        result = await ingest_ir_document(
            doc_id,
            repo=ir_repo,
            http_client=http_client,
            extractor=ir_extractor,
            settings=settings,
        )
        status = "新規に保存しました" if result.created else "既に保存済みでした"
        return f"{status}: 『{result.item.title}』(doc_id: {result.record.doc_id})\n\n要約: {result.item.summary}"

    @agent.tool_plain
    def list_ir_documents() -> IrListResult:
        """保存済みのIR文書一覧を直近分だけ返す(総件数も併せて返す)."""
        logger.info("tool call: list_ir_documents()")
        documents = [
            IrSummary(
                filer_name=record.filer_name,
                doc_type_code=record.doc_type_code,
                period_start=record.period_start,
                period_end=record.period_end,
                submit_datetime=record.submit_datetime,
                doc_id=record.doc_id,
            )
            for _item, record in ir_repo.list_ir_documents(limit=_RECENT_IR_LIMIT)
        ]
        return IrListResult(documents=documents, total_count=ir_repo.count_ir_documents())

    @agent.tool_plain
    async def get_ir_full_text(query: str) -> str:
        """保存済みIR文書の本文全文を取得し、会話に取り込む.

        Args:
            query: 対象IR文書を指す文字列(企業名の一部、またはEDINETのdocID)。

        Returns:
            IR文書の本文全文(見つからない/複数該当する場合はその旨の日本語メッセージ)。

        """
        logger.info("tool call: get_ir_full_text(query=%s)", query)
        matches = ir_repo.search_ir_documents(query)
        if not matches:
            return (
                f"'{query}' に該当するIR文書が見つかりませんでした。"
                "list_ir_documents で保存済みの文書を確認してください。"
            )
        if len(matches) > 1:
            names = "、".join(f"『{item.title}』" for item, _record in matches)
            return f"複数のIR文書が該当しました: {names}。どの文書か、企業名をもう少し詳しく指定してください。"

        item, record = matches[0]
        set_progress("stage", "IR文書の全文を読み込み中…")
        try:
            full_text = await load_ir_full_text(item, record, max_chars=settings.chat.max_full_text_chars)
        finally:
            set_progress("stage", None)
        return _format_ir_full_text(item, record, full_text)
