"""Web検索ツール(web_search、ADR-0013で chat_agent.py から分割).

018-web-search-tool で追加した。自前ホスト済みのSearXNGに直接HTTPで問い合わせる
自前adapter方式(MCPは見送り)。007/013/017など複数specから使われる横断インフラ。

`web_fetch`(pydantic-ai同梱、SSRF対策済みhttps取得+markdown変換)は具体的なURLの
内容を直接読ませたいときに使う別ツールで、実際の登録(`tools=[web_fetch_tool()]`)は
`chat_agent.py`の`Agent()`構築時に行う(この`register`が担う`_register_*_tools`形式の
関数ではないため)。指示文のみ、web_searchと近い話題としてここにまとめている。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from polaris.adapters.searxng.client import SearxngSearchError
from polaris.adapters.searxng.client import search as searxng_search
from polaris.services.progress import set_progress

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from polaris.adapters.searxng.client import SearxngResponse
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


def _format_search_results(query: str, response: SearxngResponse) -> str:
    """web_search の戻り値を組み立てる(エンジンの回答→関連情報→検索結果一覧の順)."""
    parts = [f"# Web検索結果: 「{query}」"]

    parts.extend(
        f"## 検索エンジンによる回答\n{answer.answer}{f'(出典: {answer.url})' if answer.url else ''}"
        for answer in response.answers
    )
    parts.extend(f"## 関連情報: {infobox.infobox}\n{infobox.content}" for infobox in response.infoboxes)

    if not response.results:
        parts.append("検索結果は見つかりませんでした。")
    else:
        lines = [f"{i}. {r.title}\n   {r.url}\n   {r.content}" for i, r in enumerate(response.results, start=1)]
        parts.append("## 検索結果\n" + "\n".join(lines))

    return "\n\n".join(parts)


def register(agent: Agent[Any, Any], *, settings: Settings) -> None:
    """web_search ツールを登録する(018-web-search-tool、自前ホスト済みSearXNG連携).

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
            検索エンジンの回答・関連情報・上位の検索結果をまとめた文字列
            (失敗時はその旨の日本語メッセージ)。

        """
        logger.info("tool call: web_search(query=%s)", query)
        set_progress("stage", "Webを検索中…")
        try:
            response = await searxng_search(
                query,
                client=http_client,
                base_url=settings.searxng.base_url,
                max_results=settings.searxng.max_results,
                timeout_seconds=settings.searxng.timeout_seconds,
            )
        except SearxngSearchError:
            logger.exception("web_search failed: query=%s", query)
            return f"'{query}' の検索に失敗しました。SearXNGに接続できないか、一時的な問題が発生しています。"
        finally:
            set_progress("stage", None)
        return _format_search_results(query, response)
