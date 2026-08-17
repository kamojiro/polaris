"""FastAPI アプリケーション(AG-UI 経由のチャットエンドポイント)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from pydantic_ai.ui.ag_ui import AGUIAdapter

from polaris.adapters.embeddings.qwen import QwenEmbedder
from polaris.agent.chat_agent import build_chat_agent
from polaris.agent.structure_paper import AgentPaperStructurer, build_structure_agent
from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.settings import Settings

if TYPE_CHECKING:
    from fastapi.responses import Response

settings = Settings()
# LOG_LEVEL は Settings で受け取るだけでは実際のログ出力に反映されないため、
# ここで明示的に root logger を設定する(polaris.* のログもここから出る)。
logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
_engine = create_db_engine(settings.DB_PATH, embedding_dim=settings.ingest.embedding_dim)
_repo = PaperRepository(_engine)
# Embedding モデルはプロセス起動時に 1 度だけロードする(初回は数十秒かかる)。
_embedder = QwenEmbedder(settings.ingest.embedding_model_id)
_structurer = AgentPaperStructurer(build_structure_agent(settings))
_agent = build_chat_agent(settings, _repo, embedder=_embedder, structurer=_structurer)

app = FastAPI(title="Polaris")


@app.get("/api/health")
def health() -> dict[str, str]:
    """フロントエンドからの疎通確認用."""
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(request: Request) -> Response:
    """AG-UI プロトコルでチャットエージェントを実行する."""
    return await AGUIAdapter.dispatch_request(request, agent=_agent)
