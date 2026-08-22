# 013. IR分析ツール(有価証券報告書チャット)

## ステータス

✅ 実装開始可能

## 概要

EDINET(金融庁の開示書類システム)から有価証券報告書等のPDFを取り込み、論文ドメイン(002/015)と同じ「全文をそのままコンテキストに渡すチャット」方式で質問に答えられるようにする。v1は取込・要約・QAのみに絞り、企業名検索・ニュースとの関連付け・XBRL構造化解析は範囲外とする。

## 背景・判断(2026-08-22、EDINET API v2仕様を調査した上で決定)

- EDINET API v2の書類取得エンドポイント(`GET /api/v2/documents/{docID}?type=2`)は**PDFをそのまま返す**。XBRLをパースしなくても、015で作った「PDF → pypdfで本文抽出 → 全文をコンテキストに渡すチャット」のパイプラインがほぼそのまま流用できる
- 書類一覧API(`GET /api/v2/documents.json`)は`date`(提出日)でしか絞り込めず、企業名・EDINETコードでの直接検索はAPI側に無い(レスポンスの`filerName`をクライアント側で見るしかない)。日次スキャン+ローカルインデックスを作る手も検討したが、個人用ツールの規模には過剰と判断し、v1では**ユーザーがEDINET公式サイトの検索UIで見つけたdocIDをそのままチャットに貼る**運用にする(002当初のarXiv ID直接入力と同じ考え方)
- 書類取得・書類一覧のいずれのAPIも`Subscription-Key`(無料登録で発行されるAPIキー)が必須。`settings.ir.edinet_api_key`として`LLMSettings.api_key`と同じ形で持つ
- SEC EDGAR(米国企業)はv1のスコープ外。EDINET(日本企業)のみ対応する
- 「ニュースとの関連付け」はv1のスコープ外。ニュース取得・検索という新たな外部依存が必要でスコープが大きくなるため、まずはIR資料単体の取込・要約・QAだけで完結させる。将来必要になったら別specとして切り出す
- 投資助言そのものにならないよう、要約・QAは「書かれている事実の整理」に留める。「買うべきか」等の判断を求められても回答しない、という運用上の注意を`_INSTRUCTIONS`に明記する

## データモデル

Hub/Satelliteパターンを踏襲し、論文ドメインの`PaperRecord`と対になる`IrRecord`を追加する。

```python
class ItemType(StrEnum):
    paper = "paper"
    todo = "todo"
    ir_document = "ir_document"


class IrRecord(SQLModel, table=True):
    __tablename__ = "ir_records"

    id: str = Field(primary_key=True)
    item_id: str = Field(foreign_key="items.id", index=True)
    doc_id: str = Field(index=True, unique=True)  # EDINETのdocID(書類管理番号)。重複防止キー
    filer_name: str                                # 提出者名(企業名)
    edinet_code: str | None = None
    doc_type_code: str | None = None               # 有価証券報告書/四半期報告書等の種別コード
    period_start: date | None = None
    period_end: date | None = None
    submit_datetime: datetime
    pdf_path: str | None = None
    ingested_at: datetime
```

`Item.title`は`f"{filer_name} {docDescription}"`程度、`Item.summary`はLLM要約(既存のStructureパターンを流用)で埋める。`arxiv_id`に相当する自然キーは`doc_id`(EDINETの書類管理番号、`S100XXXX`のような形式)。

## 処理フロー

1. ユーザーが「`S100XXXX`を取り込んで」のようにdocIDをチャットに貼る
2. `save_ir_document(doc_id)`ツールが`IrRecord.doc_id`で重複チェック(既存なら再取得しない、002/015と同じ冪等性の考え方)
3. `GET /api/v2/documents/{doc_id}?type=2&Subscription-Key=...`でPDFバイト列を取得(新規`adapters/edinet/client.py`、`adapters/arxiv/client.py`の構造を踏襲)
4. `adapters/pdf/extractor.py::extract_pdf_text`で本文抽出(既存を再利用、変更不要)
5. 本文冒頭から`agent/extract_metadata.py`相当のLLM抽出で企業名・書類種別・期間・要約を補完(014の非arXiv経路と同じ「本文からメタデータを拾う」パターン)
6. Item + IrRecordを保存

Chunk/Embeddingは**v1では作らない**。IR文書は「その1件を読んで質問する」用途が主で、論文のようなライブラリ横断検索の需要が今のところ無いため、015と同じ「都度pypdf再抽出して全文をコンテキストに渡す」方式(`get_ir_full_text`)だけで賄う。ライブラリ横断検索が必要になったら、その時点でChunk/Embedding化を検討する。

## ツール(chat_agent.pyに追加)

| ツール | 内容 |
|---|---|
| `save_ir_document(doc_id)` | EDINETからPDF取得・保存(処理フロー参照) |
| `get_ir_full_text(query)` | 保存済みIR文書の全文をチャットに取り込む(`query`は企業名/doc_idの一部。015の`get_paper_full_text`と同じ0件/複数件時の案内方針) |
| `list_ir_documents()` | 保存済みIR文書一覧をgenerative UIで表示(`list_papers`と同じパターン) |

015の論文モード(state駆動の動的instructions)と同じ仕組みを、IR文書についても再利用できるかは未決定事項に記載(下記参照)。

## 受け入れ条件

- EDINETのdocIDを1件貼ると、Item + IrRecordが永続化され、PDFが保存される
- 同じdocIDを再度貼っても重複登録されない
- 「〇〇社の有価証券報告書の売上は?」のような質問に、保存済みIR文書の全文をもとに回答できる
- 保存済み一覧が`list_ir_documents`でgenerative UI表示される
- 「株を買うべきか」のような投資助言を求める質問には、判断を避けて事実の整理に留める旨を回答する

## やらないこと(このspecの範囲外)

- 企業名・EDINETコードでの検索機能(docID直接入力のみ)
- SEC EDGAR(米国企業)対応
- ニュースとの関連付け
- XBRLの構造化解析(財務数値の抽出・グラフ化等)
- 投資助言(売買判断・価格予想等)

## 未決定事項

- Chunk/Embeddingを本当に作らなくてよいか(v1は上記の通り作らない判断だが、複数のIR文書を横断して比較したい需要が出たら見直す)
- 015の「論文モード」(AG-UI stateで「今読んでいる論文」を明示する仕組み)と同様の「IR文書モード」を用意するか。論文モードの実装(`PaperModeState`)がそのまま横展開できそうだが、v1では見送り、後で欲しくなったら015のパターンを踏襲して追加する
- EDINETアカウント登録・APIキー発行の具体的な手順は着手時にユーザー自身が行う(このリポジトリでは扱わない)

## 依存

- `002-papers-ingest-full`(PDF抽出・Hub/Satelliteパターン)
- `015-paper-qa-chat`(全文チャット方式のパターンを踏襲)
