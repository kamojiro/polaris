"""FastAPI アプリケーション(AG-UI 経由のチャットエンドポイント)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from pydantic_ai.ui.ag_ui import AGUIAdapter

from polaris.agent.chat_agent import build_chat_agent
from polaris.db.repository import PaperRepository
from polaris.db.session import create_db_engine
from polaris.settings import Settings

if TYPE_CHECKING:
    from fastapi.responses import Response

settings = Settings()
_engine = create_db_engine(settings.DB_PATH)
_repo = PaperRepository(_engine)
_agent = build_chat_agent(settings, _repo)

app = FastAPI(title="Polaris")


@app.get("/api/health")
def health() -> dict[str, str]:
    """フロントエンドからの疎通確認用."""
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(request: Request) -> Response:
    """AG-UI プロトコルでチャットエージェントを実行する."""
    return await AGUIAdapter.dispatch_request(request, agent=_agent)
