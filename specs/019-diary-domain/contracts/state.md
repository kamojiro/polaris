# Contract: AG-UI State (`ChatUIState`)

このプロジェクトは外部公開APIを持たない個人用ツールのため、`/contracts/`で扱う「契約」は
フロントエンド⇄バックエンド間でAG-UIのstate機構を通じて往復するデータ形のみ。

## 形

```python
# backend: src/polaris/agent/chat_agent.py
class ChatUIState(BaseModel):
    active_paper: ActivePaper | None = None
    diary_mode: bool = False
```

```typescript
// frontend: frontend/src/useChatAgent.ts
export interface ChatUIState {
  active_paper: ActivePaper | null;
  diary_mode: boolean;
}
```

バックエンドとフロントエンドでフィールド名を一致させる既存の規約(`useChatAgent.ts`の
`PaperModeState`コメント参照)を踏襲する。

## 往復のルール

1. **クライアント→サーバー**: `POST /api/chat`の`RunAgentInput.state`として毎ターン送信される
   (AG-UIプロトコルの標準機構、`HttpAgent`が自動的に行う)
2. **サーバー内**: `pydantic_ai.Agent[ChatDeps, str]`の`ChatDeps.state: ChatUIState`として
   `RunContext`経由で読み書きできる
3. **サーバー→クライアント**: ターン完了時、`on_complete`が`StateSnapshotEvent(snapshot=deps.state.model_dump(mode="json"))`
   をyieldし、クライアントの`agent.state`が丸ごと置き換わる
4. **クライアント単独での即時更新**: `diary_mode`のON/OFFトグルは`agent.setState(...)`で
   LLMのターンを待たずに即座に反映できる(次回送信時に自動的にサーバーへ伝わる)

## 後方互換性

`active_paper`は既存の`PaperModeState`から名前・型とも変更しない。クラス名の
`PaperModeState → ChatUIState`改名のみが変更点(`research.md` Decision 4)。既存の論文モードの
挙動(015)には機能的な変更を加えない。
