"""進捗表示用の超軽量な状態共有.

Polaris は個人用ツールで、同時に走る ingest 処理は基本的に1つしか想定しない。
そのためリクエストごとに配線するのではなく、プロセス内でグローバルな状態を
持つだけで十分と判断した。要約生成とEmbedding生成は並行して走るため、
単一の文字列ではなく key ごとの複数行を保持できるようにしている。
フロント側はポーリングでこれを読み、「今何をしているか」を表示する。
"""

import threading

# 表示順序(この順で存在する行だけを並べる)。
_KEY_ORDER = ("stage", "structure", "embedding")

_lock = threading.Lock()
_current: dict[str, str] = {}


def set_progress(key: str, message: str | None) -> None:
    """特定のタスク(key)の進捗メッセージを更新する(Noneでその行を消す)."""
    with _lock:
        if message is None:
            _current.pop(key, None)
        else:
            _current[key] = message


def get_progress_lines() -> list[str]:
    """現在進行中の全タスクの進捗メッセージを、決まった表示順で返す."""
    with _lock:
        return [_current[key] for key in _KEY_ORDER if key in _current]
