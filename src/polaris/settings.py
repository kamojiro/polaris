"""アプリケーション設定."""

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseModel):
    """LLM(OpenRouter)接続設定.

    モデル選択は設定値の切替のみで行い、コードに埋め込まない(constitution 参照)。
    開発フェーズは無料枠の Qwen3-30B-A3B、本番フェーズは Qwen3.6-35B-A3B を想定。
    """

    api_key: str = ""
    base_url: str = "https://openrouter.ai/api/v1"
    model_id: str = "qwen/qwen3-30b-a3b:free"
    # 実測(2026-08-30、specs/IDEAS.md記録の「toolのstreaming時ハング」不具合の原因調査)により、
    # OpenRouter上でqwen/qwen3.6-35b-a3bを配信する`AkashML`プロバイダが、tool呼び出しの引数
    # ストリーミング開始直後に生成を停止する不具合を高頻度(生SSEの直接検証で6回中4回)で
    # 起こすと確認した。OpenRouterのゲートウェイはこれをエラーにせず`: OPENROUTER PROCESSING`の
    # キープアライブコメントを送り続けるため、httpxの読み取りタイムアウトはリセットされ続け、
    # 何もしなければクライアント側は無期限にハングする(pydantic-ai/自前コードのバグではない)。
    # OpenRouterのprovider routing機能で当該プロバイダを除外することで解消する(除外後は
    # 8回中8回とも1〜4秒でクリーンに完了、別プロバイダ`Parasail`に固定でルーティングされた)。
    openrouter_ignore_providers: list[str] = ["AkashML"]


class IngestSettings(BaseModel):
    """論文 Ingest パイプライン(002-papers-ingest-full)の設定.

    Embedding モデルは ADR-0001 / spec.draft.md で決定済み(Qwen3-Embedding-0.6B、
    sentence-transformers 経由でローカルロード)。チャンク分割の粒度は未確定のため、
    設定値で調整できるようにしておく。

    ADR-0011により Ingest 時の Embedding 生成は一時停止しており、
    `embedding_model_id`/`embedding_dim`は現在どこからも参照されていない
    (`embedding_dim`のみ`create_db_engine`のvec0テーブル次元指定に残る)。
    """

    pdf_dir: str = "data/pdfs"
    embedding_model_id: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_dim: int = 1024
    chunk_chars: int = 1200
    chunk_overlap_chars: int = 200
    # 014-paper-url-pdf-ingest: URL直リンク・ローカルPDFの取り込み用設定。
    upload_dir: str = "data/uploads"
    max_pdf_bytes: int = 50_000_000
    # 非arXiv論文のメタデータ抽出(agent/extract_metadata.py)に渡す本文先頭の文字数。
    # 長すぎるとプロンプトが肥大化するだけなので、書誌情報が載っている冒頭のみで十分。
    metadata_head_chars: int = 4000


class ChatSettings(BaseModel):
    """チャットエージェント本体(agent/chat_agent.py)の設定(015-paper-qa-chat)."""

    # 実測: 保存済み論文の抽出全文は 35k〜151k 文字。200k(≒57kトークン)なら
    # 現行モデル(Qwen3-30B-A3B: 131K コンテキスト)に収まり、実データ全件をカバーできる。
    max_full_text_chars: int = 200_000
    # チャットUIのコスト表示(USD→JPY)用の固定為替レート。為替APIは個人用ツールには
    # 過剰なため呼び出さず、相場が動いたら手動でこの値を更新する運用にする。
    usd_jpy_rate: float = 159.0


class TavilySettings(BaseModel):
    """Tavily検索APIへの接続設定(018-web-search-tool、2026-09-14にSearXNGから移行).

    自前ホスト済みSearXNGは検索結果の質(関連度・情報の新しさ)が不十分だったため、
    LLM向けに作られたホスト型の検索API(Tavily)に切り替えた。APIキー認証が必須の
    サービスのため、`api_key`が未設定(空文字列)の場合は機能自体を無効化する
    (discord.bot_tokenと同じゲート方式)。キーは秘密情報なので値そのものをリポジトリに
    コミットしない(`.env`経由、既にgitignore対象)。
    """

    api_key: str = ""
    base_url: str = "https://api.tavily.com"
    # 実測(SearXNG時代): results 1件あたり210〜399文字。10件でも3.2k文字程度だが、
    # 他のツールと共存するチャットのコンテキストを無駄に膨らませないため既定は5件に絞る。
    max_results: int = 5
    timeout_seconds: float = 10.0
    # Tavilyの`include_answer`(LLM向け要約回答)。SearXNGのanswers相当で、情報密度が
    # 高くコストもほぼゼロなので既定で有効にする。
    include_answer: bool = True


class DiscordSettings(BaseModel):
    """Discord連携(021-discord-integration 方向性3: 読み取り→サイドバー表示)の設定.

    メッセージ本体の永続化はしない(サイドバー表示のたびにDiscord APIをライブに叩くだけ)。
    `bot_token`/`channel_id`が未設定(空文字列)の場合、API側で機能自体を無効化する
    (`GET /api/discord/recent`が空リストを返す)。
    """

    bot_token: str = ""
    channel_id: str = ""
    max_messages: int = 5
    timeout_seconds: float = 10.0
    # LLM生成のdisplay_titleだけをメッセージid単位でキャッシュするJSONファイル
    # (投稿後にメッセージ本文はほぼ変わらないため、同じメッセージへの再生成を避ける)。
    # NewsRecordのようなDB化はせず、単純なファイルキャッシュに留める(YAGNI)。
    title_cache_path: str = "data/discord_title_cache.json"


class MemorySettings(BaseModel):
    """チャットの長期記憶(017-chat-memory)の設定."""

    # テーマごとの現在状態ファイル(<slug>.md)の保存先。ログ層(MemoryEvent)はDBだが、
    # 会話に読み込ませる実体はこちら(ingest.pdf_dirと同じ「ディレクトリ設定+都度読み書き」パターン)。
    dir: str = "data/memory"
    # 想起(前処理、毎ターン同期呼び出し)専用のモデル。短いユーザー発言をテーマ索引の
    # 短い説明文と照合するだけの単純な分類タスクのため、メインのチャットモデル
    # (llm.model_id)より軽量なモデルで十分と判断し、明示的に分離できるようにした
    # (2026-08-26)。Qwen3-8B は131Kコンテキストで低コスト、この用途には過剰なほど軽い。
    recall_model_id: str = "qwen/qwen3-8b"


class NewsFeed(BaseModel):
    """1件のRSS/Atomフィード設定(008-daily-digest-domain Phase A)."""

    name: str
    url: str
    label: str  # source_label(対立軸の定義方針、spec参照)。フィード単位で静的に決まる
    # True の場合、LLM要約(structure_news)を呼ばずタイトルのみで表示する。
    # arXiv系フィードは1日あたりの流量がRSSの実効上限(20件)の数十倍に達する
    # (2026-08-26実機調査: cs.LG+cs.AI+cs.MA+cs.IRで565件/日、cs.SEで62件/日)ため、
    # 全件を要約付きフルエントリとして扱うのはLLM呼び出し回数・表示量ともに破綻する。
    # 「興味判定はabstractで十分、arXiv自体は1行(タイトル)で十分」という判断
    # (2026-08-27)により、arXiv系フィードは要約生成をスキップしてタイトルのみの
    # カタログ的な一覧として扱う。他記事から個別に参照されている論文をちゃんと
    # 読んで説明を付け加える案は specs/IDEAS.md に記録済み(将来の別実装)。
    skip_summary: bool = False
    # Noneの場合は NewsSettings.max_entries_per_feed を使う。skip_summary=Trueの
    # フィードはLLM呼び出しコストが無いため個別に上限を引き上げられる。
    max_entries: int | None = None


class NewsSettings(BaseModel):
    """RSS Ingest(008-daily-digest-domain Phase A)の設定.

    既定のフィード一覧はspecで実機確認済みのもの(2026-08-26)。ニュースレター系
    (Ahead of AI等)・非公式ミラー系(HF Papers等)はspecが明記した運用リスク
    (ミラー停止で静かに壊れる)により既定からは除外している。必要になれば
    ここに追加するだけでよい。
    """

    feeds: list[NewsFeed] = [
        # ai_llm
        NewsFeed(
            name="arXiv (cs.LG+cs.AI+cs.MA+cs.IR)",
            url="https://rss.arxiv.org/rss/cs.LG+cs.AI+cs.MA+cs.IR",
            label="ai_llm",
            skip_summary=True,
            max_entries=100,
        ),
        NewsFeed(name="Simon Willison", url="https://simonwillison.net/atom/everything/", label="ai_llm"),
        # swe_general
        NewsFeed(
            name="arXiv (cs.SE)",
            url="https://rss.arxiv.org/rss/cs.SE",
            label="swe_general",
            skip_summary=True,
            max_entries=70,
        ),
        NewsFeed(name="Martin Fowler", url="https://martinfowler.com/feed.atom", label="swe_general"),
        NewsFeed(name="InfoQ", url="https://www.infoq.com/feed/", label="swe_general"),
        NewsFeed(
            name="The Pragmatic Engineer", url="https://newsletter.pragmaticengineer.com/feed", label="swe_general"
        ),
        NewsFeed(name="Julia Evans", url="https://jvns.ca/atom.xml", label="swe_general"),
        NewsFeed(name="the morning paper", url="https://blog.acolyer.org/feed/", label="swe_general"),
        # jp_tech_blog
        NewsFeed(name="Zenn トレンド", url="https://zenn.dev/feed", label="jp_tech_blog"),
        NewsFeed(name="Qiita トレンド", url="https://qiita.com/popular-items/feed", label="jp_tech_blog"),
        NewsFeed(
            name="はてなブックマーク テクノロジー", url="http://b.hatena.ne.jp/hotentry/it.rss", label="jp_tech_blog"
        ),
        # tech_industry_news
        NewsFeed(name="Hacker News (hnrss)", url="https://hnrss.org/frontpage", label="tech_industry_news"),
    ]
    # 1フィードあたりの取り込み上限(暴走防止。はてブ等は大量に流れてくるため)。
    max_entries_per_feed: int = 20
    timeout_seconds: float = 15.0


class DailySummarySettings(BaseModel):
    """日次サマリー通知(023-daily-summary-notification)の設定.

    チャットのターンに紐づかない初めての処理(`docs/adr/0003-chat-turn-pipeline.md`の
    対象外)で、`008-daily-digest-domain` Phase Aと同じOS cron駆動のCLI(`cli/generate_daily_summary.py`)
    から呼ぶ想定。
    """

    # 「1日」の区切りをJST基準にする(DB保存はすべてUTCだが、生活時間の区切りは
    # 生活圏のタイムゾーンであるべきという判断)。ZoneInfoに渡せる文字列。
    timezone: str = "Asia/Tokyo"


class IrSettings(BaseModel):
    """IR文書(有価証券報告書等)Ingestパイプライン(013-ir-analysis-domain)の設定.

    EDINET API v2は書類取得・書類一覧のいずれも`Subscription-Key`(無料登録で
    発行されるAPIキー)が必須(`LLMSettings.api_key`と同じ形で持つ)。
    `edinet_base_url`はEDINET公式ドキュメント記載のv2ベースURL(2026-08-22 spec調査時点)。
    アカウント登録・APIキー発行の手順はこのリポジトリでは扱わない(spec「未決定事項」参照)。
    """

    edinet_api_key: str = ""
    edinet_base_url: str = "https://disclosure.edinet-fsa.go.jp/api/v2"
    pdf_dir: str = "data/ir_pdfs"
    # IR文書のメタデータ抽出(agent/extract_ir_metadata.py)に渡す本文先頭の文字数。
    # ingest.metadata_head_charsと同じ理由(書誌情報は冒頭に載っているため十分)。
    metadata_head_chars: int = 4000


class SemanticScholarSettings(BaseModel):
    """Semantic Scholar Academic Graph API(027-related-paper-research)への接続設定.

    無認証アクセスは実測で成功2回・429が5回(2026-09-12、共有プールのレート制限)と
    非常に不安定なため、APIキーを必須にする。`api_key`が未設定(空文字列)の場合、
    `research_related_papers`ツール側で機能自体を無効化する(discord.bot_tokenと同じ
    ゲート方式)。キーがあっても429は起こりうる前提で、全リクエストに指数バックオフ
    (`max_attempts`/`backoff_base_seconds`/`backoff_max_seconds`)を掛ける。
    """

    api_key: str = ""
    base_url: str = "https://api.semanticscholar.org/graph/v1"
    timeout_seconds: float = 20.0
    # 指数バックオフの試行回数(2s→4s→8sの間隔で待つ、1回の待ちはbackoff_max_secondsで打ち切り)。
    max_attempts: int = 4
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 30.0
    # リトライとは別に、成功時もリクエスト間に挟む最小間隔(そもそも429を出させないための予防側)。
    min_interval_seconds: float = 1.0


class PaperResearchSettings(BaseModel):
    """関連論文調査(027-related-paper-research ユーザーストーリー1)の設定.

    引用チェイニング(発見)の絞り込みパラメータはspecが「実装時にチューニングが要る」と
    明記した未決定事項のため、すべて設定値として外に出す。
    """

    # 想起(memory.recall_model_id)と同じ「軽い判定は軽いモデル」という判断。
    triage_model_id: str = "qwen/qwen3-8b"
    references_limit: int = 30
    citations_limit: int = 30
    hop2_seed_count: int = 5   # 2hopを広げる1hop論文の数(被引用数上位)
    hop2_citations_limit: int = 10
    search_limit: int = 10
    max_candidates: int = 60
    triage_batch_size: int = 10
    max_deep_read: int = 8
    # chat.max_full_text_chars(200k)より絞る: 1調査で最大max_deep_read本読むため。
    analysis_max_chars: int = 60_000
    max_records_per_run: int = 1
    stale_in_progress_minutes: int = 120
    max_record_attempts: int = 2


class WakeWordSettings(BaseModel):
    """ウェイクワード検知(026-voice-input Stage 1.5)の設定.

    Whisper tiny.enの凍結エンコーダー(768次元 = 384次元のmean+max pooling)の上に
    ロジスティック回帰を1つだけ乗せた軽量モデル(`model.npz`)でホットワードを検知する。
    `model.npz`は自分の声・自分のウェイクワードにチューニングした個人用データのため
    リポジトリにコミットしない。`model_path`が未設定(空文字列)の場合、機能自体を
    無効化する(discord.bot_tokenと同じゲート方式)。
    """

    model_path: str = ""
    whisper_model_id: str = "tiny.en"
    threshold: float = 0.5
    # 移植元(realtime_detect_whisper.py)のLOG_THRESHOLD相当。検出扱いにはしないが、
    # 閾値調整のために「惜しいスコア」をログへ残す。
    log_threshold: float = 0.3
    sample_rate: int = 16000
    window_seconds: float = 2.0
    chunk_seconds: float = 0.4
    n_pool_frames: int = 100


class AmbientVoiceSettings(BaseModel):
    """常時音声認識+定期バッチ判断(026-voice-input Stage2代替案)の設定.

    ウェイクワード(WakeWordSettings)とは別に、常時マイクをONにして発話をバッファに溜め、
    一定間隔でLLMに「反応する価値があるか」を判定させる機能。常時マイクオンという性質上、
    discord.bot_tokenのような「空文字なら無効」ではなく明示的なboolで既定を無効にする
    (誤って有効化しないようにするため)。
    """

    enabled: bool = False
    # 想起(memory.recall_model_id)・triage(paper_research.triage_model_id)と同じ
    # 「軽い判定は軽いモデル」という判断。
    judge_model_id: str = "qwen/qwen3-8b"
    # クライアント側がバッファをフラッシュする間隔の目安(秒)。バックエンド側の設定値だが、
    # フロントの`GET /api/ambient-voice/enabled`経由で参照させ、両者で値をずらさないようにする。
    max_wait_seconds: int = 60
    max_records_per_run: int = 5
    stale_in_progress_minutes: int = 10
    max_record_attempts: int = 2


class Settings(BaseSettings):
    """アプリケーション全体の設定.

    `.env` ファイルおよび環境変数(`LLM__` / `INGEST__` プレフィクスでネスト)から読み込む。
    """

    DB_PATH: str = "data/polaris.db"
    LOG_LEVEL: str = "INFO"
    LOG_PATH: str = "data/polaris.log"
    # Ingestパイプラインのステージ進行ログはリクエストごとに数十行出て他のログに
    # 埋もれやすいため、専用ファイルに分けて追いやすくする(コンソール/LOG_PATHにも引き続き出る)。
    # 名称はADR-0011適用前(Embeddingのバッチ進捗・GPUメモリ診断ログ用)の経緯のまま。
    GPU_LOG_PATH: str = "data/gpu.log"

    llm: LLMSettings = LLMSettings()
    ingest: IngestSettings = IngestSettings()
    chat: ChatSettings = ChatSettings()
    tavily: TavilySettings = TavilySettings()
    memory: MemorySettings = MemorySettings()
    news: NewsSettings = NewsSettings()
    daily_summary: DailySummarySettings = DailySummarySettings()
    ir: IrSettings = IrSettings()
    discord: DiscordSettings = DiscordSettings()
    semantic_scholar: SemanticScholarSettings = SemanticScholarSettings()
    paper_research: PaperResearchSettings = PaperResearchSettings()
    wake_word: WakeWordSettings = WakeWordSettings()
    ambient_voice: AmbientVoiceSettings = AmbientVoiceSettings()

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_nested_delimiter="__",
    )
