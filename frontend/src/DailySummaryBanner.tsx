import { useEffect, useState } from "react";

interface DailySummaryResponse {
  summary_date: string;
  content: string;
  generated_at: string;
}

const LAST_SEEN_KEY = "polaris.dailySummary.lastSeenDate";

function readLastSeen(): string | null {
  try {
    return localStorage.getItem(LAST_SEEN_KEY);
  } catch {
    return null;
  }
}

function writeLastSeen(summaryDate: string): void {
  try {
    localStorage.setItem(LAST_SEEN_KEY, summaryDate);
  } catch {
    // プライベートウィンドウ等でlocalStorageが使えない場合は諦める(この回だけ再表示されうる)。
  }
}

/**
 * 日次サマリー通知(023-daily-summary-notification)のバナー。ページロード時に最新のサマリーを
 * 取得し、まだ見ていない日付(summary_date)なら表示する。既読管理はサーバー側に持たず、
 * ブラウザのlocalStorageに最終既読日付を持つだけにする(spec未決定事項の確定、2026-08-30。
 * 個人用の単一ユーザーツールでは実害が薄く、DBスキーマ・APIを増やさずに済む)。
 *
 * 生成自体はここでは行わない(`cli/generate_daily_summary.py`がcronから叩く)。取得のみ。
 */
export function DailySummaryBanner() {
  const [summary, setSummary] = useState<DailySummaryResponse | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch("/api/daily-summary/latest");
        if (!res.ok) {
          return;
        }
        const data = (await res.json()) as DailySummaryResponse | null;
        if (!cancelled) {
          setSummary(data);
        }
      } catch {
        // 通知的な機能なので、取得に失敗しても静かに諦める(チャット本体には影響させない)。
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (summary === null || dismissed || readLastSeen() === summary.summary_date) {
    return null;
  }

  const handleDismiss = () => {
    writeLastSeen(summary.summary_date);
    setDismissed(true);
  };

  return (
    <div className="daily-summary-banner">
      <div className="daily-summary-banner-body">
        <span className="daily-summary-banner-date">📰 {summary.summary_date}のまとめ</span>
        <p>{summary.content}</p>
      </div>
      <button type="button" onClick={handleDismiss} title="閉じる">
        ✕
      </button>
    </div>
  );
}
