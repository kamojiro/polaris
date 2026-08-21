"""FastAPI アプリケーション(AG-UI 経由のチャットエンドポイント)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic_ai.ui.ag_ui import AGUIAdapter

from polaris.adapters.embeddings.qwen import QwenEmbedder
from polaris.agent.chat_agent import build_chat_agent
from polaris.agent.extract_metadata import AgentPaperMetadataExtractor, build_extract_metadata_agent
from polaris.agent.structure_paper import AgentPaperStructurer, build_structure_agent
from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.db.todo_repository import TodoRepository
from polaris.services.progress import get_progress_lines
from polaris.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from fastapi.responses import Response

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
# Embedding モデルはプロセス起動時に 1 度だけロードする(初回は数十秒かかる)。
_embedder = QwenEmbedder(settings.ingest.embedding_model_id)
_structurer = AgentPaperStructurer(build_structure_agent(settings))
_extractor = AgentPaperMetadataExtractor(build_extract_metadata_agent(settings))
_agent = build_chat_agent(
    settings,
    _repo,
    embedder=_embedder,
    structurer=_structurer,
    extractor=_extractor,
    todo_repo=_todo_repo,
)

_upload_dir = Path(settings.ingest.upload_dir)
_upload_dir.mkdir(parents=True, exist_ok=True)

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


@app.post("/api/chat")
async def chat(request: Request) -> Response:
    """AG-UI プロトコルでチャットエージェントを実行する."""
    return await AGUIAdapter.dispatch_request(request, agent=_agent)
