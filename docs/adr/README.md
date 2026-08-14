# ADR (Architecture Decision Records)

後戻りしにくい・理由を残しておきたい決定をここに1件ずつ記録する(Nygard/MADR形式: Context / Decision / Consequences)。specは「何を作るか」、ADRは「なぜその選択をしたか」を担当する。

まだ実装が始まっていないため空。最初の候補は以下(wishlist側の議論で既に方向性は決まっているもの):

- Hub/Satelliteパターンの採用(Item汎用 + PaperRecord等のsatellite)
- AG-UIプロトコル + `@ag-ui/client` 直接接続の採用(CopilotKit/Next.jsは不採用)
- OpenRouter経由のモデル抽象(dev: Qwen3-30B-A3B / prod: Qwen3.6-35B-A3B)
- GitHub Spec Kitの採用(OpenSpec/BMAD-METHODとの比較を経て)

実装が動き出したタイミングで `0000-template.md` をコピーし、`0001-...md` から番号を振って書き起こす。
