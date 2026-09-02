# Contract: `GET /api/memory-housekeeping/latest`

このプロジェクトは外部公開APIを持たない個人用ツールのため、`/contracts/`で扱う「契約」は
フロントエンド⇄バックエンド間のREST APIのみ(本specにAG-UI state・toolの変更は無い、
`data-model.md`参照)。`GET /api/daily-summary/latest`(023)と同じ形の読み取り専用エンドポイント。

## リクエスト

`GET /api/memory-housekeeping/latest`(パラメータ無し)

## レスポンス

```python
class HousekeepingSuggestionResponse(BaseModel):
    suggestion_type: str        # "merge" | "split" | "stale"
    target_themes: list[str]    # 対象テーマのslug
    detail: str

class MemoryHousekeepingResponse(BaseModel):
    generated_at: datetime
    suggestions: list[HousekeepingSuggestionResponse]
```

```typescript
// frontend: frontend/src/MemoryHousekeepingBanner.tsx
interface HousekeepingSuggestionResponse {
  suggestion_type: string;
  target_themes: string[];
  detail: string;
}

interface MemoryHousekeepingResponse {
  generated_at: string;   // ISO 8601
  suggestions: HousekeepingSuggestionResponse[];
}
```

- **候補が0件、またはバッチ未実行の場合**: `null`を返す(`suggestions`が空配列の`200`ではなく、
  レスポンス自体が`null`。フロントは`summary === null`と同じ扱いでバナーを表示しない、FR-008)
- **副作用**: 無し(読み取り専用。生成は`cli/run_memory_housekeeping.py`がcronから叩く、
  このエンドポイントは一切書き込みを行わない)
- **既読管理**: サーバー側に持たない。フロントが`generated_at`をlocalStorageの
  `polaris.memoryHousekeeping.lastSeenGeneratedAt`と比較する(023の`summary_date`比較と同型、FR-009/FR-010)
- **呼び出しタイミング**: フロントはページロード時(`MemoryHousekeepingBanner`のマウント時)に
  1回フェッチする。チャットのAG-UIストリームとは独立(023と同じ)
- **エラー時**: フェッチ失敗時はバナーを表示しないまま静かに諦める(通知的な機能のため、
  チャット本体の利用に影響させない。`DailySummaryBanner.tsx`と同じ方針)
