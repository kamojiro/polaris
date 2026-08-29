# 023. 日次サマリー通知(アイドル時バッチ生成)

## ステータス

✔️ 完了(v1、2026-08-30)。013/019が実装されたら集計対象に追加可能な構造にしてある

## 概要

1日の終わり(またはアイドル時間帯)に、Polaris全体の活動を横断的に要約し、フロントエンドに通知的に表示する。チャットのターンに紐づかない、初めてのスケジュール/アイドル駆動の処理(2026-08-26、雑談から着想)。

## 背景・判断

- `wishlist-design.md` Layer3で「バッチ処理(日次まとめ生成、Interest更新など)は個人用途なら`Celery`等を持ち込まず`cron`+スクリプトで十分」と既に方針が決まっていた。本specはその具体化
- 「LLMが使われていない間に実行してほしい」という要望は、単一GPU・単一マシン運用(既知のCUDA OOM対応の実績あり)という制約と噛み合う実務的な理由と理解する。チャット中に重い生成処理が割り込んでGPU/モデルリソースを競合させたくない、という動機
- `docs/adr/0003-chat-turn-pipeline.md`で定義した前処理/メイン/後処理は、いずれも「チャットターンに紐づく」処理だった。本specは初めてターンに紐づかないスケジュール実行になるため、ADR-0003のパイプラインには含めず、別立てのcronジョブとして実装する

## トリガー方式(v1)

- 「本当のアイドル検知」(直近のチャットアクティビティを監視して空いてる時間を探す)は複雑さの割にメリットが薄いため見送る(`017-chat-memory`がセッション終端検知を見送ったのと同じ判断)
- v1は固定時刻の`cron`(例: 深夜〜早朝、実際にチャットを使っていなさそうな時間帯)で十分とする。本当に稼働中と衝突するようなら、その時点でチャットの最終アクティビティ時刻を見るガード程度を足せばよい

## 集計内容

以下をドメインごとのrepositoryから直接読み出し、LLM1回で要約する。専用のエージェント/レジストリは作らず、`services/daily_summary.py`のような純粋関数+軽量LLM呼び出しに留める(`011-agent-registry`のYAGNI判断と同じ考え方)。

- `002`/`014`(論文Ingest): 当日保存分
- `007`(TODO): 当日追加・完了分
- `013`(IR): 当日保存分
- `017`(記憶): 当日更新されたテーマ
- `008`(ニュースダイジェスト、実装されていれば): 当日分のハイライト
- `019`(日記、実装されていれば): 当日エントリ

008/019がまだ存在しなくても、既存ドメイン(002/007/013/017)だけで動く設計にする。各ドメインの「当日分」取得は、既存のリポジトリに`created_at`/`updated_at`でのフィルタを足す程度で済むはず。

## データモデル(v1実装、2026-08-30)

```python
class DailySummaryRecord(SQLModel, table=True):
    __tablename__ = "daily_summary_records"

    id: str = Field(primary_key=True)
    summary_date: date = Field(index=True, unique=True)  # 1日1件、JST基準
    content: str           # LLMが生成した要約本文(単一の自然文、markdown想定はしていない)
    generated_at: datetime
```

`019-diary-domain`の`DiaryRecord`と形は似ている(日付キー、1日1件、テキスト本文)が、別テーブルとして分ける。著者が違う(diaryはユーザー自身がチャットで書く、こちらはシステムが自動生成する)ため、意味的に混ぜない。

`sections: list[SummarySection]`(ドメインごとに構造化して見出し・展開表示する案)も並行して検討されたが、v1では採用しなかった。理由は下記「将来検討」参照。

## フロントエンド: 通知UI(v1実装)

- ページロード時に最新のサマリーを取得するAPI(`GET /api/daily-summary/latest`)を叩き、未読なら`App.tsx`にバナー(`DailySummaryBanner.tsx`)として表示する。既存の`error`/`paper-mode-badge`と同じ軽量パターン(hooks 1つ + 条件描画)を踏襲する
- `content`(単一文字列)をそのまま全文表示する。見出しのみ+クリックで展開、という段階表示は行わない
- プッシュ通知(Service Worker等)は`010-mobile-pwa`化した後の話。v1はページを開いたときに気づける程度で十分

## 未決定事項(2026-08-30確定、v1実装時点)

- **「1日」の区切り方**: JST(`Asia/Tokyo`、`settings.daily_summary.timezone`)。DB保存はすべてUTCだが、
  集計時に`services/daily_summary.py`の`local_day_bounds_utc()`でJSTの日付境界をUTC範囲に変換する
- **生成に使うLLM**: メインのチャットモデル(`settings.llm.model_id`)。複数ドメインを横断して自然な
  文章にまとめる必要があり、017の想起用軽量モデル(qwen3-8b)より能力が要ると判断した
- **通知の既読管理**: サーバー側にread状態を持たず、フロントのlocalStorageに最終既読日付
  (`polaris.dailySummary.lastSeenDate`)を持つだけにする(`DailySummaryBanner.tsx`)。個人用の
  単一ユーザーツールでは実害が薄く、DBスキーマ・APIを増やさずに済む
- **集計対象がすべて空の日**: サマリー自体を生成しない(`DailySummaryRecord`を作らない)。
  「特に活動はありませんでした」を毎朝出すのは通知として無価値と判断した

## 実装状況(2026-08-30)

✔️完了(v1)。`013-ir-analysis-domain`は未実装のため集計対象から除外した(コードが1つも
存在しないため)。実装され次第、`collect_activity`にブロックを1つ足すだけで済む構造にしてある。

- 008(ニュース)は`skip_summary=False`のフィード由来(要約付き記事)のみ集計する。arXiv系の
  カタログフィード(1日数百件流れる)はそのまま渡すとプロンプトが肥大化するため、件数のみを
  `catalog_news_counts`として渡す
- 論文は`Item.title` + 既に生成済みの`Item.summary`のみを渡し、本文全文は渡さない
  (`specs/IDEAS.md`に記録したチャット履歴のコンテキスト肥大の問題と同じ轍を踏まないため)
- `cli/generate_daily_summary.py`をOS cronから1日1回叩く方式(`cli/ingest_news.py`と同型)。
  既定は設定タイムゾーンでの「昨日」を対象にする(深夜〜早朝cron前提)
- `GET /api/daily-summary/latest`で最新1件を返す(生成はCLI専用、APIは読み取り専用)

## 将来検討: リッチな表示への拡張(2026-08-29、並行セッションでの検討・未実装)

v1実装(このファイルの他セクション、2026-08-30)と並行して、別セッションが「複数ドメイン横断の
要約は長文になりうる」という前提で表示方式を詳細化していた。まだコード化されていないため、v1では
`content: str`の単一文字列+全文バナー表示を採用したが、設計の記録として残す。

- LLMに直接HTMLを生成させ、チャット本体と同じDOM(親ページと同一オリジン)に`dangerouslySetInnerHTML`で描画する方式は採らない。プロンプトインジェクション経由のXSS類似リスクがあるのと、生成のたびに見た目がブレる(レイアウトをLLMの気分に委ねることになる)ため
- 代わりに、LLMには`SummarySection`(`domain`/`title`/`body`)の構造化データだけを生成させ、実際の見た目(HTML/CSS)は`003-chat-ui-polish`のgenerative UIパターン(`list_papers`/`list_todos`と同じ、専用Reactコンポーネントで描画)を踏襲する。本文(`body`)はセクションごとに既存の`react-markdown`でレンダリングする
- バナーは見出し(+先頭セクションの要約1行程度)のみ表示し、クリックで展開する。展開先はモーダルまたは専用ページ(`/daily-summary`)を想定。詳細なUIモックアップは未着手
- このコンポーネントは`008-daily-digest-domain`のPhase B(まとめて見せる要求)でも再利用できる見込み
- 「本文がmarkdownでは表現しきれない自由なレイアウト・図が必要」なケースが将来出てきた場合、上記の展開ビュー(モーダル/専用ページ)側に限り、Claude ArtifactsやChatGPT Canvas等のAIチャット製品が実際に採る方式(`<iframe sandbox="allow-scripts" srcdoc="...">`、`allow-same-origin`は付与しない)でHTMLを描画する選択肢を残す。iframeは親ページと別オリジン扱いになるため、中のscriptが親ページのcookie/localStorage/認証済みAPI呼び出しに触れられず、`dangerouslySetInnerHTML`直挿しより安全にLLM生成HTMLを許容できる。チャットバブルへのインライン表示(react-markdown + Mermaid)には適用しない、隔離コストに見合わないため。実際に必要になってから着手する。iframeのsandbox属性に加えて、Content Security Policy(CSP)でも通信先を絞る(Claude Artifacts/ChatGPT Canvasの実装もsandbox属性単体ではなくCSP併用)

着手するかどうかは、v1(全文バナー表示)を実際に使ってみて「長すぎて読みにくい」という実利上の課題が出てから判断する(YAGNI、他specでも一貫している方針)。着手する場合の未決定事項:

- `content: str`から`sections: list[SummarySection]`へのデータモデル移行方法(`SummarySectionRecord`として正規化するかJSON列にするか)
- 展開表示をモーダルにするか専用ページ(`/daily-summary`)にするか

## 依存

- `002`/`007`/`017`(既存、集計対象)
- `008`(実装済み、要約付きフィードのみ集計対象)
- `013`/`019`(実装されたら集計対象に追加、無くても動く)
- `wishlist-design.md` Layer3のバッチ処理方針(`cron`+スクリプト)
