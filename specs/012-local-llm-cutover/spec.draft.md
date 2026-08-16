# 012. ローカルLLMへの本番切替

## ステータス

未着手(スケルトンのみ、Phase 4)

## 概要

Layer0のモデル抽象(OpenRouter経由のQwen3系)を活かし、本番運用をローカルホストのLLMに切り替える。pydantic-aiのModel抽象により設定切替のみで対応できる設計は既にできている想定。

## 前提・依存

- Eval harness(005)でdev/prodモデルの比較実績があると、切替判断がしやすい

## 詳細

着手時に詰める。判断材料は `wishlist/wishlist-design.md` Layer0、6章を参照。
