<!-- /speckit.specify にそのまま渡す下書き -->

001-walking-skeletonで動いたチャットUIを、実際に見やすい・使えるレベルまで改善する。主にLayer4(UI層)の変更。一部Layer2(エージェント層)に跨る。

## 背景

001実装後、実際に使ってみて2つの問題が見つかった。

1. Markdownがレンダリングされず、`**bold**`等がそのままテキスト表示されている。フォントサイズ・余白も詰まっていて読みにくい。
2. 論文一覧がLLMの生成した文章としてそのまま表示されている。件数が増えると破綻するし、普通のチャット応答と区別がつかない。
3. チャットメッセージのコンポーネント自体が小さく、デスクトップで見てもスマホ表示のような細長いレイアウトになっている。単に最大幅を絞る(読みやすい行長にする)だけでなく、メッセージ吹き出し・パディング・フォントサイズなどコンポーネントのサイズ感そのものがデスクトップ前提になっていない。

## やりたいこと

### 1. Markdown描画とレイアウト調整(Layer4のみ)

- `react-markdown` + `remark-gfm` でアシスタントの応答を描画する(太字・番号リスト・表が正しく効くようにする)
- メッセージエリアの最大幅を700px前後に絞り中央寄せ(読みやすい行長にする)
- メッセージコンポーネント自体のサイズ感をデスクトップ前提に見直す。吹き出しのpadding、フォントサイズ、行間、ユーザー/アシスタントの発言間マージンを、モバイル的な細長い見た目にならないよう調整する(単なるコンテナ幅の制限とは別の課題として扱う)
- ベースフォントサイズ16px前後、line-height 1.6程度
- 発言間の余白を広げる
- 入力欄を入力量に応じて伸びるtextareaにする

### 2. 論文一覧のgenerative UI化(Layer2+Layer4)

- `list_papers` ツールの返り値を構造化データのまま(LLMに文章化させず)フロントに渡す。エージェント側は、ツール結果をそのままAG-UIのtool result payloadとして返し、後続のLLM応答は「一覧を表示しました」程度の短い相槌に留める
- フロントは `TOOL_CALL_END` イベントでツール名が `list_papers` の場合、専用のテーブル/カードコンポーネントで一覧を描画する(タイトル・`Item.summary`(概要)を表示、著者は表示しない)
  - `Item.summary`は002のStructureフェーズでIngest時に1回生成・保存済みのフィールドなので、一覧表示のたびにLLMを呼ぶ必要はない(読み取りのみ)。001時点で取り込んだ古いレコードはsummaryが空の可能性があるため要確認
- 件数が多い場合のページング・省略は本specでは最小限(例: 直近N件+「もっと見る」程度)でよい。本格的な検索・フィルタ付き一覧は別途ダッシュボード(Phase 3)で扱う

## 受け入れ条件

- 論文を保存した際の確認メッセージ、一覧表示のいずれもMarkdownが正しくレンダリングされる
- チャット全体の見た目がClaude.aiのような余白のある読みやすいレイアウトになっている
- デスクトップの画面幅で開いたときに、スマホ表示のような細長いレイアウトに見えない(メッセージコンポーネントのサイズ・余白がデスクトップに合っている)
- 「論文の一覧を表示して」と聞いたときの応答が、LLMの生成文ではなく専用コンポーネントによる一覧表示になっている

## やらないこと(このspecの範囲外)

- 検索・フィルタ付きの独立したダッシュボード画面(Phase 3で扱う)
- モバイル対応(PWA化)
- 論文一覧以外のtool(例: 保存確認)のgenerative UI化(必要になったら別specで)

## 追加提案: メッセージのコピーボタン(実装済み、2026-08-23提案・2026-08-26実装)

Claude.aiのように、各メッセージにhoverするとコピーボタンが出る機能。バックエンド・データモデルの変更は不要でLayer4のみの変更。

- `App.tsx`のメッセージ描画(現状154〜159行目、`bubble`のdiv)に、hoverで出る`message-actions`を追加し、そこに`CopyButton`コンポーネントを置く
- `CopyButton`は`navigator.clipboard.writeText()`でレンダリング後のHTMLではなく**markdownソーステキスト**(`messageText(message)`の戻り値)をコピーする。他のmarkdown対応先に貼りやすくするため
- コピー後は1.5秒程度アイコンをチェックマークに切り替えてフィードバックする
- アイコンは新規パッケージを入れずインラインSVGで済ませる(1個のアイコンのために依存を増やさない)
- user/assistant両方のbubbleに出すか、assistantのみにするかは実装時に判断してよい(Claudeは両方に出す)

実装イメージ(そのまま貼れる想定):

```tsx
// App.tsx: TEXTAREA_MAX_HEIGHT_PX の手前あたりに追加
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      type="button"
      className="copy-button"
      onClick={() => void handleCopy()}
      aria-label={copied ? "コピーしました" : "メッセージをコピー"}
    >
      {copied ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="9" y="9" width="13" height="13" rx="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
    </button>
  );
}
```

呼び出し側(既存のbubble描画のすぐ下に追加):

```tsx
{messageText(message) !== "" && (
  <div className={`message-actions message-actions-${message.role}`}>
    <CopyButton text={messageText(message)} />
  </div>
)}
```

`styles.css`には`.message-actions`(`.message-group:hover`で`opacity: 1`)と`.copy-button`のスタイルを追加する。`.bubble-pending`定義の直後あたりが自然。

## 追加提案: 入力欄の「論文一覧」クイックアクションボタン(実装済み、2026-08-23提案・2026-08-26実装)

Claude.aiの入力欄下部にある+ボタン/プロジェクトボタンのように、毎回「論文一覧ちょうだい」と打たなくても、composerのツールバーから一発で論文一覧を呼び出せるボタンを追加する。

- `App.tsx`の`.composer`内、既存の📎(attach)ボタンの隣に追加する
- クリックしたら`void sendMessage("論文一覧ちょうだい")`を呼ぶだけ。新しいtool・エンドポイントは不要で、既存の`list_papers`フローがそのまま動く(`015-paper-qa-chat`の「クリックで裏からメッセージを送る」パターンと同じ考え方)
- アイコンは既存の📎ボタンがSVGではなく絵文字を使っている(`{isUploading ? "…" : "📎"}`)のに合わせて、絵文字(例: 📚)で統一する

```tsx
<button
  type="button"
  className="quick-action"
  disabled={isRunning}
  onClick={() => void sendMessage("論文一覧ちょうだい")}
  title="論文一覧を表示"
>
  📚
</button>
```

`019-diary-domain`で提案した日記モードのトグルボタンも同じcomposerツールバーに置く想定なので、並び順は「📎 添付 → 📚 論文一覧 → 📔 日記モード → (送信)」のように、既存のattachボタンと見た目(サイズ・余白)を揃えて追加するのが自然。

