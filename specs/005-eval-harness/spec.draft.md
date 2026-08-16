# 005. Eval harness(pydantic_evals)

## ステータス

未着手(スケルトンのみ、設計はwishlist側でかなり詳細化済み)

## 概要

pydantic_evals(Dataset/Case/Evaluator)を土台に、スキーマ妥当性率・tool call選択精度・リトライ発生率・レイテンシ(p50/p95)・コスト・世代差分の6指標を測定する仕組みを作る。dev(Qwen3-30B-A3B)/prod(Qwen3.6-35B-A3B)の比較や、モデル世代交代時の改善幅の可視化に使う。

## 前提・依存

- `002-papers-ingest-full` が動いていること(検証データが実データとして手に入るタイミングで着手するのが望ましい)

## 詳細

設計は `wishlist/wishlist-design.md` 7章に既に詳細化されている(各指標の実装方針・注意点まで記載済み)。着手時はそこから素直にspec化できるはず。特に「スキーマ妥当性率は`retries=0`固定の専用評価が必要」という落とし穴に注意。
