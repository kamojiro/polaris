"""Discordサイドバーの見出し(LLM生成のdisplay_title)をメッセージid単位でファイルキャッシュする.

021-discord-integration 方向性3。メッセージ本文(URLのみのことが多い)からLLMで短い見出しを
作るのは、同じメッセージがサイドバーに表示され続ける間、毎回のfetchで呼び直すと無駄
(投稿後にメッセージ本文はほぼ変わらない)。NewsRecordのようなDB化はせず、
`{message_id: display_title}`の単純なJSONファイル1つに留める(YAGNI)。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def read_cache(path: str) -> dict[str, str]:
    """キャッシュファイルを読む(存在しない、または壊れていれば空のdictを返す)."""
    file = Path(path)
    if not file.exists():
        return {}
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Discord見出しキャッシュの読み込みに失敗しました: %s", path, exc_info=True)
        return {}


def write_cache(path: str, cache: dict[str, str]) -> None:
    """キャッシュファイルを書き直す(親ディレクトリが無ければ作る)."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
