"""services/discord_title_cache.py のテスト."""

from pathlib import Path

from polaris.services.discord_title_cache import read_cache, write_cache


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    """書き込んだ内容がそのまま読み戻せる."""
    path = str(tmp_path / "cache.json")

    write_cache(path, {"111": "見出しA", "222": "見出しB"})

    assert read_cache(path) == {"111": "見出しA", "222": "見出しB"}


def test_read_returns_empty_dict_when_file_missing(tmp_path: Path) -> None:
    """ファイルが存在しなければ空dictを返す(初回起動時)."""
    path = str(tmp_path / "does-not-exist.json")

    assert read_cache(path) == {}


def test_read_returns_empty_dict_when_file_corrupted(tmp_path: Path) -> None:
    """壊れたJSONでも例外にならず空dictを返す."""
    path = tmp_path / "corrupted.json"
    path.write_text("{not valid json", encoding="utf-8")

    assert read_cache(str(path)) == {}


def test_write_creates_parent_directory(tmp_path: Path) -> None:
    """親ディレクトリが無ければ作ってから書き込む."""
    path = str(tmp_path / "nested" / "cache.json")

    write_cache(path, {"111": "見出しA"})

    assert read_cache(path) == {"111": "見出しA"}
