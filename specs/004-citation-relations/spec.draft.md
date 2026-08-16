# 004. 引用関係取得(Semantic Scholar API)

## ステータス

未着手(スケルトンのみ)

## 概要

論文の引用/被引用関係をSemantic Scholar APIから取得し、PaperRecord側の詳細と、可視化グラフ用の汎用`Relation`テーブル(`cites`等)の二層構成で保存する。`002-papers-ingest-full`では意図的にオプション扱いにして外してある部分。

## 前提・依存

- `002-papers-ingest-full` が完了していること

## 詳細

着手時に詰める。判断材料は `wishlist/wishlist-design.md` 3-1節、`002-papers-ingest-full/spec.draft.md` の該当箇所を参照。
