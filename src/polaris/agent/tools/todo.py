"""TODOツール(add_todo/list_todos/update_todo/complete_todo/delete_todo、ADR-0013で chat_agent.py から分割).

007-todo-domain で追加した。専用のエージェント/レジストリ(011-agent-registry)は
まだ無いため、既存の単一チャットエージェントにtoolを追加するだけに留めている
(YAGNI)。バケット分類(day/month/life)も専用のStructureステップを設けず、
LLMが add_todo の scale 引数をユーザーの自然文から直接選ぶ。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

# TodoScale は add_todo/list_todos/update_todo の引数の型注釈として使われ、
# pydantic-ai が実行時にシグネチャからスキーマを組み立てる(`from __future__ import
# annotations` で文字列注釈になるため、TYPE_CHECKING ブロックに入れると実行時に
# 解決できず NameError になる)。そのため ruff の TC001 は意図的に無視する。
from polaris.domain.entities import TodoScale  # noqa: TC001
from polaris.services.todo import build_todo_records

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from polaris.agent.chat_state import ChatDeps
    from polaris.db.todo_repository import TodoRepository
    from polaris.domain.entities import Item, TodoRecord

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
- TODO/やることを追加したい場合は add_todo を呼んでください。確認は不要です。
  scale はユーザーの表現から day(すぐ/明日まで等)/month(今月中等)/
  life(いつか/一生のうち等)を判断してください。迷ったら month にしてください。
- 「TODO一覧」「やることリスト」のように尋ねられたら list_todos を呼んでください。
  list_todos の結果は画面側で一覧表示されるため、あなたは結果を文章で列挙せず、
  「TODO一覧を表示しました」程度の一言だけ返してください。
- TODOの完了・編集・削除の指示があれば、対象のidが会話履歴から分からなければ
  先に list_todos で確認してから update_todo/complete_todo/delete_todo を
  呼んでください。"""


class TodoSummary(BaseModel):
    """一覧表示用のTODOサマリ."""

    id: str
    title: str
    description: str
    scale: TodoScale
    done: bool
    updated_at: datetime
    completed_at: datetime | None


class TodoListResult(BaseModel):
    """list_todos の戻り値."""

    todos: list[TodoSummary]


def _todo_summary(item: Item, record: TodoRecord) -> TodoSummary:
    return TodoSummary(
        id=item.id,
        title=item.title,
        description=item.summary,
        scale=record.scale,
        done=record.done,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


def register_read(agent: Agent[ChatDeps, str], todo_repo: TodoRepository) -> None:
    """add_todo/list_todos ツールを登録する(007-todo-domain)."""

    @agent.tool_plain
    def add_todo(title: str, scale: TodoScale, description: str = "") -> str:
        """新しいTODOを追加する.

        Args:
            title: TODOのタイトル。
            scale: 時間スケール(day=1日以内、month=1ヶ月以内、life=一生のうち)。
            description: 詳細メモ(任意)。

        Returns:
            保存結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: add_todo(title=%s, scale=%s)", title, scale)
        item, record = build_todo_records(title=title, scale=scale, description=description)
        todo_repo.save_todo(item, record)
        return f"TODOを追加しました({scale.value}): 『{title}』"

    @agent.tool_plain
    def list_todos(scale: TodoScale | None = None, include_done: bool = False) -> TodoListResult:
        """TODO一覧を返す(既定では未完了のみ、熟成度=最終更新日からの経過が長い順)."""
        logger.info("tool call: list_todos(scale=%s, include_done=%s)", scale, include_done)
        todos = [
            _todo_summary(item, record)
            for item, record in todo_repo.list_todos(scale=scale, include_done=include_done)
        ]
        return TodoListResult(todos=todos)


def register_write(agent: Agent[ChatDeps, str], todo_repo: TodoRepository) -> None:
    """update_todo/complete_todo/delete_todo ツールを登録する(007-todo-domain)."""

    @agent.tool_plain
    def update_todo(
        todo_id: str,
        title: str | None = None,
        description: str | None = None,
        scale: TodoScale | None = None,
    ) -> str:
        """既存TODOのタイトル・詳細メモ・時間スケールを更新する(指定したフィールドのみ変更).

        Args:
            todo_id: 対象TODOのid(list_todosの結果から取得できる)。
            title: 新しいタイトル(省略時は変更しない)。
            description: 新しい詳細メモ(省略時は変更しない)。
            scale: 新しい時間スケール(省略時は変更しない)。

        Returns:
            結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: update_todo(todo_id=%s)", todo_id)
        found = todo_repo.get_by_item_id(todo_id)
        if found is None:
            return f"TODO(id={todo_id})が見つかりませんでした。"
        item, record = found
        if title is not None:
            item.title = title
        if description is not None:
            item.summary = description
        if scale is not None:
            record.scale = scale
        record.updated_at = datetime.now(UTC)
        todo_repo.update_item(item)
        todo_repo.update_todo_record(record)
        return f"TODOを更新しました: 『{item.title}』"

    @agent.tool_plain
    def complete_todo(todo_id: str) -> str:
        """TODOを完了にする.

        Args:
            todo_id: 対象TODOのid(list_todosの結果から取得できる)。

        Returns:
            結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: complete_todo(todo_id=%s)", todo_id)
        found = todo_repo.get_by_item_id(todo_id)
        if found is None:
            return f"TODO(id={todo_id})が見つかりませんでした。"
        item, record = found
        now = datetime.now(UTC)
        record.done = True
        record.completed_at = now
        record.updated_at = now
        todo_repo.update_todo_record(record)
        return f"完了にしました: 『{item.title}』"

    @agent.tool_plain
    def delete_todo(todo_id: str) -> str:
        """TODOを削除する(物理削除、元に戻せない).

        Args:
            todo_id: 対象TODOのid(list_todosの結果から取得できる)。

        Returns:
            結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: delete_todo(todo_id=%s)", todo_id)
        found = todo_repo.get_by_item_id(todo_id)
        if found is None:
            return f"TODO(id={todo_id})が見つかりませんでした。"
        item, _record = found
        todo_repo.delete_todo(todo_id)
        return f"削除しました: 『{item.title}』"
