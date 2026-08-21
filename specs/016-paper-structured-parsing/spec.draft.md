# 016. 論文の構造化パース + 引用根拠付き回答(将来拡張)

## ステータス

未着手(スケルトンのみ、着手トリガー待ち)

## 着手トリガー

`015-paper-qa-chat`(full-context stuffing)を使ってみて、以下のような具体的な困りごとが実際に出てきたら着手する。今は仮説段階なので実装しない。

- 論文中の図表について質問したいのに、テキスト抽出だけでは答えられない
- 回答の根拠(どのsection/pageから来た情報か)を示してほしい、hallucinationの検証をしたい

## 概要

`015`の単純な全文stuffingに対して、PDFをパース段階で構造化しておくことで、引用根拠付き回答(citation grounding)と図表を使った質問に対応できるようにする。

## 想定する設計(たたき台)

- PDF → セクション単位のMarkdown化。title、abstract、section見出し、図表キャプション、参考文献リストを構造化する
- パースツール候補: GROBID(学術論文特化、セクション・参考文献・メタデータの構造化抽出に強い)、Docling(IBM)、marker(レイアウト認識+Markdown化)。単純な`pypdf`のテキスト抽出は数式・マルチカラムレイアウトで崩れやすいため、これらへの置き換えを検討する
- 図表は画像として別途保持し、質問が図表に触れたときだけマルチモーダル入力として画像を渡す(ページを画像としてラスタライズしてそのまま渡す方式も候補)
- データモデル(案):

```python
class Section(BaseModel):
    id: str
    heading: str
    page_range: tuple[int, int]
    text: str

class Figure(BaseModel):
    id: str
    caption: str
    page: int
    image_path: str

class PaperDocument(BaseModel):
    title: str
    sections: list[Section]
    figures: list[Figure]
    references: list[str]
```

- 回答生成時に「どのsection/pageを根拠にしたか」をPydantic AIのstructured outputで構造化させ、引用付き回答("p.4, Section 3.2より")を実現する

## 依存

- `015-paper-qa-chat`(まずこちらで様子を見る)
- `002-papers-ingest-full`
