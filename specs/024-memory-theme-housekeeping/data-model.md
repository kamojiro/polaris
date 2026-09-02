# Phase 1 Data Model: 記憶テーマの定期棚卸し(memory-theme-housekeeping)

`research.md`の決定を踏まえた確定版。`spec.draft.md`のたたき台をベースに、`dismissed`カラムを
削除(既読管理はlocalStorage、Decision 5)、`generated_at`をバッチ全体で共有する形に変更した。

## エンティティ

### MemoryHousekeepingSuggestion(satellite相当、`Item`ハブは経由しない)

```python
class MemoryHousekeepingSuggestion(SQLModel, table=True):
    __tablename__ = "memory_housekeeping_suggestions"

    id: str = Field(primary_key=True)
    suggestion_type: str    # "merge" | "split" | "stale"(spec Key Entities/Assumptions: 3種で固定)
    target_themes: str      # 対象テーマのslugをカンマ区切りで保持(シンプルな実装優先、たたき台どおり)
    detail: str              # 提案の具体的な理由の説明(LLMが生成、FR-003)
    generated_at: datetime = Field(index=True)  # このバッチ全体の実行時刻。全行で共通の値を持つ
```

`MemoryTheme`/`DailySummaryRecord`と同じく`Item`ハブを経由しない(特定の知識アイテム1件に
紐づくものではなく、複数テーマを横断した提案のため、`db/memory_repository.py`のdocstringと同じ考え方)。

`suggestion_type`は自由文字列だが、API/フロント側では`Literal["merge", "split", "stale"]`相当として
扱う(FR-002/spec Assumptions)。DB制約(CHECK制約等)は憲章 原則II(YAGNI)により設けない
(単一ユーザー・LLM生成値のみが書き込まれるため実害が薄い)。

## Repository: `MemoryHousekeepingRepository`(`db/memory_housekeeping_repository.py`、新規)

`MemoryRepository`/`DailySummaryRepository`と同じ「メソッドごとにSessionを開く」パターン。

```python
class MemoryHousekeepingRepository:
    def __init__(self, engine: Engine) -> None: ...

    def replace_all(self, suggestions: Sequence[MemoryHousekeepingSuggestion]) -> None:
        """既存の全行を削除してから新しい行を挿入する(FR-005: 毎回完全に置き換え)。
        suggestionsが空でも削除は必ず行う(FR-006: 0件なら既存候補を消去)。"""

    def list_latest(self) -> list[MemoryHousekeepingSuggestion]:
        """テーブルは常に最新バッチの行のみを持つため、単純に全件返す(generated_at降順)。
        空リストなら「直近のバッチで候補0件」または「バッチ未実行」のいずれか
        (API層はどちらも同じ「候補なし」として扱う、FR-008)。"""
```

`replace_all`は「削除→挿入」を1つの`Session`/トランザクション内で行う(冪等性、`upsert_theme`と
同じくSession境界を1メソッドに閉じる方針)。

## 検出エージェント `MemoryHousekeepingDetector`(`agent/memory_housekeeping.py`、新規)

`agent/memory_extract.py`と同じ「Protocol + Agentラッパー」の形(research.md Decision 3)。

```python
class HousekeepingSuggestionItem(BaseModel):
    suggestion_type: Literal["merge", "split", "stale"]
    target_theme_slugs: list[str]   # merge/splitは複数件、staleは通常1件
    detail: str                      # 具体的な理由(日本語)

class HousekeepingDetectionResult(BaseModel):
    suggestions: list[HousekeepingSuggestionItem]  # 0件もありうる(FR-006)

class MemoryHousekeepingDetector(Protocol):
    async def detect(self, *, themes: Sequence[tuple[str, str]]) -> HousekeepingDetectionResult:
        """themesは (slug, 現在状態ファイル全文) のペア一覧。全テーマを1回のLLM呼び出しで評価する
        (research.md Decision 3)。"""
        ...

def build_memory_housekeeping_agent(settings: Settings) -> Agent[None, HousekeepingDetectionResult]:
    """settings.llm.model_id(メインモデル)を使う(research.md Decision 4)。reasoningは無効化しない
    (023の日次サマリーエージェントと同じ判断)。"""

class AgentMemoryHousekeepingDetector:
    async def detect(self, *, themes: Sequence[tuple[str, str]]) -> HousekeepingDetectionResult: ...
```

stale判定に必要な`updated_at`(FR-002の「長期間更新されていない」判定)はプロンプト側で
`(slug, 現在状態ファイル全文, updated_at)`として渡す(`themes`のタプルに`updated_at`を含める)。

## オーケストレーション `run_memory_housekeeping`(`services/memory_housekeeping.py`、新規)

```python
async def run_memory_housekeeping(
    *,
    detector: MemoryHousekeepingDetector,
    memory_repo: MemoryRepository,
    housekeeping_repo: MemoryHousekeepingRepository,
    settings: Settings,
) -> list[MemoryHousekeepingSuggestion]:
    """全テーマのslug・updated_at・現在状態ファイル全文を集め、detectorに渡し、
    結果をMemoryHousekeepingSuggestion行に変換してreplace_allで保存する。
    テーマが0〜1件でもエラーにしない(Edge Case、FR-006はそのまま「0件」として保存)。"""
```

`services/daily_summary.generate_daily_summary`と違い、「活動が空なら何もしない」という早期リターンは
無い(空でも`replace_all([])`は必ず呼び、既存候補があれば消去するのがFR-006の要求)。

## CLI(`cli/run_memory_housekeeping.py`、新規)

`cli/generate_daily_summary.py`と同型だが対象期間引数は持たない(research.md Decision 6)。
`api/app.py`とは別にEngine・Repository・Agentを自前で組み立てる(サーバー未起動でも動く)。

```text
uv run python -m polaris.cli.run_memory_housekeeping
```

## API(`api/app.py`、拡張)

```python
class HousekeepingSuggestionResponse(BaseModel):
    suggestion_type: str
    target_themes: list[str]
    detail: str

class MemoryHousekeepingResponse(BaseModel):
    generated_at: datetime
    suggestions: list[HousekeepingSuggestionResponse]

@app.get("/api/memory-housekeeping/latest")
def memory_housekeeping_latest() -> MemoryHousekeepingResponse | None:
    """list_latest()が空リストならNoneを返す(候補なし/未実行のどちらもバナー非表示、FR-008)。"""
```

生成はCLI側でしか行わない(023の`/api/daily-summary/latest`と同じく読み取り専用エンドポイント)。

## フロントエンド

`frontend/src/MemoryHousekeepingBanner.tsx`(新規)。`DailySummaryBanner.tsx`と同じ構造。

```tsx
const LAST_SEEN_KEY = "polaris.memoryHousekeeping.lastSeenGeneratedAt";
// マウント時に GET /api/memory-housekeeping/latest
// suggestions.length > 0 && generated_at !== localStorage.getItem(LAST_SEEN_KEY) なら表示
// ✕ で localStorage.setItem(LAST_SEEN_KEY, generated_at) して閉じる(FR-009/FR-010)
```

`App.tsx`では`DailySummaryBanner`と並べて置く(`<main>`の直後、composerの手前)。

## バリデーションルール

- `MemoryHousekeepingSuggestion.suggestion_type`はAPI/フロント層で`"merge" | "split" | "stale"`の
  3値に限定する(FR-002、spec Assumptions)
- `replace_all`は必ず「削除→挿入」を1トランザクションで行う(FR-005: 過去分を蓄積しない)
- `target_themes`はカンマ区切り文字列で保持し、API応答時に`list[str]`へ変換する(たたき台の
  シンプルな実装を踏襲、正規化されたリレーションテーブルは設けない)
