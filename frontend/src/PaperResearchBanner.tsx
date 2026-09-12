import { useEffect, useState } from "react";

interface PaperResearchResponse {
  research_id: string;
  seed_title: string;
  result_summary: string;
  completed_at: string;
}

const LAST_SEEN_KEY = "polaris.paperResearch.lastSeenCompletedAt";

function readLastSeen(): string | null {
  try {
    return localStorage.getItem(LAST_SEEN_KEY);
  } catch {
    return null;
  }
}

function writeLastSeen(completedAt: string): void {
  try {
    localStorage.setItem(LAST_SEEN_KEY, completedAt);
  } catch {
    // プライベートウィンドウ等でlocalStorageが使えない場合は諦める(この回だけ再表示されうる)。
  }
}

/**
 * 関連論文調査(027-related-paper-research)の完了通知バナー。ページロード時に直近の
 * 完了結果を取得し、未読なら表示する。`MemoryHousekeepingBanner.tsx`と同じ
 * 「コンポーネント内完結」パターン。既読管理はサーバー側に持たず、ブラウザの
 * localStorageに最終既読の`completed_at`を持つ。
 *
 * 統合結果は複数段落になりうるため、`NewsList.tsx`の`<details>`パターンで畳んで表示する
 * (023/024のバナーには展開機構が無いが、本文の長さがそれらと異なるため個別に採用する)。
 *
 * 生成自体はここでは行わない(`cli/run_paper_research.py`がcronから叩く)。取得のみ。
 */
export function PaperResearchBanner() {
  const [data, setData] = useState<PaperResearchResponse | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch("/api/paper-research/latest");
        if (!res.ok) {
          return;
        }
        const body = (await res.json()) as PaperResearchResponse | null;
        if (!cancelled) {
          setData(body);
        }
      } catch {
        // 通知的な機能なので、取得に失敗しても静かに諦める(チャット本体には影響させない)。
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (data === null || dismissed || readLastSeen() === data.completed_at) {
    return null;
  }

  const handleDismiss = () => {
    writeLastSeen(data.completed_at);
    setDismissed(true);
  };

  return (
    <div className="paper-research-banner">
      <div className="paper-research-banner-body">
        <span className="paper-research-banner-title">
          🔎 『{data.seed_title}』の関連論文調査が完了しました
        </span>
        <details className="paper-research-banner-details">
          <summary>調査結果を表示</summary>
          <p>{data.result_summary}</p>
        </details>
      </div>
      <button type="button" onClick={handleDismiss} title="閉じる">
        ✕
      </button>
    </div>
  );
}
