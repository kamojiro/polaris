"""日記ツール(get_diary_range/set_diary_mode、ADR-0013で chat_agent.py から分割).

日記モード中の記録自体(`record_diary_turn`)はチャットのtoolを経由しない(`services/diary.py`の
docstring参照、Decision 1)。しかしモードのON/OFF自体は、当初UIのトグルボタン専用としていたが、
チャットからも切り替えたいという要望があり、`exit_paper_mode`と同じ「state変更専用tool」
パターンで`set_diary_mode`を追加した(019-diary-domain research.md Decision 10)。日記モードには
論文モードのような「対象を特定する」概念が無い(ON/OFFの2値のみ)ため、論文モードのtool群とは
統合せず独立したtoolにする。

実機検証で、日記モードをチャットで切り替えられない設計だと、モデルが対応方法に迷い続けて
reasoning_tokensを大量消費し、`max_tokens`超過エラー("Model token limit (provider
default) exceeded")の一因になることを確認した。tool化するとその場でtool呼び出しに
短絡できるため、この問題も合わせて緩和される(`chat_agent.py`の`_CHAT_MODEL_SETTINGS`の
上限設定と併用)。

「今月」「先週」のような相対的な日付表現をLLMが正しくstart_date/end_dateへ変換できるよう、
動的instructionsで「今日の日付」を毎ターン伝える(実機検証で、これが無いと「今月」を
別の年月と誤解釈することを確認した)。
"""

from __future__ import annotations

import logging
from datetime import date  # noqa: TC003 - DiaryDayResultのフィールド型としてランタイムに解決される必要がある
from typing import TYPE_CHECKING

from pydantic import BaseModel

# RunContext/ChatDeps は get_diary_range 以外のtool/instructions(set_diary_mode、
# _today_instructions、_diary_mode_instructions)の引数の型注釈として使われ、
# pydantic-ai が実行時にシグネチャから解決する(`from __future__ import annotations`
# で文字列注釈になるため、TYPE_CHECKING ブロックに入れると実行時に解決できず
# NameError になる)。そのため ruff の TC001/TC002 は意図的に無視する。
from pydantic_ai import RunContext  # noqa: TC002

from polaris.agent.chat_state import ChatDeps  # noqa: TC001
from polaris.services.daily_summary import local_today

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from polaris.db.diary_repository import DiaryRepository
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

# get_diary_range が一度に読み込める期間の上限(日数)。get_paper_full_text と同種の
# 全文コンテキストtoolのため、広すぎる範囲によるコンテキスト肥大化を防ぐガード
# (research.md Decision 8)。
_MAX_DIARY_RANGE_DAYS = 62

INSTRUCTIONS = """\
- 「この日の日記を見せて」「先週の水曜どうだった」「今月の日記まとめて」のように過去の日記の
  内容について尋ねられたら get_diary_range で該当期間を取得してから答えてください。
  get_diary_range が「期間が広すぎる」旨のメッセージを返した場合、範囲を分割して何度も
  呼び出し直す(全期間を律儀に遡って調べる)のではなく、その旨をそのままユーザーに伝えて
  期間を絞ってもらってください。
- 「日記モードになって」「日記つけたい」のように言われたら set_diary_mode(enabled=True) を
  呼んでください。確認は不要です。「日記モード終了」「日記モードから抜けて」のように言われたら
  set_diary_mode(enabled=False) を呼んでください。日記モード中の会話内容自体は、あなたが
  何もしなくても裏側で自動的にその日の日記として記録されます(記録用の別toolはありません)。"""


class DiaryDayResult(BaseModel):
    """get_diary_range の1日分の結果."""

    entry_date: date
    content: str


class DiaryRangeResult(BaseModel):
    """get_diary_range の戻り値.

    実在する日のみを含む(無い日は含めない、`data-model.md`参照)。
    """

    entries: list[DiaryDayResult]


def register(agent: Agent[ChatDeps, str], diary_repo: DiaryRepository, *, settings: Settings) -> None:
    """get_diary_range・set_diary_mode ツールを登録する(019-diary-domain User Story 5、実運用フィードバックでの拡張)."""

    @agent.instructions
    def _today_instructions(ctx: RunContext[ChatDeps]) -> str:  # noqa: ARG001
        today = local_today(settings.daily_summary.timezone)
        return f"今日の日付は{today}です。get_diary_rangeで相対的な日付表現を解釈する際はこれを基準にしてください。"

    @agent.instructions
    def _diary_mode_instructions(ctx: RunContext[ChatDeps]) -> str | None:
        if not ctx.deps.state.diary_mode:
            return None
        return (
            "現在は「日記モード」中です。ユーザーの発言はあなたの応答とは別に、裏側で自動的に"
            "その日の日記として記録されています(あなたがtoolを呼ぶ必要はありません)。"
            "「日記として保存されません」のような誤った案内はしないでください。"
        )

    @agent.tool_plain
    def get_diary_range(start_date: date, end_date: date) -> DiaryRangeResult | str:
        """指定期間の日記エントリを返す(単日を見たい場合は start_date と end_date を同じ日にする).

        Args:
            start_date: 取得したい期間の開始日。
            end_date: 取得したい期間の終了日(この日を含む)。

        Returns:
            期間内に実在するエントリの一覧。期間が62日を超える場合は、その旨を伝える
            日本語メッセージ(範囲を絞るよう促す)。

        """
        logger.info("tool call: get_diary_range(start_date=%s, end_date=%s)", start_date, end_date)
        if (end_date - start_date).days > _MAX_DIARY_RANGE_DAYS:
            return f"指定期間が広すぎます。{_MAX_DIARY_RANGE_DAYS}日以内の範囲を指定してください。"
        records = diary_repo.list_records_in_range(start_date, end_date)
        return DiaryRangeResult(
            entries=[DiaryDayResult(entry_date=r.entry_date, content=r.content) for r in records]
        )

    @agent.tool
    def set_diary_mode(ctx: RunContext[ChatDeps], enabled: bool) -> str:
        """日記モードを開始/終了する(019-diary-domain).

        日記モード中の会話内容は、あなたがtoolを呼ばなくても裏側で自動的にその日の日記として
        記録される(このtoolはON/OFFの切り替えのみ担う)。

        Args:
            ctx: 実行コンテキスト(diary_modeのstateを保持)。
            enabled: Trueで日記モードを開始、Falseで終了。

        Returns:
            結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: set_diary_mode(enabled=%s)", enabled)
        ctx.deps.state.diary_mode = enabled
        if enabled:
            return "日記モードを開始しました。今日あったことを話してください。"
        return "日記モードを終了しました。"
