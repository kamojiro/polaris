"""論文・TODOチャットエージェント.

論文ツール(save_paper/list_papers)は 002-papers-ingest-full 以降、PDF取得・
本文抽出・チャンク分割・Embedding生成までのフルパイプラインを実行する。
014-paper-url-pdf-ingest で arXiv 以外(PDF直リンクURL、`upload://<id>` 経由の
ローカルPDF)にも対応した。

TODOツール(add_todo/list_todos/update_todo/complete_todo/delete_todo)は
007-todo-domain で追加した。専用のエージェント/レジストリ(011-agent-registry)は
まだ無いため、既存の単一チャットエージェントにtoolを追加するだけに留めている
(YAGNI)。バケット分類(day/month/life)も専用のStructureステップを設けず、
LLMが add_todo の scale 引数をユーザーの自然文から直接選ぶ。

論文QAツール(get_paper_full_text)は 015-paper-qa-chat で追加した。ベクトル検索
(Chunk/Embedding)は経由せず、対象論文の抽出済み全文をそのまま会話に取り込む方式。
一度取り込んだ全文は会話履歴に残るため、同じ論文について複数ターン質問しても
ツールを再度呼ぶ必要はない。

「論文モード」(015拡張)は、get_paper_full_text が成功すると AG-UI の state
(ChatUIState.active_paper)に「今読んでいる論文」を記録し、動的instructions
(_register_paper_qa_tools 内で登録)がそれを見て「曖昧な質問もこの論文への
質問として解釈してよい」という指示を追加する。会話履歴だけに頼るのではなく、
明示的な state を LLM への指示とフロントのバッジ表示の両方に使う。

チャットの長期記憶(017-chat-memory)は、メインのチャットエージェントに
「記憶を検索するtool」を持たせない(応答生成モデルに能動的なtool呼び出しを
期待するのは信頼性が低いため)。代わりに `api/app.py` の前処理段が想起した
内容を `ChatDeps.recalled_memory` に詰めて渡し、`_memory_instructions` が
それを動的instructionsとして注入する。抽出(後処理)は完全にこのエージェントの
外側(`services/memory.py`)で行われ、チャットの応答自体には一切関与しない。

IR文書ツール(save_ir_document/get_ir_full_text/list_ir_documents)は
013-ir-analysis-domain で追加した。EDINETから取り込んだ有価証券報告書等を
015と同じ「全文をそのままコンテキストに渡す」方式で扱うが、論文モードのような
state駆動の動的instructions・モード終了toolは持たない(spec「未決定事項」で
v1は見送りと明記されているため、YAGNI)。要約・QAが投資助言(売買判断等)に
踏み込まないよう、_INSTRUCTIONS に明記して回答を事実の整理に留めさせる。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import httpx
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.common_tools.web_fetch import web_fetch_tool

# TodoScale は tool 関数の引数の型注釈として使われ、pydantic-ai が実行時に
# シグネチャからスキーマを組み立てる(`from __future__ import annotations` で
# 文字列注釈になるため、TYPE_CHECKING ブロックに入れると実行時に解決できず
# NameError になる)。そのため ruff の TC001(型チェック専用importへの移動提案)は
# 意図的に無視する。
from polaris.adapters.arxiv.parser import extract_arxiv_id
from polaris.adapters.searxng.client import SearxngSearchError
from polaris.adapters.searxng.client import search as searxng_search
from polaris.domain.entities import TodoScale  # noqa: TC001
from polaris.services.ingest_ir import ingest_ir_document
from polaris.services.ingest_paper import ingest_paper_from_url
from polaris.services.ir_full_text import load_ir_full_text
from polaris.services.paper_full_text import load_full_text
from polaris.services.paper_source import InvalidPaperUrlError
from polaris.services.progress import set_progress
from polaris.services.todo import build_todo_records

from .model import build_model

if TYPE_CHECKING:
    from polaris.adapters.embeddings import EmbeddingModel
    from polaris.adapters.searxng.client import SearxngResponse
    from polaris.agent.extract_ir_metadata import IrMetadataExtractor
    from polaris.agent.extract_metadata import PaperMetadataExtractor
    from polaris.agent.structure_paper import PaperStructurer
    from polaris.db.ir_repository import IrRepository
    from polaris.db.news_repository import NewsRepository
    from polaris.db.repository import PaperRepository
    from polaris.db.todo_repository import TodoRepository
    from polaris.domain.entities import IrRecord, Item, PaperRecord, TodoRecord
    from polaris.services.ir_full_text import IrFullText
    from polaris.services.paper_full_text import PaperFullText
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

# 一覧表示の上限。件数が増えるほど DB 負荷・LLM に渡すトークン量が際限なく
# 増えないよう、フロントではなくここ(list_papers/list_news の SQL LIMIT)で絞る。
_RECENT_PAPERS_LIMIT = 20
# source_labelごとの上限(全体への単一LIMITではない。NewsRepository.list_news参照)。
_RECENT_NEWS_LIMIT_PER_LABEL = 15
# 013-ir-analysis-domain: list_ir_documents の一覧表示上限(_RECENT_PAPERS_LIMITと同じ理由)。
_RECENT_IR_LIMIT = 20

_INSTRUCTIONS = """\
あなたは個人用の論文管理・TODO管理アシスタントです。次のルールに従ってください。

- ユーザーのメッセージに arXiv の URL/ID、PDFへの直リンクURL、または
  `upload://` から始まる文字列が含まれていたら、必ず save_paper ツールを
  呼び出して保存してください。確認は不要です。
  save_paper の結果に含まれる要約は省略せずそのままユーザーに伝えてください。
- 「保存した論文」「今までの論文一覧」のように尋ねられたら list_papers ツールを呼び出してください。
  list_papers の結果は画面側で一覧表示されるため、あなたは結果を文章で列挙せず、
  「保存済みの論文一覧を表示しました」程度の一言だけ返してください。
- TODO/やることを追加したい場合は add_todo を呼んでください。確認は不要です。
  scale はユーザーの表現から day(すぐ/明日まで等)/month(今月中等)/
  life(いつか/一生のうち等)を判断してください。迷ったら month にしてください。
- 「TODO一覧」「やることリスト」のように尋ねられたら list_todos を呼んでください。
  list_todos の結果は画面側で一覧表示されるため、あなたは結果を文章で列挙せず、
  「TODO一覧を表示しました」程度の一言だけ返してください。
- TODOの完了・編集・削除の指示があれば、対象のidが会話履歴から分からなければ
  先に list_todos で確認してから update_todo/complete_todo/delete_todo を
  呼んでください。
- 特定の論文の内容について質問されたら(「〇〇という論文の手法は?」等)、まず
  get_paper_full_text で全文を会話に取り込んでから答えてください。同じ論文に
  ついて続けて質問された場合、全文は既に会話履歴に残っているのでツールを
  再度呼ぶ必要はありません。複数の論文を比較する場合は、それぞれについて
  ツールを呼んでください。
- ユーザーのメッセージに具体的なURL(arXiv/PDF以外の、記事・ブログ等へのリンク)が
  含まれていて、その内容について尋ねられたら web_fetch でそのURLを直接取得して
  答えてください。web_search で近似する必要はありません。
- 最新情報や、保存済みの論文・TODOには無い一般的な事柄を(具体的なURLが無い状態で)
  尋ねられたら web_search ツールを使ってWebを検索してください。ただし
  「保存した論文は?」「TODO一覧」のように保存済みデータについて尋ねられた場合は
  web_search ではなく list_papers/get_paper_full_text/list_todos を使ってください。
  web_search/web_fetch の結果をもとに回答するときは、根拠にした出典のURLを必ず併記してください。
- 「ニュース一覧」「最近の記事」「今日のニュース」のように尋ねられたら list_news ツールを
  呼び出してください。list_news の結果は画面側で情報源のカテゴリごとに一覧表示されるため、
  あなたは結果を文章で列挙せず、「取り込み済みのニュース一覧を表示しました」程度の
  一言だけ返してください。ニュースの取り込み自体はチャットからはできません
  (RSSの定期巡回でのみ更新されます)。
- ユーザーのメッセージにEDINETの書類管理番号(`S100XXXX`のような形式のdocID)が
  含まれていたら、必ず save_ir_document ツールを呼び出して保存してください。確認は不要です。
  save_ir_document の結果に含まれる要約は省略せずそのままユーザーに伝えてください。
- 「保存したIR文書」「有価証券報告書の一覧」のように尋ねられたら list_ir_documents ツールを
  呼び出してください。list_ir_documents の結果は画面側で一覧表示されるため、あなたは結果を
  文章で列挙せず、「保存済みのIR文書一覧を表示しました」程度の一言だけ返してください。
- 特定のIR文書の内容について質問されたら(「〇〇社の有価証券報告書の売上は?」等)、まず
  get_ir_full_text で全文を会話に取り込んでから答えてください。同じ文書について続けて
  質問された場合、全文は既に会話履歴に残っているのでツールを再度呼ぶ必要はありません。
- IR文書に関する要約・QAは、書かれている事実の整理に徹してください。「株を買うべきか」
  「今が売り時か」等の投資助言(売買判断・価格予想)を求められても、判断そのものは
  行わず、事実の整理に留める旨を答えてください。
- 回答はツールの結果だけを根拠にし、推測で情報を補わないでください。
- 日本語で簡潔に答えてください。
"""


class PaperSummary(BaseModel):
    """一覧表示用の論文サマリ."""

    title: str
    authors: list[str]
    year: int | None
    arxiv_id: str | None


class PaperListResult(BaseModel):
    """list_papers の戻り値.

    `papers` は直近 `_RECENT_PAPERS_LIMIT` 件のみ、`total_count` は保存済みの
    総件数(省略された残り件数をフロントが計算できるようにするため)。
    """

    papers: list[PaperSummary]
    total_count: int


class ActivePaper(BaseModel):
    """論文モード(015拡張)で「今読んでいる論文」を表す."""

    item_id: str
    title: str


class ChatUIState(BaseModel):
    """AG-UI の RunAgentInput.state ⇄ StateSnapshotEvent で同期する会話状態(015拡張、019で汎用化).

    クライアントは毎ターン `state` をそのまま送り返してくるため、`Agent` の
    `deps_type=StateDeps[ChatUIState]` で受け取り、`get_paper_full_text` が
    成功した時点で `active_paper` をセットする。フロント側はこれを見て
    「📄 読書中: (論文タイトル)」のバッジを表示する。

    `diary_mode`(019-diary-domain)は`active_paper`と独立したフィールドで、両者は
    排他ではなく共存できる(論文について話しながら、その内容を今日の日記にも残せる)。
    元は`PaperModeState`という名前だったが、論文モード専用ではなくなったため改名した。
    """

    active_paper: ActivePaper | None = None
    diary_mode: bool = False


@dataclass
class ChatDeps:
    """メインのチャットエージェントの deps(`StateHandler` プロトコルを満たす自前dataclass).

    `state` は AG-UI の RunAgentInput.state ⇄ StateSnapshotEvent でクライアントと
    同期される(`StateHandler` は「dataclassであること」と「state属性を持つこと」しか
    要求しないため、`pydantic_ai.ui.StateDeps` を使わずこの形で足りる)。`recalled_memory`
    は017-chat-memoryの前処理(`api/app.py`)がサーバー側だけで設定する値で、
    `state` ではないため AG-UI 側には一切公開されない(StateSnapshotEventにも乗らない)。
    """

    state: ChatUIState
    recalled_memory: str | None = None


class TodoSummary(BaseModel):
    """一覧表示用のTODOサマリ."""

    id: str
    title: str
    description: str
    scale: TodoScale
    done: bool
    updated_at: datetime
    completed_at: datetime | None


class TodoListResult(BaseModel):
    """list_todos の戻り値."""

    todos: list[TodoSummary]


def _todo_summary(item: Item, record: TodoRecord) -> TodoSummary:
    return TodoSummary(
        id=item.id,
        title=item.title,
        description=item.summary,
        scale=record.scale,
        done=record.done,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


def _register_paper_tools(
    agent: Agent[ChatDeps, str],
    repo: PaperRepository,
    *,
    settings: Settings,
    embedder: EmbeddingModel,
    structurer: PaperStructurer,
    extractor: PaperMetadataExtractor,
) -> None:
    """save_paper/list_papers ツールを登録する(002-papers-ingest-full/014-paper-url-pdf-ingest)."""
    http_client = httpx.AsyncClient()

    @agent.tool_plain
    async def save_paper(url: str) -> str:
        """arXiv/PDF直リンクURL/アップロード済みPDFからメタデータ・本文を取得し、チャンク分割・Embedding生成まで行って保存する.

        Args:
            url: arXiv の論文 URL/ID(例: https://arxiv.org/abs/2401.12345)、
                PDFへの直リンクURL、または `upload://<id>`(POST /api/papers/upload
                が発行した ID)。

        Returns:
            保存結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: save_paper(url=%s)", url)
        try:
            result = await ingest_paper_from_url(
                url,
                repo=repo,
                http_client=http_client,
                embedder=embedder,
                structurer=structurer,
                extractor=extractor,
                settings=settings,
            )
        except InvalidPaperUrlError:
            return (
                f"'{url}' から論文の取り込み元を特定できませんでした。"
                "arXivのURL/ID、またはPDFへの直リンクURLを貼ってください。"
            )

        status = "新規に保存しました" if result.created else "既に保存済みでした"
        source_label = f"arXiv:{result.record.arxiv_id}" if result.record.arxiv_id else result.record.source_url
        return (
            f"{status}: 『{result.item.title}』({source_label}, チャンク数: {len(result.chunks)})\n\n"
            f"要約: {result.item.summary}"
        )

    @agent.tool_plain
    def list_papers() -> PaperListResult:
        """保存済みの論文一覧を直近分だけ返す(総件数も併せて返す)."""
        logger.info("tool call: list_papers()")
        papers = [
            PaperSummary(title=item.title, authors=record.authors, year=record.year, arxiv_id=record.arxiv_id)
            for item, record in repo.list_papers(limit=_RECENT_PAPERS_LIMIT)
        ]
        return PaperListResult(papers=papers, total_count=repo.count_papers())


def _format_full_text(item: Item, record: PaperRecord, full_text: PaperFullText) -> str:
    """get_paper_full_text の戻り値を組み立てる(ヘッダ+本文)."""
    arxiv_label = f", arXiv:{record.arxiv_id}" if record.arxiv_id else ""
    header = f"# 『{item.title}』({'、'.join(record.authors) or '著者不明'}{arxiv_label})"
    truncated_note = "\n(全文が長いため先頭部分のみ表示しています)" if full_text.truncated else ""
    return f"{header}{truncated_note}\n---\n{full_text.text}"


def _register_paper_qa_tools(
    agent: Agent[ChatDeps, str], repo: PaperRepository, *, settings: Settings
) -> None:
    """get_paper_full_text/exit_paper_mode ツールと論文モードの動的instructionsを登録する(015-paper-qa-chat)."""

    @agent.tool
    async def get_paper_full_text(ctx: RunContext[ChatDeps], paper: str) -> str:
        """保存済み論文の本文全文を取得し、会話に取り込む(論文モードに入る).

        Args:
            ctx: pydantic-ai が注入する実行コンテキスト(論文モードのstateを保持)。
            paper: 対象論文を指す文字列(arXivのURL/ID、または保存時のタイトルの一部)。

        Returns:
            論文の本文全文(見つからない/複数該当する場合はその旨の日本語メッセージ)。

        """
        logger.info("tool call: get_paper_full_text(paper=%s)", paper)
        query = extract_arxiv_id(paper) or paper
        matches = repo.search_papers(query)
        if not matches:
            return f"'{paper}' に該当する論文が見つかりませんでした。list_papers で保存済みの論文を確認してください。"
        if len(matches) > 1:
            titles = "、".join(f"『{item.title}』" for item, _record in matches)
            return f"複数の論文が該当しました: {titles}。どの論文か、タイトルをもう少し詳しく指定してください。"

        item, record = matches[0]
        set_progress("stage", "論文の全文を読み込み中…")
        try:
            full_text = await load_full_text(item, record, repo=repo, max_chars=settings.chat.max_full_text_chars)
        finally:
            set_progress("stage", None)
        ctx.deps.state.active_paper = ActivePaper(item_id=item.id, title=item.title)
        return _format_full_text(item, record, full_text)

    @agent.tool
    def exit_paper_mode(ctx: RunContext[ChatDeps]) -> str:
        """論文モードを終了する(ユーザーが別の話題に移った、または明示的に終了を求めた場合に呼ぶ)."""
        logger.info("tool call: exit_paper_mode()")
        ctx.deps.state.active_paper = None
        return "論文モードを終了しました。"

    @agent.instructions
    def _paper_mode_instructions(ctx: RunContext[ChatDeps]) -> str | None:
        active = ctx.deps.state.active_paper
        if active is None:
            return None
        return (
            f"現在は論文『{active.title}』について読んでいる「論文モード」です。"
            "ユーザーの質問が曖昧でも、明確に他の話題に触れていなければこの論文についての"
            "質問だと解釈して回答してください(全文は会話履歴に既にあるので "
            "get_paper_full_text を再度呼ぶ必要はありません)。ユーザーが明確に別の話題へ"
            "移ったり、論文の話を終えたいと言ったりしたら exit_paper_mode を呼んでください。"
        )


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


def _register_web_search_tools(agent: Agent[ChatDeps, str], *, settings: Settings) -> None:
    """web_search ツールを登録する(018-web-search-tool、自前ホスト済みSearXNG連携)."""
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


def _register_todo_read_tools(agent: Agent[ChatDeps, str], todo_repo: TodoRepository) -> None:
    """add_todo/list_todos ツールを登録する(007-todo-domain)."""

    @agent.tool_plain
    def add_todo(title: str, scale: TodoScale, description: str = "") -> str:
        """新しいTODOを追加する.

        Args:
            title: TODOのタイトル。
            scale: 時間スケール(day=1日以内、month=1ヶ月以内、life=一生のうち)。
            description: 詳細メモ(任意)。

        Returns:
            保存結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: add_todo(title=%s, scale=%s)", title, scale)
        item, record = build_todo_records(title=title, scale=scale, description=description)
        todo_repo.save_todo(item, record)
        return f"TODOを追加しました({scale.value}): 『{title}』"

    @agent.tool_plain
    def list_todos(scale: TodoScale | None = None, include_done: bool = False) -> TodoListResult:
        """TODO一覧を返す(既定では未完了のみ、熟成度=最終更新日からの経過が長い順)."""
        logger.info("tool call: list_todos(scale=%s, include_done=%s)", scale, include_done)
        todos = [
            _todo_summary(item, record)
            for item, record in todo_repo.list_todos(scale=scale, include_done=include_done)
        ]
        return TodoListResult(todos=todos)


def _register_todo_write_tools(agent: Agent[ChatDeps, str], todo_repo: TodoRepository) -> None:
    """update_todo/complete_todo/delete_todo ツールを登録する(007-todo-domain)."""

    @agent.tool_plain
    def update_todo(
        todo_id: str,
        title: str | None = None,
        description: str | None = None,
        scale: TodoScale | None = None,
    ) -> str:
        """既存TODOのタイトル・詳細メモ・時間スケールを更新する(指定したフィールドのみ変更).

        Args:
            todo_id: 対象TODOのid(list_todosの結果から取得できる)。
            title: 新しいタイトル(省略時は変更しない)。
            description: 新しい詳細メモ(省略時は変更しない)。
            scale: 新しい時間スケール(省略時は変更しない)。

        Returns:
            結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: update_todo(todo_id=%s)", todo_id)
        found = todo_repo.get_by_item_id(todo_id)
        if found is None:
            return f"TODO(id={todo_id})が見つかりませんでした。"
        item, record = found
        if title is not None:
            item.title = title
        if description is not None:
            item.summary = description
        if scale is not None:
            record.scale = scale
        record.updated_at = datetime.now(UTC)
        todo_repo.update_item(item)
        todo_repo.update_todo_record(record)
        return f"TODOを更新しました: 『{item.title}』"

    @agent.tool_plain
    def complete_todo(todo_id: str) -> str:
        """TODOを完了にする.

        Args:
            todo_id: 対象TODOのid(list_todosの結果から取得できる)。

        Returns:
            結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: complete_todo(todo_id=%s)", todo_id)
        found = todo_repo.get_by_item_id(todo_id)
        if found is None:
            return f"TODO(id={todo_id})が見つかりませんでした。"
        item, record = found
        now = datetime.now(UTC)
        record.done = True
        record.completed_at = now
        record.updated_at = now
        todo_repo.update_todo_record(record)
        return f"完了にしました: 『{item.title}』"

    @agent.tool_plain
    def delete_todo(todo_id: str) -> str:
        """TODOを削除する(物理削除、元に戻せない).

        Args:
            todo_id: 対象TODOのid(list_todosの結果から取得できる)。

        Returns:
            結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: delete_todo(todo_id=%s)", todo_id)
        found = todo_repo.get_by_item_id(todo_id)
        if found is None:
            return f"TODO(id={todo_id})が見つかりませんでした。"
        item, _record = found
        todo_repo.delete_todo(todo_id)
        return f"削除しました: 『{item.title}』"


class NewsSummary(BaseModel):
    """一覧表示用のニュース記事サマリ."""

    title: str
    source_name: str
    source_label: str
    summary: str
    published_at: datetime
    source_url: str


class NewsListResult(BaseModel):
    """list_news の戻り値."""

    news: list[NewsSummary]


def _register_news_tools(agent: Agent[ChatDeps, str], news_repo: NewsRepository) -> None:
    """list_news ツールを登録する(008-daily-digest-domain Phase A)."""

    @agent.tool_plain
    def list_news() -> NewsListResult:
        """取り込み済みのニュース記事一覧を返す(情報源のラベルごとに画面側でグルーピング表示される)."""
        logger.info("tool call: list_news()")
        news = [
            NewsSummary(
                title=item.title,
                source_name=record.source_name,
                source_label=record.source_label,
                summary=item.summary,
                published_at=record.published_at,
                source_url=record.source_url,
            )
            for item, record in news_repo.list_news(limit_per_label=_RECENT_NEWS_LIMIT_PER_LABEL)
        ]
        return NewsListResult(news=news)


class IrSummary(BaseModel):
    """一覧表示用のIR文書サマリ."""

    filer_name: str
    doc_type_code: str | None
    period_start: date | None
    period_end: date | None
    submit_datetime: datetime
    doc_id: str


class IrListResult(BaseModel):
    """list_ir_documents の戻り値.

    `documents` は直近 `_RECENT_IR_LIMIT` 件のみ、`total_count` は保存済みの
    総件数(list_papers/PaperListResultと同じ形)。
    """

    documents: list[IrSummary]
    total_count: int


def _register_ir_tools(
    agent: Agent[ChatDeps, str],
    ir_repo: IrRepository,
    *,
    settings: Settings,
    ir_extractor: IrMetadataExtractor,
) -> None:
    """save_ir_document/get_ir_full_text/list_ir_documents ツールを登録する(013-ir-analysis-domain).

    015の論文モードのようなstate駆動の動的instructions・モード終了toolは持たない
    (spec「未決定事項」でv1は見送りと明記されているため)。
    """
    http_client = httpx.AsyncClient()

    @agent.tool_plain
    async def save_ir_document(doc_id: str) -> str:
        """EDINETのdocID(書類管理番号)からIR文書(有価証券報告書等)のPDFを取得し保存する.

        Args:
            doc_id: EDINETの書類管理番号(例: S100XXXX)。

        Returns:
            保存結果を表す短い日本語メッセージ。

        """
        logger.info("tool call: save_ir_document(doc_id=%s)", doc_id)
        result = await ingest_ir_document(
            doc_id,
            repo=ir_repo,
            http_client=http_client,
            extractor=ir_extractor,
            settings=settings,
        )
        status = "新規に保存しました" if result.created else "既に保存済みでした"
        return f"{status}: 『{result.item.title}』(doc_id: {result.record.doc_id})\n\n要約: {result.item.summary}"

    @agent.tool_plain
    def list_ir_documents() -> IrListResult:
        """保存済みのIR文書一覧を直近分だけ返す(総件数も併せて返す)."""
        logger.info("tool call: list_ir_documents()")
        documents = [
            IrSummary(
                filer_name=record.filer_name,
                doc_type_code=record.doc_type_code,
                period_start=record.period_start,
                period_end=record.period_end,
                submit_datetime=record.submit_datetime,
                doc_id=record.doc_id,
            )
            for _item, record in ir_repo.list_ir_documents(limit=_RECENT_IR_LIMIT)
        ]
        return IrListResult(documents=documents, total_count=ir_repo.count_ir_documents())

    @agent.tool_plain
    async def get_ir_full_text(query: str) -> str:
        """保存済みIR文書の本文全文を取得し、会話に取り込む.

        Args:
            query: 対象IR文書を指す文字列(企業名の一部、またはEDINETのdocID)。

        Returns:
            IR文書の本文全文(見つからない/複数該当する場合はその旨の日本語メッセージ)。

        """
        logger.info("tool call: get_ir_full_text(query=%s)", query)
        matches = ir_repo.search_ir_documents(query)
        if not matches:
            return (
                f"'{query}' に該当するIR文書が見つかりませんでした。"
                "list_ir_documents で保存済みの文書を確認してください。"
            )
        if len(matches) > 1:
            names = "、".join(f"『{item.title}』" for item, _record in matches)
            return f"複数のIR文書が該当しました: {names}。どの文書か、企業名をもう少し詳しく指定してください。"

        item, record = matches[0]
        set_progress("stage", "IR文書の全文を読み込み中…")
        try:
            full_text = await load_ir_full_text(item, record, max_chars=settings.chat.max_full_text_chars)
        finally:
            set_progress("stage", None)
        return _format_ir_full_text(item, record, full_text)


def _format_ir_full_text(item: Item, record: IrRecord, full_text: IrFullText) -> str:
    """get_ir_full_text の戻り値を組み立てる(ヘッダ+本文)."""
    header = f"# 『{item.title}』(提出者: {record.filer_name}, doc_id: {record.doc_id})"
    truncated_note = "\n(全文が長いため先頭部分のみ表示しています)" if full_text.truncated else ""
    return f"{header}{truncated_note}\n---\n{full_text.text}"


def _register_memory_instructions(agent: Agent[ChatDeps, str]) -> None:
    """想起した長期記憶(017-chat-memory)を動的instructionsとして注入する.

    `api/app.py` の前処理段が `ctx.deps.recalled_memory` を設定済みの前提で、
    それが None でなければ会話の前提知識としてinstructionsに足す。tool は登録しない
    (記憶の想起・抽出はどちらもメインのチャットエージェントの外側で完結する)。
    """

    @agent.instructions
    def _memory_instructions(ctx: RunContext[ChatDeps]) -> str | None:
        if ctx.deps.recalled_memory is None:
            return None
        return (
            "以下は過去の会話から蓄積した、関連するテーマについての記憶です。"
            "踏まえた上で回答してください。\n\n" + ctx.deps.recalled_memory
        )


def build_chat_agent(
    settings: Settings,
    repo: PaperRepository,
    *,
    embedder: EmbeddingModel,
    structurer: PaperStructurer,
    extractor: PaperMetadataExtractor,
    todo_repo: TodoRepository,
    news_repo: NewsRepository,
    ir_repo: IrRepository,
    ir_extractor: IrMetadataExtractor,
) -> Agent[ChatDeps, str]:
    """設定とリポジトリ・Embedding/Structure/メタデータ抽出・TODO/ニュース/IRリポジトリ依存からチャットエージェントを組み立てる."""
    model = build_model(settings)
    # web_fetch はpydantic-ai同梱のツール(SSRF対策済みhttps取得+markdown変換)。
    # 具体的なURLの内容を尋ねられたとき、web_searchで近似せず直接読ませるために使う
    # (008拡張のニュースサイドバー「クリックで詳しく教えて」導線での実運用から着想)。
    agent = Agent(model, deps_type=ChatDeps, instructions=_INSTRUCTIONS, tools=[web_fetch_tool()])
    _register_memory_instructions(agent)
    _register_paper_tools(
        agent,
        repo,
        settings=settings,
        embedder=embedder,
        structurer=structurer,
        extractor=extractor,
    )
    _register_todo_read_tools(agent, todo_repo)
    _register_todo_write_tools(agent, todo_repo)
    _register_paper_qa_tools(agent, repo, settings=settings)
    _register_web_search_tools(agent, settings=settings)
    _register_news_tools(agent, news_repo)
    _register_ir_tools(agent, ir_repo, settings=settings, ir_extractor=ir_extractor)
    return agent
