"""Whisper tiny.en の凍結エンコーダーによる特徴抽出(026-voice-input Stage 1.5).

移植元(Polarisリポジトリ外の個人用プロトタイピングプロジェクトの`features_whisper.py`、
`greg1232/hey-claude` の手法の再現)のロジックをそのまま移す:

    2秒の音声
        -> Whisper tiny.en の凍結エンコーダー   (1500フレーム, 384次元)
        -> 最初の `n_pool_frames` フレームだけ取り出す
        -> mean pooling と max pooling を計算して連結   (768次元)

学習済みのロジスティック回帰(`services/wake_word.py::WakeWordModel`)へ渡す特徴量を
作るだけで、エンコーダー自体は一切更新しない。モデルは `__init__` で 1 度だけロードして
プロセス内に保持する(`adapters/embeddings/qwen.py`と同じ方針)。
"""

import asyncio
import logging
import os

# torch import前に設定する必要がある(adapters/embeddings/qwen.pyと同じ理由)。
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
import torch
import whisper

logger = logging.getLogger(__name__)


class WhisperWakeWordEncoder:
    """Whisper tiny.en の凍結エンコーダーで2秒窓の音声を768次元特徴量へ変換する."""

    def __init__(self, model_id: str, *, n_pool_frames: int) -> None:
        """モデルをロードする(GPUがあれば自動的に使われる)."""
        self._n_pool_frames = n_pool_frames
        logger.info("Whisper %s をロード中...", model_id)
        self._model = whisper.load_model(model_id)
        self._model.eval()
        self._log_gpu_memory("ロード後")

    async def embed(self, audio: np.ndarray) -> np.ndarray:
        """16kHz float32・単一チャンネルの音声(2秒窓)から768次元の特徴ベクトルを作る.

        推論はブロッキング処理のため `asyncio.to_thread()` でスレッドに逃がし、
        イベントループ(WebSocketの他接続の受信ループ)を塞がないようにする。
        """
        return await asyncio.to_thread(self._embed_sync, audio)

    def _embed_sync(self, audio: np.ndarray) -> np.ndarray:
        device = next(self._model.parameters()).device
        trimmed = whisper.pad_or_trim(audio.astype(np.float32))
        mel = whisper.log_mel_spectrogram(trimmed).to(device)

        with torch.no_grad():
            hidden = self._model.encoder(mel.unsqueeze(0))  # (1, 1500, n_state=384)

        hidden = hidden[:, : self._n_pool_frames, :]
        mean_pool = hidden.mean(dim=1)
        max_pool = hidden.max(dim=1).values
        pooled = torch.cat([mean_pool, max_pool], dim=1)  # (1, 768)

        return pooled.squeeze(0).cpu().numpy().astype(np.float32)

    def _log_gpu_memory(self, label: str) -> None:
        """GPUメモリ使用量をログに残す(adapters/embeddings/qwen.pyと同じ診断ログ)."""
        if not torch.cuda.is_available():
            return
        logger.info(
            "GPU memory(%s): allocated=%dMiB reserved=%dMiB",
            label,
            torch.cuda.memory_allocated() // (1024 * 1024),
            torch.cuda.memory_reserved() // (1024 * 1024),
        )
