# 007. TODO管理ツール

## ステータス

✔️ 完了

## 概要

明確な締め切りのないタスクを、1日・1ヶ月・一生という異なる時間スケール(バケット)で管理する。論文ドメイン(001〜003、014)で固まった Hub/Satellite スキーマ・AG-UIチャットの型を横展開する。優先度は締切ではなく「最終更新日からの経過時間(熟成度)」から動的に算出する。

wishlist-design.md 3-3節ではリマインドと「現況調査エージェント」(定期的にWeb検索等でタスクの外部状況変化を確認する)も構想に含まれているが、**v1はスコープ外**とする(下記「v1のスコープ」参照)。

## v1のスコープ

- CRUD(追加・一覧・更新・完了・削除)+ 3バケット(day/month/life)分類のみ
- 優先度算出は「最終更新日からの経過時間」のみで行う。wishlist-design.md が挙げる「関連Interest」は `008-daily-digest-domain` で作られる予定の概念であり、v1時点ではまだ存在しないため依存しない
- リマインド機能・現況調査エージェントは対象外(将来別specとして切り出す。「未決定事項」参照)

## アーキテクチャ判断: 新規エージェントは作らない

wishlist-design.md の Layer2 構想では将来的にドメインごとのエージェントをレジストリで束ねる想定(`011-agent-registry`、未着手)だが、v1時点ではまだ論文ドメイン1つしか実装されておらず、レジストリを導入する理由がない(YAGNI、constitution 参照)。

そのため、TODOの各操作は新しいエージェントを作らず、既存の単一チャットエージェント(`agent/chat_agent.py` の `build_chat_agent`)に tool を追加する形で実装する。バケット分類(day/month/life)も専用のStructureステップを設けず、ユーザーの自然文からLLMが `add_todo` ツールの `scale` 引数を直接選ぶ(「明日までにやりたい」→`day`、「今月中に」→`month`、「いつかやりたい」→`life`)ことで賄う。

## データモデル追加

Hub/Satelliteパターンを踏襲し、論文ドメインの `PaperRecord` と対になる `TodoRecord` を追加する。

```python
class TodoScale(StrEnum):
    day = "day"
    month = "month"
    life = "life"


class TodoRecord(SQLModel, table=True):
    __tablename__ = "todo_records"

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True)
    scale: TodoScale
    done: bool = False
    updated_at: datetime   # 優先度算出(熟成度)の基準。編集・完了のたびに更新する
    completed_at: datetime | None = None
```

`ItemType` に `todo = "todo"` を追加する。TODOのタイトルは `Item.title`、詳細メモは既存の `Item.summary` を流用する(論文が `Item.summary` に要約を入れているのと同じ使い方)。

`Item` 自体には `updated_at` を追加しない(論文ドメインには不要なフィールドで、汎用hubに持たせると影響範囲が広がるため、TODO固有の `TodoRecord.updated_at` に閉じる)。

## ツール(chat_agent.pyに追加)

| ツール | 内容 |
|---|---|
| `add_todo(title, scale, description="")` | Item + TodoRecord を新規作成する。`updated_at` は作成時刻で初期化 |
| `list_todos(scale=None, include_done=False)` | バケットごとに、`updated_at` が古い順(熟成度が高い順)で一覧を返す。`scale` 指定時はそのバケットのみ |
| `update_todo(todo_id, title=None, description=None, scale=None)` | 指定フィールドのみ更新し、`updated_at` を現在時刻に更新する(熟成度のリセット) |
| `complete_todo(todo_id)` | `done=True`、`completed_at`・`updated_at` を現在時刻にする |
| `delete_todo(todo_id)` | Item/TodoRecordを削除する(物理削除。個人用途でCRUDの範囲、復元は対象外) |

`todo_id` の指定は、直前に `list_todos` の結果(会話履歴に構造化データとして残る)からLLMが該当項目のIDを拾って渡す想定。ユーザーがUUIDを直接入力する必要はない(論文一覧の`arxiv_id`と同じ考え方)。

## UI(generative UI)

`PaperList.tsx` と同じパターンで `TodoList.tsx` を新設する。`list_todos` の結果をLLMに文章で列挙させず、バケット(day/month/life)ごとにグルーピングした専用コンポーネントで表示する。v1では表示のみ(チェックボックス等の直接操作UIは持たず、完了・編集は引き続きチャットのテキストで行う。将来UIでの直接操作が欲しくなったら別途検討する)。

## 受け入れ条件

- 「明日までに〇〇をやりたい」のような自然文から `add_todo` が呼ばれ、`scale=day` のTODOが作成される
- 「今のTODOを見せて」で、day/month/lifeの3バケットに分かれた一覧がgenerative UIで表示される(LLMが文章で列挙しない)
- 作成から時間が経ったTODOほど一覧内で先頭に来る(熟成度順)
- 完了・更新・削除がそれぞれ動作し、`updated_at`/`completed_at` が正しく反映される

## 未決定事項(将来のspec)

- リマインド機能(スケジュールタスク機構との統合): 将来別specとして切り出す
- 現況調査エージェント(Web検索等でタスクの外部状況変化を定期確認): 将来別specとして切り出す。それまでの繋ぎとして、v1では「熟成度(最終更新日からの経過時間)」の一覧表示だけでも「長らく放置されているタスク」への気づきは得られる
- `008-daily-digest-domain` で Interest 概念ができた後、優先度算出にどう組み込むか

## 実装状況(2026-08-21)

✔️完了。

- `domain/entities.py` に `TodoScale`/`TodoRecord`/`ItemType.todo` を追加。新規テーブル追加のみで既存テーブルへの変更は無いため、既存`data/polaris.db`のマイグレーション不要。
- `db/todo_repository.py`(新規)に `TodoRepository` を実装(`PaperRepository`と同じSessionパターン)。
- `services/todo.py`(新規)に純関数 `build_todo_records` のみ配置(更新・完了・削除は`chat_agent.py`のtool内に直接記述、YAGNI)。
- `agent/chat_agent.py` に5つのtoolを追加。`build_chat_agent`本体の複雑度(ruffのC901/PLR0915)を超えたため、`_register_paper_tools`/`_register_todo_read_tools`/`_register_todo_write_tools`に登録処理を分割した。
- `frontend/src/TodoList.tsx`(新規)で3バケット表示、`App.tsx`の`findPaperListResults`は`findToolResults<T>`に一般化してTodo側でも再利用。
- 実LLM(GPU embedder込みでチャットエージェントを組み立て)で手動E2E確認済み: 自然文(「明日までに〇〇したい」「今月中に〇〇」「いつか〇〇したい」)から`add_todo`が正しい`scale`(day/month/life)で呼ばれること、`list_todos`の一言応答、直前の一覧結果を踏まえた`complete_todo`の自然文解決までを確認。

## 依存

- `002-papers-ingest-full` / `014-paper-url-pdf-ingest`(Hub/Satelliteパターン・チャットツールのパターンを流用)
