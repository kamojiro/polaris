"""FastAPI アプリケーション(AG-UI 経由のチャットエンドポイント)."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from datetime import date, datetime  # noqa: TC003 (pydanticがランタイムで解決するため実importが必要)
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ag_ui.core import BaseEvent, CustomEvent, MessagesSnapshotEvent, RunAgentInput, StateSnapshotEvent
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.ui.ag_ui import AGUIAdapter

from polaris.adapters.embeddings.qwen import QwenEmbedder
from polaris.agent.chat_agent import ChatDeps, PaperModeState, build_chat_agent
from polaris.agent.extract_metadata import AgentPaperMetadataExtractor, build_extract_metadata_agent
from polaris.agent.memory_extract import (
    AgentMemoryExtractor,
    AgentMemoryRewriter,
    build_memory_extract_agent,
    build_memory_rewrite_agent,
)
from polaris.agent.memory_recall import AgentMemoryRecaller, build_memory_recall_agent
from polaris.agent.sidebar_title import AgentSidebarTitler, build_sidebar_title_agent
from polaris.agent.structure_paper import AgentPaperStructurer, build_structure_agent
from polaris.db.daily_summary_repository import DailySummaryRepository
from polaris.db.memory_repository import MemoryRepository
from polaris.db.news_repository import NewsRepository
from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.db.todo_repository import TodoRepository
from polaris.services.history_trim import trim_stale_full_text_results
from polaris.services.memory import extract_and_store_memory, recall_memory
from polaris.services.progress import get_progress_lines
from polaris.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from ag_ui.core import Message
    from fastapi.responses import Response
    from pydantic_ai.run import AgentRunResult

# 進捗メッセージが変化していないかの内部チェック間隔。クライアントへの問い合わせではなく
# サーバー内でのポーリングなので、間隔を詰めてもネットワーク負荷は発生しない。
_PROGRESS_CHECK_INTERVAL_S = 0.2

# アップロードされたPDFのマジックバイト検証用(Content-Typeはブラウザ・クライアント次第で
# 信用できないため)。
_PDF_MAGIC_BYTES = b"%PDF"

# ログファイルの上限サイズ。Embeddingのバッチ進捗など出力頻度が高いログもあるため、
# 無制限に肥大化しないようローテーションする(直近分だけ残ればよい個人用ツールのため)。
_LOG_FILE_MAX_BYTES = 5_000_000
_LOG_FILE_BACKUP_COUNT = 3

logger = logging.getLogger(__name__)

settings = Settings()
# LOG_LEVEL は Settings で受け取るだけでは実際のログ出力に反映されないため、
# ここで明示的に root logger を設定する(polaris.* のログもここから出る)。
# ターミナルのスクロールバックを遡らなくて済むよう、ファイルにも同時出力する。
_log_path = Path(settings.LOG_PATH)
_log_path.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            _log_path,
            maxBytes=_LOG_FILE_MAX_BYTES,
            backupCount=_LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        ),
    ],
)
# Ingestパイプライン(ステージ進行)とEmbeddingのバッチ進捗・GPUメモリ診断ログは
# 量が多く他のログに埋もれやすいので、専用ファイルに分けて追いやすくする
# (root loggerへの伝播はそのままなので、コンソール・LOG_PATH にも引き続き出る)。
_gpu_log_path = Path(settings.GPU_LOG_PATH)
_gpu_log_path.parent.mkdir(parents=True, exist_ok=True)
_gpu_log_handler = RotatingFileHandler(
    _gpu_log_path,
    maxBytes=_LOG_FILE_MAX_BYTES,
    backupCount=_LOG_FILE_BACKUP_COUNT,
    encoding="utf-8",
)
_gpu_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
for _logger_name in ("polaris.services.ingest_paper", "polaris.adapters.embeddings.qwen"):
    logging.getLogger(_logger_name).addHandler(_gpu_log_handler)

_engine = create_db_engine(settings.DB_PATH, embedding_dim=settings.ingest.embedding_dim)
_repo = PaperRepository(_engine)
_todo_repo = TodoRepository(_engine)  # 007-todo-domain: Paperと同じSQLiteファイルを使う
_memory_repo = MemoryRepository(_engine)  # 017-chat-memory: 同上
_news_repo = NewsRepository(_engine)  # 008-daily-digest-domain Phase A: 同上
_daily_summary_repo = DailySummaryRepository(_engine)  # 023-daily-summary-notification: 同上(読み取り専用)
# Embedding モデルはプロセス起動時に 1 度だけロードする(初回は数十秒かかる)。
_embedder = QwenEmbedder(settings.ingest.embedding_model_id)
_structurer = AgentPaperStructurer(build_structure_agent(settings))
_extractor = AgentPaperMetadataExtractor(build_extract_metadata_agent(settings))
_memory_recaller = AgentMemoryRecaller(build_memory_recall_agent(settings))
_memory_extractor = AgentMemoryExtractor(build_memory_extract_agent(settings))
_memory_rewriter = AgentMemoryRewriter(build_memory_rewrite_agent(settings))
_sidebar_titler = AgentSidebarTitler(build_sidebar_title_agent(settings))
_agent = build_chat_agent(
    settings,
    _repo,
    embedder=_embedder,
    structurer=_structurer,
    extractor=_extractor,
    todo_repo=_todo_repo,
    news_repo=_news_repo,
)

_upload_dir = Path(settings.ingest.upload_dir)
_upload_dir.mkdir(parents=True, exist_ok=True)

# 017-chat-memory: バックグラウンドで走らせる記憶抽出タスクへの強参照。asyncio.create_task が
# 返す Task はどこからも参照されないとGCされ、タスクの途中で実行が打ち切られることがある
# (Python公式ドキュメントで明記されている既知の落とし穴)ため、完了まで参照を保持する。
_background_tasks: set[asyncio.Task[None]] = set()

app = FastAPI(title="Polaris")


@app.middleware("http")
async def log_request_duration(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """リクエスト全体(LLMのストリーミング完了まで)にかかった時間をログに出す.

    `/api/chat` は SSE のストリーミングレスポンスのため、`AGUIAdapter.dispatch_request`
    の戻り値自体はすぐ返る(ストリームの構築のみ)。ASGI ミドルウェアはレスポンスの
    送信完了まで待ってから戻るため、ここで計測すればストリーム完了までの実時間になる。
    """
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    logger.info("%s %s completed in %.2fs (status=%d)", request.method, request.url.path, elapsed, response.status_code)
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    """フロントエンドからの疎通確認用."""
    return {"status": "ok"}


@app.get("/api/progress/stream")
async def progress_stream(request: Request) -> StreamingResponse:
    """実行中の ingest 処理の進捗(例: 要約生成・Embedding生成それぞれの状況)を SSE で push する.

    要約生成とEmbedding生成は並行して走るため、`get_progress_lines()` は
    同時に複数行(例: 「要約生成完了」「Embedding生成中: 40/74 チャンク完了」)を
    返しうる。`/api/chat` の AG-UI ストリームとは別チャネル(pydantic-ai の AG-UI
    アダプタにはツール実行中の途中経過を同じストリームに乗せる仕組みが無いため)。
    ただし配信方式は揃えて SSE にし、クライアント側からの繰り返しの問い合わせ
    (ポーリング)は発生させない。
    """

    async def events() -> AsyncIterator[str]:
        last: list[str] | None = None  # 初回は必ず1回送るため、空リストとも区別できる値にしておく
        while not await request.is_disconnected():
            current = get_progress_lines()
            if current != last:
                last = current
                yield f"data: {json.dumps({'lines': current})}\n\n"
            await asyncio.sleep(_PROGRESS_CHECK_INTERVAL_S)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/papers/upload")
async def upload_paper_pdf(file: UploadFile) -> dict[str, str]:
    """ローカルPDFをアップロードし、Ingest本体(save_paperツール)から参照できる ID を発行する.

    014-paper-url-pdf-ingest: ここでは取り込みは行わない(保存のみ)。フロントは
    返ってきた upload_id を `upload://<id>` としてチャットメッセージに埋め込み、
    通常の save_paper ツール経由で取り込む。これにより進捗SSE・チャット履歴・
    一覧更新の既存の導線がそのまま使える(ingestの入口をエージェント1本に保つ)。
    """
    content = await file.read()
    if len(content) > settings.ingest.max_pdf_bytes:
        raise HTTPException(status_code=413, detail="PDFのサイズが上限を超えています。")
    if not content.startswith(_PDF_MAGIC_BYTES):
        raise HTTPException(status_code=400, detail="PDFファイルとして認識できませんでした。")

    upload_id = uuid.uuid4().hex
    upload_path = _upload_dir / f"{upload_id}.pdf"
    await asyncio.to_thread(upload_path.write_bytes, content)
    logger.info("PDFアップロード完了: upload_id=%s, filename=%s, %dバイト", upload_id, file.filename, len(content))
    return {"upload_id": upload_id, "filename": file.filename or "アップロードされたPDF"}


class SidebarNewsItem(BaseModel):
    """ニュースサイドバーの1件分(008-daily-digest-domain拡張)."""

    display_title: str
    title: str
    source_name: str
    source_label: str
    published_at: datetime
    source_url: str


# サイドバーの抽選プール(ラベルごとの直近件数)。list_news のチャット向け表示上限
# (chat_agent._RECENT_NEWS_LIMIT_PER_LABEL)とは独立に、サイドバー用にやや広めに取る。
_SIDEBAR_POOL_PER_LABEL = 30


@app.get("/api/news/picks")
async def news_picks(count: int = 5) -> list[SidebarNewsItem]:
    """取り込み済みニュースからランダムに`count`件選び、表示用の短い見出しをLLMで生成して返す(008-daily-digest-domain拡張).

    チャットの`list_news`ツール(チャット履歴の一部としてのみ表示される)とは別に、
    ページを開いた時点でアンビエントに表示したいサイドバー用の専用エンドポイント。
    見出し生成はここで選ばれた数件分だけなのでLLM呼び出しコストは小さい
    (arXivフィードの565件全部を判定するような設計は避けている、settings.pyの
    NewsFeed.skip_summary docstring参照)。
    """
    pool = _news_repo.list_news(limit_per_label=_SIDEBAR_POOL_PER_LABEL)
    if not pool:
        return []
    picked = random.sample(pool, k=min(count, len(pool)))
    display_titles = await asyncio.gather(
        *(_sidebar_titler.title(title=item.title, summary=item.summary) for item, _ in picked)
    )
    return [
        SidebarNewsItem(
            display_title=display_title.display_title,
            title=item.title,
            source_name=record.source_name,
            source_label=record.source_label,
            published_at=record.published_at,
            source_url=record.source_url,
        )
        for (item, record), display_title in zip(picked, display_titles, strict=True)
    ]


class DailySummaryResponse(BaseModel):
    """日次サマリーの1件分(023-daily-summary-notification)."""

    summary_date: date
    content: str
    generated_at: datetime


@app.get("/api/daily-summary/latest")
def daily_summary_latest() -> DailySummaryResponse | None:
    """最新の日次サマリーを返す(無ければ`null`)。生成はここでは行わない(CLI専用、cron駆動).

    ページロード時にフロントが叩き、既読管理(最終既読日付との比較)はフロント側の
    localStorageで行う(サーバー側にread状態を持たせない、spec確定事項)。
    """
    record = _daily_summary_repo.get_latest()
    if record is None:
        return None
    return DailySummaryResponse(
        summary_date=record.summary_date, content=record.content, generated_at=record.generated_at
    )


async def _emit_usage_event(result: AgentRunResult[Any]) -> AsyncIterator[BaseEvent]:
    """ターンごとのトークン使用量・コストを AG-UI の CUSTOM イベントとしてフロントに渡す.

    015-paper-qa-chat追加分。`RunUsage`(このターン内の複数リクエストの合算値)を
    そのまま JSON 化して送るだけ。CachePoint は今のモデル(qwen系)では
    `openrouter_supports_cache_control=False` のため no-op だが、プロバイダ側の
    自動キャッシュが効くことがあるため `cache_read_tokens` を見れば実際にヒットしたか
    ターンごとに分かる(specの実測結果参照)。

    コストは USD(`usage.cost`)に加えて、`settings.chat.usd_jpy_rate`(手動更新の
    固定レート、為替APIは呼ばない)で換算した JPY も一緒に送る。
    """
    usage = result.usage
    cost_usd = float(usage.cost) if usage.cost is not None else None
    yield CustomEvent(
        name="usage",
        value={
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "cost_usd": cost_usd,
            "cost_jpy": cost_usd * settings.chat.usd_jpy_rate if cost_usd is not None else None,
        },
    )


def _tool_call_durations(result: AgentRunResult[Any]) -> list[tuple[str, float]]:
    """このターンで呼ばれたtoolそれぞれの実行時間(秒)を算出する.

    `pydantic_ai`はtool呼び出し(`ToolCallPart`、`ModelResponse.timestamp`)と
    その結果(`ToolReturnPart.timestamp`)の両方に既にタイムスタンプを打っているため、
    差分を取るだけで済む(tool関数側やtoolset側に計測コードを仕込む必要がない)。
    これは`web_fetch`のようにこちらで定義していないtool(pydantic-ai同梱)の
    実行時間も同じ仕組みで取れる利点がある。実機確認(2026-08-27):テスト用の
    1.5秒sleepするtoolで、この方法で1.502秒という正しい差分が取れることを確認済み。
    """
    call_started_at: dict[str, tuple[str, datetime]] = {}
    durations: list[tuple[str, float]] = []
    for message in result.new_messages():
        for part in message.parts:
            # ToolCallPart は ModelResponse.parts にのみ現れる(モデルからの出力のため)。
            # ModelRequest.timestamp は datetime | None のため、message側もisinstanceで
            # 絞り込まないとpyrightがNoneの可能性を消せない。
            if isinstance(part, ToolCallPart) and isinstance(message, ModelResponse):
                call_started_at[part.tool_call_id] = (part.tool_name, message.timestamp)
            elif isinstance(part, ToolReturnPart) and part.tool_call_id in call_started_at:
                tool_name, started_at = call_started_at.pop(part.tool_call_id)
                durations.append((tool_name, (part.timestamp - started_at).total_seconds()))
    return durations


async def _emit_tool_timings_event(result: AgentRunResult[Any]) -> AsyncIterator[BaseEvent]:
    """このターンで呼ばれたtoolの実行時間を、ログとAG-UIのCUSTOMイベント両方に出す.

    ログ側は個々のtool関数が呼び出し開始時に出している`tool call: X(args)`とは
    別に、完了時の所要時間だけをまとめて出す(どのtoolが遅かったかを手元のログの
    タイムスタンプ差分で毎回手計算しなくて済むように)。フロント側は`usage`と
    同じCUSTOMイベントパターンでチャットの表示に使う(`useChatAgent.ts`参照)。
    """
    durations = _tool_call_durations(result)
    for tool_name, duration in durations:
        logger.info("tool call: %s took %.2fs", tool_name, duration)
    if durations:
        yield CustomEvent(
            name="tool_timings",
            value=[{"tool_name": name, "duration_seconds": duration} for name, duration in durations],
        )


def _trimmed_history_messages(result: AgentRunResult[Any]) -> list[Message]:
    """今回のターン完了時点の全履歴から、古い全文取得ツール結果をプレースホルダに置換したAG-UIメッセージ列を作る(ADR-0012).

    `result.all_messages()`(過去ターン分も含む全履歴)を対象にする必要がある
    (`new_messages()`は今回のターン分のみのため、過去ターンで取り込まれた全文結果が見えない)。
    `trim_stale_full_text_results` はpydantic-ai内部の`ModelMessage`列を返すだけなので、
    クライアントへ返せる形式にするには`AGUIAdapter`が`load_messages`と対で使っている
    `dump_messages`(AG-UI wire formatへの変換ロジック)にそのまま通す。
    """
    trimmed = trim_stale_full_text_results(result.all_messages())
    return AGUIAdapter.dump_messages(trimmed)


async def _emit_trimmed_history_event(result: AgentRunResult[Any]) -> AsyncIterator[BaseEvent]:
    """ADR-0012のトリミング結果を`MESSAGES_SNAPSHOT`としてフロントに送る.

    フロントの`HttpAgent`は`MESSAGES_SNAPSHOT`受信時に保持中の`agent.messages`をメッセージIDで
    突き合わせて反映する。`dump_messages`は毎回新規IDを振るため、旧メッセージとID一致するものは
    無く、実質的に丸ごと置き換わる(実装時に`@ag-ui/client`のソースで確認済み、ADR-0012参照)。
    これにより次のターン以降はクライアント自身が送り返す履歴も既にトリミング済みになる。
    """
    yield MessagesSnapshotEvent(messages=_trimmed_history_messages(result))


def _latest_user_text(run_input: RunAgentInput) -> tuple[str, str] | None:
    """直近のユーザー発言を (message id, テキスト) として返す(無ければ None).

    017-chat-memory の前処理・後処理どちらの入力にもなる。マルチモーダル内容
    (`UserMessage.content` が `list[InputContent]` の場合)は対象外(v1は素の
    フロントエンドから常に文字列が来る前提、`useChatAgent.ts`参照)。
    """
    for message in reversed(run_input.messages):
        if message.role == "user" and isinstance(message.content, str):
            return message.id, message.content
    return None


async def _extract_memory_task(user_text: str, assistant_text: str, *, turn_id: str) -> None:
    """017-chat-memory の後処理本体(fire-and-forgetで呼ばれる想定).

    `asyncio.create_task` から参照を持たずに呼ばれるため、ここで例外を捕まえて
    ログに残す(拾わなければ `Task exception was never retrieved` になるだけで
    チャット応答自体には影響しないが、原因調査ができなくなる)。
    """
    try:
        await extract_and_store_memory(
            user_text,
            assistant_text,
            turn_id=turn_id,
            extractor=_memory_extractor,
            rewriter=_memory_rewriter,
            repo=_memory_repo,
            settings=settings,
        )
    except Exception:
        logger.exception("chat memory extraction failed")


@app.post("/api/chat")
async def chat(request: Request) -> Response:
    """AG-UI プロトコルでチャットエージェントを実行する(ADR-0003の3段パイプライン).

    前処理(同期): 直近のユーザー発言から関連する記憶(017-chat-memory)を想起し、
    `deps.recalled_memory` に詰める。`AGUIAdapter.dispatch_request` は Request から
    自前でボディを読むが、`Request.body()` はキャッシュされるため、ここで先に
    読んでも問題ない。

    メイン処理: 既存の `_agent` をそのまま使う(変更なし)。

    後処理(非同期): 論文モード(015拡張)の state 同期・使用量イベントに加えて、
    ADR-0012(古い全文取得ツール結果のトリミング)の `MESSAGES_SNAPSHOT` 送出、
    017-chat-memory の記憶抽出を `asyncio.create_task` でバックグラウンド実行する
    (チャット応答をブロックしない)。
    """
    body = await request.body()
    run_input = AGUIAdapter.build_run_input(body)
    latest = _latest_user_text(run_input)

    deps = ChatDeps(state=PaperModeState())
    if latest is not None:
        _, user_text = latest
        deps.recalled_memory = await recall_memory(
            user_text, recaller=_memory_recaller, repo=_memory_repo, settings=settings
        )

    async def on_complete(result: AgentRunResult[Any]) -> AsyncIterator[BaseEvent]:
        async for event in _emit_usage_event(result):
            yield event
        async for event in _emit_tool_timings_event(result):
            yield event
        async for event in _emit_trimmed_history_event(result):
            yield event
        yield StateSnapshotEvent(snapshot=deps.state.model_dump(mode="json"))
        if latest is not None:
            turn_id, user_text = latest
            # build_chat_agent は Agent[ChatDeps, str] なので result.output は常に str。
            task = asyncio.create_task(_extract_memory_task(user_text, result.output, turn_id=turn_id))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

    return await AGUIAdapter.dispatch_request(request, agent=_agent, deps=deps, on_complete=on_complete)
