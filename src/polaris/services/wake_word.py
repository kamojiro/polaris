"""ウェイクワード検知(026-voice-input Stage 1.5)のスコアリング.

Whisper tiny.enの凍結エンコーダー(`adapters/wake_word/encoder.py`、Protocol経由で注入)で
作った768次元特徴量に、学習済みロジスティック回帰(`model.npz`)を適用してスコアを出す。
numpyのみに依存する軽い層に留め、torch/whisperへの依存はadapters層に閉じ込める。

移植元(`realtime_detect_whisper.py`)のスライディングウィンドウ方式をそのまま踏襲する:
窓(`window_seconds`)をチャンク(`chunk_seconds`)ぶんずつ押し出しながら、チャンクが
届くたびに窓全体を再スコアリングする。
"""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)


class WakeWordEncoder(Protocol):
    """窓ぶんの音声から特徴量を作る抽象(`adapters/wake_word/encoder.py`が実装)."""

    async def embed(self, audio: np.ndarray) -> np.ndarray:
        """窓ぶんの音声(float32)から特徴ベクトルを作る."""
        ...


class WakeWordModel:
    """学習済みロジスティック回帰によるスコアリング(`model.npz`から読み込む).

    移植元(`realtime_detect_whisper.py::load_model`/`score`)をそのまま移す。
    """

    def __init__(
        self,
        *,
        coef: np.ndarray,
        intercept: np.ndarray,
        scaler_mean: np.ndarray,
        scaler_scale: np.ndarray,
    ) -> None:
        """`model.npz`から読み込んだ配列をそのまま保持する(`load()`から使う想定)."""
        self._coef = coef
        self._intercept = intercept
        self._scaler_mean = scaler_mean
        self._scaler_scale = scaler_scale

    @classmethod
    def load(cls, path: str) -> WakeWordModel:
        """`model.npz`(coef/intercept/scaler_mean/scaler_scale)から読み込む."""
        data = np.load(path)
        return cls(
            coef=data["coef"],
            intercept=data["intercept"],
            scaler_mean=data["scaler_mean"],
            scaler_scale=data["scaler_scale"],
        )

    def score(self, embedding: np.ndarray) -> float:
        """0〜1のウェイクワードらしさのスコアを返す."""
        scaled = (embedding - self._scaler_mean) / self._scaler_scale
        logit = float(scaled @ self._coef[0] + self._intercept[0])
        return 1.0 / (1.0 + np.exp(-logit))


class WakeWordStream:
    """接続1本ぶんのスライディングウィンドウ+スコアリング状態.

    窓は`chunk_seconds`のストライドで重なるため、閾値超え(検知)の直後は
    バッファをゼロクリアする。クリアしないと同じ発話に対して連続発火する。

    音声の取り込み(`_buffer`への追記)は`push()`が呼ばれるたびに必ず行うが、
    スコアリング(エンコーダー推論)が前回分だけで完了していない間に次の`push()`が
    呼ばれた場合は、そのストライドのスコアリングをスキップする。呼び出し元が
    スコアリングの完了を待たずに次のチャンクを取り込めるようにするための設計
    (CPU推論や他ジョブでGPUが埋まっている場合に遅延が雪だるま式に伸びるのを防ぐ)。
    """

    def __init__(
        self,
        *,
        model: WakeWordModel,
        encoder: WakeWordEncoder,
        window_len: int,
        threshold: float,
        log_threshold: float,
    ) -> None:
        """`window_len`サンプル(通常`window_seconds * sample_rate`)のゼロ埋めバッファで始める."""
        self._model = model
        self._encoder = encoder
        self._window_len = window_len
        self._threshold = threshold
        self._log_threshold = log_threshold
        self._buffer = np.zeros(window_len, dtype=np.float32)
        self._scoring = False

    async def push(self, chunk: np.ndarray) -> float | None:
        """chunkをバッファへ追記し、必要ならスコアリングする.

        戻り値: 検知した場合はそのスコア、それ以外(未検知・スコアリングを
        スキップした場合を含む)は`None`。
        """
        self._buffer = np.concatenate([self._buffer, chunk])[-self._window_len :]

        if self._scoring:
            return None

        self._scoring = True
        try:
            embedding = await self._encoder.embed(self._buffer)
            score = self._model.score(embedding)
        finally:
            self._scoring = False

        if score > self._threshold:
            logger.info("ウェイクワード検知: score=%.3f", score)
            self._buffer = np.zeros(self._window_len, dtype=np.float32)
            return score

        if score > self._log_threshold:
            logger.debug("ウェイクワード惜しい: score=%.3f", score)

        return None

    @property
    def buffer(self) -> np.ndarray:
        """現在のスライディングウィンドウの中身(テスト・診断用の読み取り専用アクセサ)."""
        return self._buffer
