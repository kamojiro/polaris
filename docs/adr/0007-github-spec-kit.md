# 0007. GitHub Spec Kitを採用する

## ステータス

採択

## コンテキスト

個人開発で、機能追加のたびに「何を作るか」の合意形成をどう進めるかを決める必要があった。このリポジトリを作成する前の設計段階で、OpenSpec・BMAD-METHODと比較検討している。ただし、その詳細な比較の議論ログは本リポジトリの外(`wishlist`フォルダ側)にあり、ここには残っていない。本ADRは決定の記録であり、比較の詳細な再現ではない。

## 決定

GitHub Spec Kitを採用し、spec-driven developmentで進める。人間が書いた下書き(`docs/constitution.draft.md`、`specs/*/spec.draft.md`)を`/speckit.constitution`→`/speckit.specify`のスラッシュコマンドに渡す運用にする。

## 検討した代替案

- OpenSpec: 比較検討はしたが、具体的な不採用理由は本リポジトリに記録が残っていない。
- BMAD-METHOD: 比較検討はしたが、具体的な不採用理由は本リポジトリに記録が残っていない。

## 結果(Consequences)

良い面: git管理下の`specs/`ディレクトリにspec本体(`spec.draft.md`、実装状況、未決定事項)が残り、実装リポジトリと設計ドキュメントが分離しない。スラッシュコマンドの運用がそのままClaude Codeでの開発ワークフローに乗る。

悪い面: Spec KitのCLI(`specify init`)自体は開発に使っているサンドボックス環境からはネットワーク制限で実行できず、ネットワーク制限のないマシン側で初期化する必要があった(`README.md`参照)。`.specify/`自体は結局未初期化のまま、`spec.draft.md`を直接実装する運用に落ち着いている。

## 関連

- `README.md`
- `docs/constitution.draft.md`
