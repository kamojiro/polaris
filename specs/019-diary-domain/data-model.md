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

## Repository: `DiaryRepository`(`db/diary_repository.py`、拡張)

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

    # User Story 5(research.md Decision 8): 期間指定の読み取り
    def list_records_in_range(self, start_date: date, end_date: date) -> list[DiaryRecord]:
        """entry_date BETWEEN start_date AND end_dateのDiaryRecordをentry_date昇順で返す."""

    # User Story 6(research.md Decision 9): 執筆中パネル用
    def get_latest_updated_record(self) -> DiaryRecord | None:
        """updated_at降順の先頭(アンカー)を返す(無ければNone)."""

    def list_records_before(self, entry_date: date, *, limit: int) -> list[DiaryRecord]:
        """entry_date未満のDiaryRecordをentry_date降順でlimit件返す(アンカーの前後文脈用)."""
```

### `record_diary_turn`の拡張(User Story 4、`services/diary.py`)

```python
async def record_diary_turn(
    user_text: str,
    assistant_text: str,
    *,
    turn_id: str,
    rewriter: DiaryRewriter,
    repo: DiaryRepository,
    settings: Settings,
    target_date: date | None = None,  # 追加: DiaryDateInferrerが推定した過去日(推定できなければNone)
) -> None:
    """target_dateが指定されればそのentry_dateを、Noneならlocal_today()を対象にする.
    それ以外のロジック(DiaryEvent追記→当日の全イベントをrewrite→upsert)は変更なし。"""
```

### 日付推定エージェント `DiaryDateInferrer`(User Story 4、`agent/diary_date_infer.py`、新規)

`agent/memory_extract.py`の構造化抽出パターン(reasoning無効化)と同型。呼び出し元は`services/diary.py`
ではなく`api/app.py::_record_diary_task`(`record_diary_turn`を呼ぶ前段、`research.md` Decision 7)。

```python
class DateInferenceResult(BaseModel):
    target_date: date | None  # 推定できなければNone(当日のエントリを対象にする)

class DiaryDateInferrer(Protocol):
    async def infer(self, *, user_text: str, assistant_text: str, today: date) -> DateInferenceResult: ...

def build_diary_date_infer_agent(settings: Settings) -> Agent[None, DateInferenceResult]: ...

class AgentDiaryDateInferrer:
    async def infer(self, *, user_text: str, assistant_text: str, today: date) -> DateInferenceResult: ...
```

### 読み取りtool `get_diary_range`(User Story 5、`chat_agent.py`)

```python
class DiaryDayResult(BaseModel):
    entry_date: date
    content: str

class DiaryRangeResult(BaseModel):
    entries: list[DiaryDayResult]  # 実在する日だけ、無い日は含めない

@agent.tool_plain
def get_diary_range(start_date: date, end_date: date) -> DiaryRangeResult | str:
    """指定期間の日記エントリを返す(単日はstart_date == end_date)。
    (end_date - start_date).days > 62 の場合は期間を絞るよう促す文字列を返す(research.md Decision 8)。
    """
```

`get_paper_full_text`と同じ「全文をコンテキストに渡す」toolのため、`src/polaris/services/history_trim.py`の
`FULL_TEXT_TOOL_NAMES`に`"get_diary_range"`を追加する(ADR-0012対応)。

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
