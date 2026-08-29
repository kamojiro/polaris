"""EDINET(金融庁の開示書類システム)API v2 への HTTP アクセス.

013-ir-analysis-domain: 書類取得エンドポイント(`GET /api/v2/documents/{docID}?type=2`)は
PDFをそのまま返すため、XBRLパースは不要(spec「背景・判断」参照)。書類一覧API
(`GET /api/v2/documents.json`)はv1では使わない(企業名検索が無く、日次スキャンは
個人用ツールには過剰と判断、spec参照)ため、ここでは単一書類のPDF取得のみを提供する。

書類取得APIは`Subscription-Key`(無料登録で発行されるAPIキー)がクエリパラメータとして
必須。`adapters/arxiv/client.py`/`adapters/searxng/client.py`と同じ、薄いhttpxラッパーの形。
"""

from __future__ import annotations

import httpx

_DOCUMENT_PATH = "/documents/{doc_id}"
_TIMEOUT_SECONDS = 60.0
# type=2: PDF(提出本文書及び監査報告書)を取得する。type=1はXBRL等を含むZIPになる
# (v1ではXBRLパースをしないため使わない、spec「背景・判断」参照)。
_PDF_DOCUMENT_TYPE = "2"


class EdinetClientError(Exception):
    """EDINET APIへのリクエストが失敗した場合の例外."""


async def fetch_edinet_document_pdf(
    doc_id: str,
    *,
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
) -> bytes:
    """doc_id(EDINETの書類管理番号、例: S100XXXX)の提出書類PDFをダウンロードする.

    Raises:
        EdinetClientError: HTTPリクエストが失敗した場合。

    """
    try:
        response = await client.get(
            f"{base_url}{_DOCUMENT_PATH.format(doc_id=doc_id)}",
            params={"type": _PDF_DOCUMENT_TYPE, "Subscription-Key": api_key},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        msg = f"EDINETからの書類取得に失敗しました: doc_id={doc_id!r}"
        raise EdinetClientError(msg) from exc
    return response.content
