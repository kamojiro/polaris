# 0002. ローカルPDFの取り込みは専用アップロードエンドポイントで行う

## ステータス

採択

## コンテキスト

`014-paper-url-pdf-ingest` でローカルPDFファイルからの論文取り込みに対応する必要があった。spec の下書き段階では第一候補として「チャットUIへのファイル添付」を挙げていた。AG-UIプロトコルには `BinaryInputContent`/`ImageInputContent`/`DocumentInputContent` 等による `InputContent[]` 添付の仕組みがあり、着手時に実装(pydantic-ai 2.31.0 の `AGUIAdapter`、`@ag-ui/client` 0.0.57)を直接読んで検証した。

検証の結果、`pydantic_ai/ui/ag_ui/_adapter.py` の `load_messages` は `BinaryInputContent`/`DocumentInputContent` を `BinaryContent`/`DocumentUrl` に変換し、`UserPromptPart` の一部として **チャットモデルへのプロンプトに載せる**実装になっていることを確認した(懸念していた「バイナリ部分がテキスト抽出時に捨てられる」不具合は今回のバージョンでは見当たらなかった)。つまり技術的には動く。

しかし、この経路が想定している用途は「LLMに画像やドキュメントを読ませる」ことであり、Polarisの用途とは噛み合わない:

- Polarisの本文抽出は `pypdf`(`adapters/pdf/extractor.py`)によるサーバー側処理が前提で、PDFをLLMに読ませて理解させる設計にはなっていない。
- チャットエージェントのモデルはOpenRouter経由のテキスト専用Qwen3系(`agent/model.py`)で、PDF等のマルチモーダル入力を想定した構成ではない。
- 添付を使うには `/api/chat` で `AGUIAdapter.dispatch_request` に渡す前にリクエストボディを手動でパースしてバイナリ部分を抜き出す実装が必要になり、既存の薄いエンドポイント(`api/app.py`)に対して不釣り合いに複雑になる(constitution の YAGNI原則に反する)。

## 決定

ローカルPDFの取り込みは、チャット添付ではなく専用の `POST /api/papers/upload` エンドポイント(`multipart/form-data`)で受け取る。アップロードはファイルの一時保存のみを行い、実際の取り込み(本文抽出・メタデータ抽出・チャンク分割・Embedding生成)は行わない。フロントエンドはアップロード成功後に返る `upload_id` を `upload://<id>` という擬似スキームとして通常のチャットメッセージに埋め込み、既存の `save_paper` ツール経由で取り込みを実行させる。

## 検討した代替案

- AG-UI添付をそのまま使う: 技術的には動作を確認できたが、上記の理由(用途の不一致、実装の複雑化)により見送った。
- アップロード後にingestまで即時実行する専用エンドポイントにする: 進捗表示(SSE)・チャット履歴・エラーメッセージ等、`save_paper` ツール経由で既に得られている導線を全て別途アップロードエンドポイント側にも実装する必要があり、ingestの入口が2箇所に分散する。`save_paper` 1本に絞る方が単純。

## 結果(Consequences)

良い面: ingestの入口が `save_paper` ツール1本のまま保たれ、進捗SSE・チャット履歴・一覧更新の既存の導線がそのまま使える。アップロードエンドポイント自体は薄いI/Oのみなのでテストも容易(`api/app.py` はモジュールレベルでGPUモデルをロードするためAPI層の自動テストは書いていない)。

悪い面: ユーザー操作が「ファイル選択→(内部的に)アップロード→チャットメッセージ送信」の2段階になる(ただしフロント側で自動連結しているため、体感は1操作に近い)。アップロードされたファイルは一時領域(`settings.ingest.upload_dir`)に残るため、取り込み完了後に削除する後始末をIngestパイプライン側で行う必要がある(実装済み)。

## 関連

- 関連spec: `specs/014-paper-url-pdf-ingest`
- 関連ADR: なし
