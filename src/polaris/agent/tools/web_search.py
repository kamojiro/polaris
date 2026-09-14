"""Web検索ツール(web_search、ADR-0013で chat_agent.py から分割).

018-web-search-tool で追加した。当初は自前ホスト済みのSearXNGに直接HTTPで問い合わせる
自前adapter方式だったが、検索結果の質が不十分だったため2026-09-14にTavily(LLM向けの
ホスト型検索API)へ移行した。「MCPは経由せず薄いhttpxクライアントを自前で書く」という
接続方式自体は変えていない。007/013/017など複数specから使われる横断インフラ。

`web_fetch`(pydantic-ai同梱、SSRF対策済みhttps取得+markdown変換)は具体的なURLの
内容を直接読ませたいときに使う別ツールで、実際の登録(`tools=[web_fetch_tool()]`)は
`chat_agent.py`の`Agent()`構築時に行う(この`register`が担う`_register_*_tools`形式の
関数ではないため)。指示文のみ、web_searchと近い話題としてここにまとめている。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from polaris.adapters.tavily.client import TavilySearchError
from polaris.adapters.tavily.client import search as tavily_search
from polaris.progress import set_progress

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from polaris.adapters.tavily.client import TavilyResponse
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
- ユーザーのメッセージに具体的なURL(arXiv/PDF以外の、記事・ブログ等へのリンク)が
  含まれていて、その内容について尋ねられたら web_fetch でそのURLを直接取得して
  答えてください。web_search で近似する必要はありません。
- 最新情報や、保存済みの論文・TODOには無い一般的な事柄を(具体的なURLが無い状態で)
  尋ねられたら web_search ツールを使ってWebを検索してください。ただし
  「保存した論文は?」「TODO一覧」のように保存済みデータについて尋ねられた場合は
  web_search ではなく list_papers/get_paper_full_text/list_todos を使ってください。
  web_search/web_fetch の結果をもとに回答するときは、根拠にした出典のURLを必ず併記してください。"""


def _format_search_results(query: str, response: TavilyResponse) -> str:
    """web_search の戻り値を組み立てる(LLM生成の回答→検索結果一覧の順)."""
    parts = [f"# Web検索結果: 「{query}」"]

    if response.answer:
        parts.append(f"## 検索エンジンによる回答\n{response.answer}")

    if not response.results:
        parts.append("検索結果は見つかりませんでした。")
    else:
        lines = [f"{i}. {r.title}\n   {r.url}\n   {r.content}" for i, r in enumerate(response.results, start=1)]
        parts.append("## 検索結果\n" + "\n".join(lines))

    return "\n\n".join(parts)


def register(agent: Agent[Any, Any], *, settings: Settings) -> None:
    """web_search ツールを登録する(018-web-search-tool、2026-09-14にTavily連携へ移行).

    `agent.tool_plain`はRunContext/depsに触れないため、deps_type/output_typeを問わず
    任意のAgentに登録できる(021-discord-integrationの`agent/discord_title.py`が
    `Agent[None, SidebarTitle]`に対して同じ関数を再利用している)。
    """
    http_client = httpx.AsyncClient()

    @agent.tool_plain
    async def web_search(query: str) -> str:
        """Webを検索する(最新情報や、保存済みデータには無い一般的な事柄を調べる).

        Args:
            query: 検索クエリ。

        Returns:
            検索エンジンの回答・上位の検索結果をまとめた文字列
            (未設定・失敗時はその旨の日本語メッセージ)。

        """
        logger.info("tool call: web_search(query=%s)", query)
        if not settings.tavily.api_key:
            return "Web検索機能は現在無効です(Tavily APIキーが未設定のため)。"
        set_progress("stage", "Webを検索中…")
        try:
            response = await tavily_search(
                query,
                client=http_client,
                api_key=settings.tavily.api_key,
                base_url=settings.tavily.base_url,
                max_results=settings.tavily.max_results,
                timeout_seconds=settings.tavily.timeout_seconds,
                include_answer=settings.tavily.include_answer,
            )
        except TavilySearchError:
            logger.exception("web_search failed: query=%s", query)
            return f"'{query}' の検索に失敗しました。Tavilyに接続できないか、一時的な問題が発生しています。"
        finally:
            set_progress("stage", None)
        return _format_search_results(query, response)
