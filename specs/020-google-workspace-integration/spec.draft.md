# 020. Google Calendar/Drive連携

## ステータス

💤 スケルトンのみ

## 概要

Google CalendarとGoogle Driveとの連携。用途の具体化はこれから(2026-08-23、雑談から着想)。想定される方向性:

- Calendar: `007-todo-domain`が将来spec扱いにしたリマインド機能との連携(締切のあるTODOをカレンダーに反映する、または既存の予定を読んでTODOの参考にする)
- Drive: 論文/IR文書の取り込み元としてDrive上のファイルを参照する、またはPolarisのデータのバックアップ先として使う、といった用途が考えられるが未確定

## 背景・判断

- `specs/IDEAS.md`の調査(2026-08-23)で、Googleが公式のリモートMCPサーバー(`calendarmcp.googleapis.com`/`gmailmcp.googleapis.com`)を提供していることを確認済み。自分のGoogle Cloudプロジェクトで有効化してOAuth接続する方式で、サードパーティのリレーを経由しない
- Driveについては同系統の公式軽量MCPが確認できていない。コミュニティ実装(`taylorwilsdon/google_workspace_mcp`、Gmail/Calendar/Docs/Sheets/Slides/Drive等12サービス対応、MIT、OAuth 2.1、自前ホスト)が候補になる。CalendarとDriveでMCPサーバーの出どころが異なる可能性がある点に注意
- `018-web-search-tool`と同じく、自前でGoogle APIクライアントを書かず既存のMCPサーバーをpydantic-aiのMCP toolsetとして接続する方針を踏襲する

## 未決定事項

- 具体的な用途の絞り込み(Calendar/Driveそれぞれ、読み取りだけで十分か、書き込み(予定作成・ファイル作成等)まで要るか)
- Calendarは公式MCP、Driveはコミュニティ実装、のようにサービスごとに接続先が変わってよいか(全部`taylorwilsdon/google_workspace_mcp`に寄せて一本化する選択肢もある)
- 書き込み系の操作(カレンダーへの予定作成、Driveへのファイル作成・共有等)を許可制にするか。`022-misskey-integration`の投稿許可制と同様の考え方(elicitation等)が要るかもしれない
- Google Cloudプロジェクトの用意・OAuth同意画面の設定など、着手時にユーザー自身が行う作業の切り分け

## 依存

- `018-web-search-tool`のMCP toolset接続パターンを踏襲
- `007-todo-domain`のリマインド機能(将来spec)と関連しうる
