"""チャット長期記憶(017-chat-memory)のオーケストレーション.

`api/app.py`のADR-0003前処理/後処理段から呼ばれる。想起・抽出・書き直しの
LLM呼び出し自体は`agent/memory_recall.py`/`agent/memory_extract.py`が担い、
ここではそれらとDB(`MemoryRepository`)・現在状態ファイル(`memory/<slug>.md`)を
つなぐ。`services/ingest_paper.py`と同じ「repoとagentを受け取って組み立てる」パターン。
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from polaris.domain.entities import MemoryEvent

if TYPE_CHECKING:
    from polaris.agent.memory_extract import MemoryExtractor, MemoryRewriter
    from polaris.agent.memory_recall import MemoryRecaller
    from polaris.db.memory_repository import MemoryRepository
    from polaris.settings import Settings

logger = logging.getLogger(__name__)

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9-]+")
_SLUG_MAX_LEN = 40


def slugify(text: str) -> str:
    """テーマの説明文からファイル名・索引キーに使う slug を作る.

    非ASCII(日本語の説明が大半)は失われるため、変換後に空になったら
    `theme-<8桁のランダム16進>` にフォールバックする(可読性より一意性を優先)。
    """
    lowered = text.strip().lower().replace(" ", "-")
    slug = _SLUG_INVALID_CHARS.sub("-", lowered).strip("-")[:_SLUG_MAX_LEN].strip("-")
    if not slug:
        slug = f"theme-{uuid.uuid4().hex[:8]}"
    return slug


def _theme_file_path(slug: str, *, settings: Settings) -> Path:
    return Path(settings.memory.dir) / f"{slug}.md"


def read_theme_file(slug: str, *, settings: Settings) -> str | None:
    """現在状態ファイルを読む(無ければNone)."""
    path = _theme_file_path(slug, settings=settings)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def write_theme_file(slug: str, content: str, *, settings: Settings) -> None:
    """現在状態ファイルを書き直す(ディレクトリが無ければ作る)."""
    path = _theme_file_path(slug, settings=settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def recall_memory(
    recent_text: str,
    *,
    recaller: MemoryRecaller,
    repo: MemoryRepository,
    settings: Settings,
) -> str | None:
    """直近のユーザー発言から関連テーマを想起し、該当する現在状態ファイルの中身を返す.

    テーマ索引が空ならLLM呼び出し自体を省略する(想起しようがないため)。
    複数テーマがヒットした場合は、それぞれの現在状態ファイルを連結して返す。
    """
    themes = repo.list_themes()
    if not themes:
        return None

    result = await recaller.recall(recent_text=recent_text, themes=[(t.slug, t.description) for t in themes])
    if not result.matched_theme_slugs:
        return None

    contents = [read_theme_file(slug, settings=settings) for slug in result.matched_theme_slugs]
    non_empty = [c for c in contents if c]
    if not non_empty:
        return None
    return "\n\n---\n\n".join(non_empty)


async def extract_and_store_memory(
    user_text: str,
    assistant_text: str,
    *,
    turn_id: str,
    extractor: MemoryExtractor,
    rewriter: MemoryRewriter,
    repo: MemoryRepository,
    settings: Settings,
) -> None:
    """直近のやり取りが記憶に値するか判定し、値するならログ追記+現在状態ファイルの書き直しを行う.

    「記憶に値するか」の判断自体をLLMに委ねる(承認ゲート方式は採用しない、spec参照)。
    """
    themes = repo.list_themes()
    result = await extractor.extract(
        user_text=user_text, assistant_text=assistant_text, themes=[(t.slug, t.description) for t in themes]
    )
    if not result.worth_remembering or result.theme_slug is None or result.content is None:
        return

    slug = result.theme_slug
    now = datetime.now(UTC)
    repo.append_event(
        MemoryEvent(
            id=uuid.uuid4().hex,
            theme=slug,
            extracted_at=now,
            source_conversation_turn=turn_id,
            raw_text=result.content,
        )
    )
    if result.is_new_theme:
        description = result.theme_description or result.content
        repo.upsert_theme(slug=slug, description=description, updated_at=now)
        logger.info("chat memory: new theme created: slug=%s", slug)

    theme = next((t for t in repo.list_themes() if t.slug == slug), None)
    theme_description = theme.description if theme is not None else slug
    events = repo.list_events(slug)
    rewritten = await rewriter.rewrite(theme_description=theme_description, raw_texts=[e.raw_text for e in events])
    write_theme_file(slug, rewritten, settings=settings)
    logger.info("chat memory: theme file rewritten: slug=%s, events=%d", slug, len(events))
