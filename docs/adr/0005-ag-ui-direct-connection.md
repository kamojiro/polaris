# 0005. AG-UIプロトコル + @ag-ui/client直接接続を採用する

## ステータス

採択

## コンテキスト

チャットUI(フロントエンド)とpydantic-aiエージェント(バックエンド)をつなぐ必要があった。AG-UIプロトコルのリファレンス実装元でもあるCopilotKit(Next.js向けの高機能チャットUIフレームワーク)を使う選択肢と、AG-UIプロトコルを`pydantic_ai.ag_ui.AGUIAdapter`(バックエンド)+`@ag-ui/client`の`HttpAgent`(フロントエンド)で直接話す選択肢があった。

## 決定

CopilotKit/Next.jsは使わない。FastAPIのエンドポイントに`pydantic_ai.ag_ui.AGUIAdapter`を繋ぎ、フロントエンドは素のVite+Reactから`@ag-ui/client`の`HttpAgent`で直接接続する。

## 検討した代替案

- CopilotKitを採用する: Next.jsへの依存が付いてくる(個人開発で管理したいスタックが増える)。UIコンポーネントが用意される代わりに、細かいカスタマイズ(003のgenerative UI各種、008のニュースサイドバー等、本プロジェクト固有のUI要件)への対応がフレームワークの流儀に縛られる懸念があった。プロトコル自体(AG-UI)を直接話せば、React側は自由に組める。

## 結果(Consequences)

良い面: フロントの技術選択が自由(Vite+React、Next.js特有の制約なし)。実際にPaperList/TodoList/NewsList/NewsSidebar等、要件に応じた専用generative UIコンポーネントを都度自由に組めている。AG-UIの`CustomEvent`/`StateSnapshotEvent`のような低レベルの機能(015の使用量表示・論文モード、本セッションのtool実行時間表示)も直接扱えている。

悪い面: CopilotKitが提供するはずの既製UI・機能(ストリーミング表示の細部、承認フロー等)を自前で実装する必要がある。実際にmessage-actions(コピーボタン)、usage表示、tool実行中のstatus表示は全て自前実装になっている。

## 関連

- `docs/constitution.draft.md`
- `001-walking-skeleton`
