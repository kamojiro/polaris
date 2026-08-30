# Phase 1 Data Model: 日記ドメイン(diary-domain)

`research.md`の決定を踏まえた確定版。`spec.draft.md`のたたき台をベースに、ログ層(`DiaryEvent`)を
追加した点が主な差分。

## エンティティ

### Item(既存ハブ、拡張)

`domain/entities.py`の`ItemType` StrEnumに`diary = "diary"`を追加する(既存の
`paper`/`todo`/`ir_document`と並ぶ4つ目)。

- `title`: `f"{entry_date}の日記"`程度の機械生成(rewriterの出力から流用はしない、一覧表示用の
  識別子として安定させるため)
- `summary`: rewrite後の本文の冒頭抜粋、または空文字列(v1では一覧UI自体が範囲外のため厳密な
  要否は実装時に判断してよい)

### DiaryRecord(satellite、現在状態層)

```python
class DiaryRecord(SQLModel, table=True):
    __tablename__ = "diary_records"

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True)
    entry_date: date = Field(index=True, unique=True)  # 1日1エントリ、JST基準(research.md Decision 5)
    content: str        # rewriter(LLM)が都度書き直す日記本文
    updated_at: datetime
```

`spec.draft.md`のたたき台と同一。「1日1エントリ」という制約は`entry_date`のunique制約で担保する
(`023-daily-summary-notification`の`DailySummaryRecord.summary_date`と同じ形)。

### DiaryEvent(log layer、追記のみ)

```python
class DiaryEvent(SQLModel, table=True):
    __tablename__ = "diary_events"

    id: str = Field(primary_key=True)
    entry_date: date = Field(index=True)          # DiaryRecord.entry_dateと同じ基準
    recorded_at: datetime
    source_conversation_turn: str                  # AG-UIメッセージid(トレーサビリティ用、MemoryEventと同型)
    raw_text: str                                   # このターンのuser発言+assistant応答の要約的な生テキスト
```

`domain/entities.py`の`MemoryEvent`と同じ形。`theme: str`が`entry_date: date`に置き換わる点のみ異なる
(グルーピングキーがテーマではなく日付、`spec.draft.md`の背景・判断で既に決定済み)。

## Repository: `DiaryRepository`(新規、`db/diary_repository.py`)

`MemoryRepository`/`DailySummaryRepository`と同じ「メソッドごとにSessionを開く」パターン。

```python
class DiaryRepository:
    def __init__(self, engine: Engine) -> None: ...

    def append_event(self, event: DiaryEvent) -> None: ...
    def list_events(self, entry_date: date) -> list[DiaryEvent]: ...

    def get_record(self, entry_date: date) -> DiaryRecord | None: ...
    def upsert_record(self, item: Item, record: DiaryRecord) -> None:
        """entry_dateでupsertする(MemoryRepository.upsert_themeと同じ考え方、
        1日目はItem+DiaryRecordを新規作成、2回目以降はcontent/updated_atのみ更新)."""
```

## 状態遷移(AG-UI state)

`research.md` Decision 4のとおり、`agent/chat_agent.py`の`PaperModeState`を`ChatUIState`に改名し、
以下の形にする。

```python
class ChatUIState(BaseModel):
    active_paper: ActivePaper | None = None
    diary_mode: bool = False
```

- **ON→OFF/OFF→ON**: フロントの`useChatAgent.ts`から`agent.setState({...current, diary_mode: True/False})`
  で即座に切り替わる(015の`exitPaperMode`と同じ、LLMのターンを挟まない)
- **サーバー側の参照**: `api/app.py`の`on_complete`が`deps.state.diary_mode`を見て、`True`なら
  `_extract_diary_task`をfire-and-forgetで起動する(`_extract_memory_task`と並列に追加)
- **状態の永続化**: `diary_mode`自体はAG-UI stateのみで管理し、DBには保存しない(セッションを
  またいで記憶する必要はない、`active_paper`が既にそうなっているのと同じ扱い)

## バリデーションルール

- `DiaryRecord.entry_date`は一意(`FR-004`: 同じ日に複数回出入りしても1エントリ)
- `DiaryEvent`は`entry_date`昇順ではなく`recorded_at`昇順で`rewrite`に渡す(会話が起きた順序を
  保つため。`MemoryEvent`が`extracted_at`ではなく素朴にリスト順で渡している箇所と挙動を揃える)
