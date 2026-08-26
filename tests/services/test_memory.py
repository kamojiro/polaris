"""services/memory.py のロジックテスト.

想起・抽出・書き直しのLLM呼び出しはフェイク(`tests/services/test_ingest_paper.py`の
フェイク構造化エージェントと同じやり方)に差し替え、実LLM・実DBファイルへの依存なしで
orchestration(recall_memory/extract_and_store_memory)のロジックだけを検証する。
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from polaris.agent.memory_extract import ExtractionResult
from polaris.agent.memory_recall import RecallResult
from polaris.db.memory_repository import MemoryRepository
from polaris.db.session import create_db_engine
from polaris.services.memory import extract_and_store_memory, recall_memory, slugify
from polaris.settings import MemorySettings, Settings


class _FakeRecaller:
    """固定の RecallResult を返すだけのフェイク想起エージェント."""

    def __init__(self, matched_theme_slugs: list[str]) -> None:
        self._matched = matched_theme_slugs
        self.calls: list[tuple[str, list[tuple[str, str]]]] = []

    async def recall(self, *, recent_text: str, themes: Sequence[tuple[str, str]]) -> RecallResult:
        self.calls.append((recent_text, list(themes)))
        return RecallResult(matched_theme_slugs=self._matched)


class _FakeExtractor:
    """固定の ExtractionResult を返すだけのフェイク抽出エージェント."""

    def __init__(self, result: ExtractionResult) -> None:
        self._result = result

    async def extract(
        self,
        *,
        user_text: str,  # noqa: ARG002
        assistant_text: str,  # noqa: ARG002
        themes: Sequence[tuple[str, str]],  # noqa: ARG002
    ) -> ExtractionResult:
        return self._result


class _FakeRewriter:
    """固定のMarkdown本文を返すだけのフェイク書き直しエージェント."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    async def rewrite(self, *, theme_description: str, raw_texts: Sequence[str]) -> str:
        self.calls.append((theme_description, list(raw_texts)))
        return f"# {theme_description}\n\n" + "\n".join(raw_texts)


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(memory=MemorySettings(dir=str(tmp_path / "memory")))


def test_slugify_converts_ascii_lowercase_and_hyphenates() -> None:
    """ASCII文字は小文字化+ハイフン区切りに変換される."""
    assert slugify("Local LLM Setup") == "local-llm-setup"


def test_slugify_falls_back_to_random_slug_for_non_ascii() -> None:
    """ASCII英数字を一切含まないdescriptionは変換後に空になるため theme-<hex> にフォールバックする."""
    slug = slugify("ローカルの話題")
    assert slug.startswith("theme-")
    assert len(slug) == len("theme-") + 8


def test_slugify_keeps_ascii_substring_from_mixed_text() -> None:
    """日本語にASCII部分文字列(LLM等)が混じっていれば、そこだけ残ったslugになる(空にはならない)."""
    slug = slugify("ローカルLLMの話題")
    assert slug == "llm"


async def test_recall_memory_skips_llm_call_when_no_themes(tmp_path: Path) -> None:
    """テーマ索引が空ならLLM呼び出し自体を省略してNoneを返す."""
    repo = MemoryRepository(create_db_engine(str(tmp_path / "test.db")))
    recaller = _FakeRecaller(matched_theme_slugs=["local-llm"])
    settings = _make_settings(tmp_path)

    result = await recall_memory("こんにちは", recaller=recaller, repo=repo, settings=settings)

    assert result is None
    assert recaller.calls == []


async def test_recall_memory_returns_none_when_no_theme_matched(tmp_path: Path) -> None:
    """テーマは存在するが該当なしと判定されればNoneを返す."""
    repo = MemoryRepository(create_db_engine(str(tmp_path / "test.db")))
    settings = _make_settings(tmp_path)
    repo.upsert_theme(slug="local-llm", description="ローカルLLMの話題", updated_at=datetime.now(UTC))
    recaller = _FakeRecaller(matched_theme_slugs=[])

    result = await recall_memory("こんにちは", recaller=recaller, repo=repo, settings=settings)

    assert result is None


async def test_recall_memory_returns_theme_file_content_when_matched(tmp_path: Path) -> None:
    """該当テーマがあれば現在状態ファイルの中身を返す."""
    repo = MemoryRepository(create_db_engine(str(tmp_path / "test.db")))
    settings = _make_settings(tmp_path)
    repo.upsert_theme(slug="local-llm", description="ローカルLLMの話題", updated_at=datetime.now(UTC))
    memory_dir = Path(settings.memory.dir)
    memory_dir.mkdir(parents=True)  # noqa: ASYNC240 - テストなのでブロッキング呼び出しで問題ない
    (memory_dir / "local-llm.md").write_text("RTX 2060 SUPERで動かしている", encoding="utf-8")
    recaller = _FakeRecaller(matched_theme_slugs=["local-llm"])

    result = await recall_memory("GPUの調子どう?", recaller=recaller, repo=repo, settings=settings)

    assert result == "RTX 2060 SUPERで動かしている"


async def test_extract_and_store_memory_does_nothing_when_not_worth_remembering(tmp_path: Path) -> None:
    """worth_remembering=Falseなら MemoryEvent もファイルも作られない."""
    repo = MemoryRepository(create_db_engine(str(tmp_path / "test.db")))
    settings = _make_settings(tmp_path)
    extractor = _FakeExtractor(ExtractionResult(worth_remembering=False))
    rewriter = _FakeRewriter()

    await extract_and_store_memory(
        "こんにちは",
        "こんにちは!",
        turn_id="turn-1",
        extractor=extractor,
        rewriter=rewriter,
        repo=repo,
        settings=settings,
    )

    assert repo.list_themes() == []
    assert rewriter.calls == []


async def test_extract_and_store_memory_creates_new_theme_and_writes_file(tmp_path: Path) -> None:
    """新規テーマなら MemoryTheme が作られ、MemoryEventが追記され、ファイルが書き直される."""
    repo = MemoryRepository(create_db_engine(str(tmp_path / "test.db")))
    settings = _make_settings(tmp_path)
    extractor = _FakeExtractor(
        ExtractionResult(
            worth_remembering=True,
            theme_slug="local-llm",
            is_new_theme=True,
            theme_description="ローカルLLMの話題",
            content="RTX 2060 SUPERで動かしている",
        )
    )
    rewriter = _FakeRewriter()

    await extract_and_store_memory(
        "ローカルLLMをRTX 2060 SUPERで動かしてる",
        "なるほど",
        turn_id="turn-1",
        extractor=extractor,
        rewriter=rewriter,
        repo=repo,
        settings=settings,
    )

    themes = repo.list_themes()
    assert len(themes) == 1
    assert themes[0].slug == "local-llm"
    events = repo.list_events("local-llm")
    assert len(events) == 1
    assert events[0].raw_text == "RTX 2060 SUPERで動かしている"
    assert events[0].source_conversation_turn == "turn-1"
    theme_file = Path(settings.memory.dir) / "local-llm.md"
    assert theme_file.exists()
    assert "RTX 2060 SUPERで動かしている" in theme_file.read_text(encoding="utf-8")


async def test_extract_and_store_memory_appends_to_existing_theme_without_duplicating(tmp_path: Path) -> None:
    """既存テーマなら MemoryTheme を重複作成せず、ログにイベントを追記するだけ."""
    repo = MemoryRepository(create_db_engine(str(tmp_path / "test.db")))
    settings = _make_settings(tmp_path)
    repo.upsert_theme(slug="local-llm", description="ローカルLLMの話題", updated_at=datetime.now(UTC))
    extractor = _FakeExtractor(
        ExtractionResult(
            worth_remembering=True,
            theme_slug="local-llm",
            is_new_theme=False,
            content="VRAM 8GBで運用中",
        )
    )
    rewriter = _FakeRewriter()

    await extract_and_store_memory(
        "GPUのVRAMは8GB", "了解", turn_id="turn-2", extractor=extractor, rewriter=rewriter, repo=repo, settings=settings
    )

    assert len(repo.list_themes()) == 1  # 重複作成されない
    events = repo.list_events("local-llm")
    assert len(events) == 1
    assert events[0].raw_text == "VRAM 8GBで運用中"
    assert rewriter.calls[0][0] == "ローカルLLMの話題"  # 既存の説明がrewriterに渡される
