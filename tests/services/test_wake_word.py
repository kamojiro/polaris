"""services/wake_word.py のロジックテスト.

Whisperエンコーダー(重い依存)はフェイクに差し替え(`tests/services/test_memory.py`の
フェイクエージェントと同じやり方)、numpyだけで完結するスコアリング・ウィンドウ管理を
実DB・実モデルなしで検証する。
"""

import asyncio
from pathlib import Path

import numpy as np
import pytest

from polaris.services.wake_word import WakeWordModel, WakeWordStream

_THRESHOLD = 0.5
_LOG_THRESHOLD = 0.1
_WINDOW_LEN = 4


class _FixedEncoder:
    """常に固定の埋め込みを返すフェイクエンコーダー(呼び出し回数を記録する)."""

    def __init__(self, embedding: np.ndarray) -> None:
        self._embedding = embedding
        self.calls: list[np.ndarray] = []

    async def embed(self, audio: np.ndarray) -> np.ndarray:
        self.calls.append(audio.copy())
        return self._embedding


class _BlockingEncoder:
    """1回目の呼び出しが`release`されるまで待つフェイクエンコーダー(競合検証用)."""

    def __init__(self, embedding: np.ndarray) -> None:
        self._embedding = embedding
        self.calls = 0
        self.release = asyncio.Event()

    async def embed(self, audio: np.ndarray) -> np.ndarray:  # noqa: ARG002
        self.calls += 1
        await self.release.wait()
        return self._embedding


def _one_dim_model(*, mean: float = 0.0, scale: float = 1.0) -> WakeWordModel:
    """スコア = sigmoid(embedding[0]) になる、埋め込み1次元の単純なモデル."""
    return WakeWordModel(
        coef=np.array([[1.0]], dtype=np.float32),
        intercept=np.array([0.0], dtype=np.float32),
        scaler_mean=np.array([mean], dtype=np.float32),
        scaler_scale=np.array([scale], dtype=np.float32),
    )


def test_score_matches_manual_sigmoid() -> None:
    """score()が手計算のsigmoidと一致する."""
    coef = np.array([[0.5, -0.25]], dtype=np.float32)
    intercept = np.array([0.1], dtype=np.float32)
    scaler_mean = np.array([1.0, 2.0], dtype=np.float32)
    scaler_scale = np.array([2.0, 4.0], dtype=np.float32)
    model = WakeWordModel(coef=coef, intercept=intercept, scaler_mean=scaler_mean, scaler_scale=scaler_scale)
    embedding = np.array([3.0, 6.0], dtype=np.float32)

    scaled = (embedding - scaler_mean) / scaler_scale
    expected = 1.0 / (1.0 + np.exp(-(float(scaled @ coef[0]) + float(intercept[0]))))

    assert model.score(embedding) == pytest.approx(expected)


def test_load_from_npz(tmp_path: Path) -> None:
    """model.npz(coef/intercept/scaler_mean/scaler_scale)から正しく読み込める."""
    path = tmp_path / "model.npz"
    np.savez(
        path,
        coef=np.array([[1.0]], dtype=np.float32),
        intercept=np.array([0.0], dtype=np.float32),
        scaler_mean=np.array([0.0], dtype=np.float32),
        scaler_scale=np.array([1.0], dtype=np.float32),
    )
    model = WakeWordModel.load(str(path))

    assert model.score(np.array([0.0], dtype=np.float32)) == pytest.approx(0.5)


async def test_push_returns_none_when_below_threshold() -> None:
    """スコアが閾値未満なら未検知(None)として扱う."""
    encoder = _FixedEncoder(np.array([-10.0], dtype=np.float32))  # sigmoid(-10) ≈ 0
    stream = WakeWordStream(
        model=_one_dim_model(),
        encoder=encoder,
        window_len=_WINDOW_LEN,
        threshold=_THRESHOLD,
        log_threshold=_LOG_THRESHOLD,
    )

    result = await stream.push(np.array([1.0, 2.0], dtype=np.float32))

    assert result is None
    assert len(encoder.calls) == 1


async def test_push_detects_and_clears_buffer() -> None:
    """閾値超えで検知スコアを返し、同じ発話で連続発火しないようバッファをゼロクリアする."""
    encoder = _FixedEncoder(np.array([10.0], dtype=np.float32))  # sigmoid(10) ≈ 1
    stream = WakeWordStream(
        model=_one_dim_model(),
        encoder=encoder,
        window_len=_WINDOW_LEN,
        threshold=_THRESHOLD,
        log_threshold=_LOG_THRESHOLD,
    )

    result = await stream.push(np.array([1.0, 2.0], dtype=np.float32))

    assert result is not None
    assert result > _THRESHOLD
    assert np.array_equal(stream.buffer, np.zeros(_WINDOW_LEN, dtype=np.float32))


async def test_push_skips_scoring_when_already_in_progress() -> None:
    """前回のスコアリングが未完のまま次のchunkが来たら、スコアリングだけスキップしバッファは更新する."""
    encoder = _BlockingEncoder(np.array([-10.0], dtype=np.float32))
    stream = WakeWordStream(
        model=_one_dim_model(),
        encoder=encoder,
        window_len=_WINDOW_LEN,
        threshold=_THRESHOLD,
        log_threshold=_LOG_THRESHOLD,
    )

    task1 = asyncio.create_task(stream.push(np.array([1.0, 2.0], dtype=np.float32)))
    await asyncio.sleep(0)  # task1がencoder.embed()内のawaitで止まるまで進める

    result2 = await stream.push(np.array([3.0, 4.0], dtype=np.float32))

    assert result2 is None
    assert encoder.calls == 1  # 2回目の push はスコアリングをスキップした
    # スコアリングをスキップしても、バッファへの追記(2回目のchunk)は反映されている。
    assert stream.buffer.tolist() == [1.0, 2.0, 3.0, 4.0]

    encoder.release.set()
    result1 = await task1
    assert result1 is None
