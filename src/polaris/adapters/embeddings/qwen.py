"""sentence-transformers 経由の Qwen3-Embedding-0.6B ローカル実装.

モデルは `__init__` で 1 度だけロードしてプロセス内に保持する(呼び出しごとの
再ロードはしない)。`encode()` は同期・ブロッキング呼び出しのため、
`asyncio.to_thread()` でスレッドに逃がしてイベントループを塞がないようにする。
"""

import asyncio
import logging

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# sentence-transformers の encode() は内部で既にバッチ処理しており、デフォルトの
# batch_size も 32。それより小さくすると外側の呼び出し回数が増えるだけで
# GPU 上のバッチ化効果を落としてしまうため、進捗ログの粒度もこれに合わせる。
_PROGRESS_BATCH_SIZE = 32


class QwenEmbedder:
    """Qwen3-Embedding-0.6B をローカルロードして Embedding を計算する."""

    def __init__(self, model_id: str) -> None:
        """モデルをロードする(GPU があれば自動的に使われる).

        既にローカルキャッシュにある場合は Hugging Face Hub に一切アクセスせず
        (`local_files_only=True`)、未キャッシュの初回のみ通常ロードでダウンロードする。
        """
        self._model_id = model_id
        try:
            self._model = SentenceTransformer(model_id, local_files_only=True)
        except OSError:
            self._model = SentenceTransformer(model_id)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """テキストのバッチを正規化済みベクトルへ変換する.

        `_PROGRESS_BATCH_SIZE` 件ずつに分けて `encode()` を呼び、都度ログで
        進捗(何件中何件終わったか)を出す。
        """
        vectors: list[list[float]] = []
        total = len(texts)
        for start in range(0, total, _PROGRESS_BATCH_SIZE):
            sub_batch = texts[start : start + _PROGRESS_BATCH_SIZE]
            sub_vectors = await asyncio.to_thread(self._model.encode, sub_batch, normalize_embeddings=True)
            vectors.extend(sub_vectors.tolist())
            logger.info("Embedding進捗: %d/%d チャンク完了", len(vectors), total)
        return vectors

    @property
    def model_id(self) -> str:
        """`EmbeddingRecord.model` に記録するモデル識別子."""
        return self._model_id
