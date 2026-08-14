# Polaris

個人用の知識・生活管理プラットフォーム(実装コードネーム: Polaris)。

設計の経緯・議論のログは `wishlist` フォルダ側にある(`wishlist/wishlist-design.md`, `wishlist/discussion/`)。ここは実装リポジトリで、GitHub Spec Kit を使ったspec-driven developmentで進める想定。

## セットアップ(このマシンで実行する場合)

```bash
cd polaris
uvx --from git+https://github.com/github/spec-kit.git specify init --here
```

Cowork側のサンドボックスはネットワーク制限によりSpec KitのCLIをそのまま実行できなかったため、上記コマンドは実際に使うマシン(git・ネットワークに制限のない環境)側で実行すること。`git init` も同様にこちらで行う。

`specify init` を実行すると `.specify/` とスラッシュコマンド一式が入る。その後、下記の下書きをそのまま(または調整して)`/speckit.constitution` と `/speckit.specify` に渡す。

## ディレクトリ構成

```
docs/
  constitution.draft.md          # /speckit.constitution に渡す下書き
  adr/                            # 後戻りしにくい決定を記録する(実装が進んでから追加)
specs/
  README.md                       # spec一覧と着手可否のステータス表
  001-walking-skeleton/
    spec.draft.md                 # 最初の実装ターゲット。/speckit.specify に渡す下書き
  002-papers-ingest-full/
    spec.draft.md                 # walking skeletonの後に着手するフルIngestパイプライン
```

着手可否は `specs/README.md` を見ればわかる。

`.draft.md` はSpec Kitの正式なテンプレート(`spec.md`/`plan.md`/`tasks.md`)が生成される前の、人間が書いた種(seed)。`/speckit.specify` 等に渡した後は、生成された正式ファイルの方を正とする。
