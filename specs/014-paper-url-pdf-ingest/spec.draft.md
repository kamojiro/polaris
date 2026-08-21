# 014. 論文Ingestのurl/local_pdf対応

## ステータス

✔️ 完了

## 概要

`002-papers-ingest-full` はarXiv入力のみを実装して完了とした。当初スコープにあった「URL(PDF直リンク等)」「ローカルPDFファイル」からのIngestを、このspecで追加する。

**訂正(014着手時の調査で判明)**: 002 spec は「`InputKind`の判定ロジック自体は002の時点で将来拡張できる形にしてある」としていたが、実際にはコード上に `InputKind` は存在せず、`extract_arxiv_id() -> str | None` による二値判定(arXivか否か)しか無かった。014では `services/paper_source.py` として入力種別の判定を新設した(タグ付きdataclassの union: `ArxivSource` / `UrlSource` / `UploadSource`)。

## URL入力(PDF直リンク)

素直にダウンロードすればよい。`httpx`でPDFを取得し、以降は002の本文抽出〜永続化フローにそのまま合流する。新規の論点はない。

## local_pdf入力(方針)

第一候補: チャットUIにファイル添付機能を作る。AG-UIプロトコル自体は `InputContent[]`(text + `BinaryInputContent`、mimeType + base64)によるバイナリ添付をサポートしており、agentが `capabilities` でファイルアップロード対応を宣言する仕組みもある。

ただし実装レベルでは既知の不安定さがある。`@ag-ui/client` や各種AG-UIブリッジ実装で、添付のバイナリ部分がテキスト抽出時に捨てられ、テキストだけがエージェントに渡ってしまう不具合が複数報告されている。pydantic-aiの`AGUIAdapter`がバイナリ添付をエンドツーエンドで正しく扱えるかは着手時に実機検証が必要(未検証)。

フォールバック: チャット添付が動かない、または実装コストが見合わない場合は、チャットとは別に単純なアップロード用エンドポイント(例: `POST /papers/upload`)を作り、フロント側に最小限のアップロードUI(ファイル選択+送信ボタン)を用意する。アップロード後は既存のIngestパイプライン(arXiv/URL経路と同じStructure以降のフロー)に合流させる。

## 受け入れ条件

- PDF直リンクURLを貼ると論文が保存される(既存のarXiv経路と同じ完了の定義に準拠)
- ローカルPDFファイルを何らかの手段(チャット添付 or 専用アップロードUI)でサーバーに渡すと論文が保存される
- どちらの手段で取り込んだ場合も、保存後の一覧表示・検索は既存の論文(arXiv経由)と区別なく扱われる

## 未決定事項(結論)

- AG-UIのバイナリ添付がpydantic-aiの`AGUIAdapter`経由で実際に動くか →
  **動く**ことを実装(`pydantic_ai/ui/ag_ui/_adapter.py`)を読んで確認したが、
  **採用しなかった**。その経路はPDFをLLMのuser promptに載せる設計であり、
  Polarisの本文抽出(pypdfによるサーバー側処理)・チャットモデル(text-only Qwen3系)
  とは用途が噛み合わないため。専用アップロードエンドポイント方式(フォールバックと
  していた方)を本命として採用した。判断の詳細は `docs/adr/0002-local-pdf-upload-endpoint.md` 参照。

## 実装状況(2026-08-20)

✔️完了。

- URL直リンク: `adapters/pdf/downloader.py`(新規)でダウンロードし、既存の
  本文抽出〜永続化フローに合流する。arXiv以外は `PaperStructurer` の代わりに
  `agent/extract_metadata.py`(新規)で本文冒頭からtitle/authors/year/abstract/doi/venue
  とsummaryをLLM1回で抽出する(title/abstractの供給元がarXiv APIのように別途無いため)。
- local_pdf: `POST /api/papers/upload` でアップロードのみ行い、返る `upload_id` を
  `upload://<id>` としてチャットメッセージに埋め込み、既存の `save_paper` ツール
  経由で取り込む(ADR-0002)。
- 重複判定は非arXiv(`arxiv_id=None`)には `source_url` を流用(`find_by_source_url`
  を追加)。ローカルPDFは内容のsha256ハッシュを `source_url` に入れる。
  DBスキーマにカラムは追加していない(既存 `data/polaris.db` のマイグレーション不要)。
- `extract_arxiv_id` を厳格化し、arxiv.org以外のホストのURLに数字列が含まれていても
  誤ってarXiv扱いしないようにした(過剰マッチの回帰防止)。
- 実PDF・実LLM・実GPU embedderでarXiv/URL直リンク/アップロードの3経路すべてを
  手動E2E確認済み。

## 依存

- `002-papers-ingest-full`(完了済み)
