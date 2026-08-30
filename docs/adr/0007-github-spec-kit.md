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

## 追記(2026-08-30): 実際に導入、運用の役割分担を決定

Macで`specify init --here --integration claude`(script: sh)を実行し、`.specify/`・`.claude/skills/speckit-*`(`speckit-specify`/`clarify`/`plan`/`tasks`/`implement`等)が実際にインストールされた。導入時点の仕様では、Claude連携は`.claude/commands/`のスラッシュコマンドではなく**Claude Skill形式**(`SKILL.md`、`user-invocable: true`)で入る。

Cowork(このADRを含む設計会話をしている側)では、この`speckit-*`は`<available_skills>`に自動登録されないことを実機で確認した(接続フォルダ内の`.claude/skills/`をCoworkが必ずしも自動検出するわけではない)。そのため、次の役割分担で運用することにした。

- **Cowork**: 引き続き会話ベースで設計し、`spec.draft.md`・ADRに直接書く(このADRの本文がまさにその運用)。speckitの自動化には依存しない
- **Claude Code(実装機)**: `spec.draft.md`が固まったドメインについて、`/speckit.plan`→`/speckit.tasks`→`/speckit.implement`の**仕上げ工程だけ**をここに任せる。`spec.draft.md`の内容が`spec.md`相当になっていることが多いため、`/speckit.specify`は軽く流すかスキップしてよい
- **Cowork側でspec-kitのテンプレート形式に厳密に沿わせたいとき**: `SKILL.md`は単なるMarkdownの指示書なので、正式なSkill呼び出しではなく、ファイルを直接読んでその手順どおりに振る舞う(手動再現)ことでも近い結果は得られる。`.specify/scripts/`配下の補助スクリプトもシェルから直接叩ける
- Coworkへの正式移植(`save_skill`で複製)は、上記で困る場面が実際に出てきてから検討する。本家更新への追従が手動になるコストがあるため、今は見送り

## 関連

- `README.md`
- `docs/constitution.draft.md`
