"""sentence-transformers 経由の Qwen3-Embedding-0.6B ローカル実装.

モデルは `__init__` で 1 度だけロードしてプロセス内に保持する(呼び出しごとの
再ロードはしない)。`encode()` は同期・ブロッキング呼び出しのため、
`asyncio.to_thread()` でスレッドに逃がしてイベントループを塞がないようにする。
"""

import asyncio
import gc
import logging
import os

# tokenizers(sentence-transformers の依存)はフォーク後に並列トークナイズを使うと
# デッドロック・警告を起こすことがあるため、既存の設定を上書きしない範囲で無効化する。
# PYTORCH_CUDA_ALLOC_CONF は CUDA キャッシングアロケータの断片化対策(公式推奨設定)。
# どちらも CUDA 初期化前(= torch / sentence_transformers を import する前)に設定する必要がある。
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from sentence_transformers import SentenceTransformer

from polaris.services.progress import set_progress

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
        進捗(何件中何件終わったか)を出す。バッチ完了ごとに `empty_cache()` で
        未使用のキャッシュ済みメモリを解放し、allocated/reserved をログに残す
        (GPUメモリが長寿命プロセスでじわじわ増える問題の切り分け用)。
        呼び出し終了後だけでなく毎バッチ後・失敗直前にも記録することで、
        OOMが起きた瞬間の状態も追えるようにしている。
        """
        vectors: list[list[float]] = []
        total = len(texts)
        try:
            for start in range(0, total, _PROGRESS_BATCH_SIZE):
                sub_batch = texts[start : start + _PROGRESS_BATCH_SIZE]
                try:
                    sub_vectors = await asyncio.to_thread(self._model.encode, sub_batch, normalize_embeddings=True)
                except RuntimeError:
                    self._log_gpu_memory("失敗直前")
                    raise
                vectors.extend(sub_vectors.tolist())
                logger.info("Embedding進捗: %d/%d チャンク完了", len(vectors), total)
                set_progress("embedding", f"Embedding生成中: {len(vectors)}/{total} チャンク完了")
                self._log_gpu_memory("バッチ完了後")
        finally:
            set_progress("embedding", None)

        return vectors

    def _log_gpu_memory(self, label: str) -> None:
        """GPUメモリ使用量(allocated/reserved)をログに残す(リーク調査用の診断ログ)."""
        if not torch.cuda.is_available():
            return
        gc.collect()
        torch.cuda.empty_cache()
        logger.info(
            "GPU memory(%s): allocated=%dMiB reserved=%dMiB",
            label,
            torch.cuda.memory_allocated() // (1024 * 1024),
            torch.cuda.memory_reserved() // (1024 * 1024),
        )

    @property
    def model_id(self) -> str:
        """`EmbeddingRecord.model` に記録するモデル識別子."""
        return self._model_id
