# 0006. OpenRouter経由のモデル抽象を採用する

## ステータス

採択

## コンテキスト

LLMプロバイダ・モデルを直接コードに埋め込むと、開発時のモデル(コストを気にせず試行錯誤したい)と本番のモデル(品質重視)の切り替えや、将来`012-local-llm-cutover`でのローカルLLM移行の妨げになる。

## 決定

OpenRouterを唯一のモデルプロバイダ窓口とする。開発フェーズは`qwen/qwen3-30b-a3b:free`(無料)、本番フェーズは`qwen/qwen3.6-35b-a3b`を使う。モデル選択は設定値(`LLM__MODEL_ID`等、`.env`)の切替のみで行い、モデル名をコードに埋め込まない(`agent/model.py::build_model()`に集約)。

## 検討した代替案

- 各プロバイダのSDKを直接使う(Anthropic API、OpenAI APIを個別に呼ぶ等): プロバイダごとにコードパスが分岐し、切り替えコストが高い。OpenRouterは単一のOpenAI互換エンドポイントで多数のモデル・プロバイダを横断できるため、抽象化の手間を大部分肩代わりしてくれる。

## 結果(Consequences)

良い面: 開発中は無料枠モデルで試行錯誤し、コストを気にせずイテレーションできる。モデル切り替えが設定変更のみで完結する(想起専用の軽量モデルを追加した`017-chat-memory`の`settings.memory.recall_model_id`も、同じ`build_model()`にmodel_id上書きオプションを足すだけで対応できた)。

悪い面: OpenRouter経由であるがゆえに、モデル固有機能の挙動がプロバイダ・モデルの組み合わせに依存して不安定になることがある(`015-paper-qa-chat`で判明: `qwen`系モデルは`pydantic_ai`側で`openrouter_supports_cache_control=False`となっており、明示的な`CachePoint`(prompt caching)が黙ってno-opになる。実測されたキャッシュヒットはOpenRouter側の暗黙キャッシュの気まぐれだった)。単一のモデルベンダーに直結する場合より、こうした挙動の細かい制御は効きにくい。

## 関連

- `docs/constitution.draft.md`
- `015-paper-qa-chat`(prompt caching検証)
- `017-chat-memory`(想起用の軽量モデル分離)
- `012-local-llm-cutover`(将来)
