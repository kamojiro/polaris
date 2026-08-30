"""日記ドメイン(019-diary-domain)のオーケストレーション.

`api/app.py`のADR-0003後処理段(`on_complete`)から、`deps.state.diary_mode`が`True`の
ターンについて呼ばれる想定。`services/memory.py`と同じ「repoとagentを受け取って組み立てる」
パターンだが、「記憶に値するか」の判定ステップ(017の`extract`)は無い(research.md Decision 3)。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from polaris.domain.entities import DiaryEvent, DiaryRecord, Item, ItemType
from polaris.services.daily_summary import local_today

if TYPE_CHECKING:
    from datetime import date

    from polaris.agent.diary_rewrite import DiaryRewriter
    from polaris.db.diary_repository import DiaryRepository
    from polaris.settings import Settings

_SUMMARY_EXCERPT_CHARS = 80


def _format_turn(user_text: str, assistant_text: str) -> str:
    return f"ユーザー: {user_text}\nアシスタント: {assistant_text}"


async def record_diary_turn(
    user_text: str,
    assistant_text: str,
    *,
    turn_id: str,
    rewriter: DiaryRewriter,
    repo: DiaryRepository,
    settings: Settings,
    target_date: date | None = None,
) -> None:
    """日記モード中の1ターンをログに追記し、その日のエントリを書き直す.

    日記モード中の会話は無条件に記録対象(FR-002/FR-008、017のような選別ステップは無い)。
    `target_date`は`DiaryDateInferrer`(呼び出し元)が会話文面から推定した過去日で、指定されれば
    その日を対象にする(バックフィル、User Story 4)。指定が無ければ当日を対象にする。
    """
    entry_date = target_date if target_date is not None else local_today(settings.daily_summary.timezone)
    now = datetime.now(UTC)
    repo.append_event(
        DiaryEvent(
            id=uuid.uuid4().hex,
            entry_date=entry_date,
            recorded_at=now,
            source_conversation_turn=turn_id,
            raw_text=_format_turn(user_text, assistant_text),
        )
    )

    events = repo.list_events(entry_date)
    content = await rewriter.rewrite(raw_texts=[e.raw_text for e in events])

    existing = repo.get_record(entry_date)
    item_id = existing.item_id if existing is not None else uuid.uuid4().hex
    item = Item(
        id=item_id,
        item_type=ItemType.diary,
        title=f"{entry_date}の日記",
        summary=content[:_SUMMARY_EXCERPT_CHARS],
        created_at=now,
        source_ref=f"diary:{entry_date}",
    )
    record = DiaryRecord(
        id=existing.id if existing is not None else uuid.uuid4().hex,
        item_id=item_id,
        entry_date=entry_date,
        content=content,
        updated_at=now,
    )
    repo.upsert_record(item, record)
