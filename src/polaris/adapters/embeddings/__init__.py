"""Embedding モデルの抽象・実装.

呼び出し側は `EmbeddingModel` Protocol だけに依存させ、ローカルの
sentence-transformers モデルから将来 API 経由の別モデルへ差し替え可能にしておく。
"""

from typing import Protocol


class EmbeddingModel(Protocol):
    """テキストのバッチを Embedding ベクトルへ変換する抽象."""

    @property
    def model_id(self) -> str:
        """`EmbeddingRecord.model` に記録するモデル識別子."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """複数テキストをまとめてベクトル化する."""
        ...
