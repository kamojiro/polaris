import { useEffect, useState } from "react";

interface HousekeepingSuggestionResponse {
  suggestion_type: string;
  target_themes: string[];
  detail: string;
}

interface MemoryHousekeepingResponse {
  generated_at: string;
  suggestions: HousekeepingSuggestionResponse[];
}

const SUGGESTION_TYPE_LABELS: Record<string, string> = {
  merge: "統合",
  split: "分割",
  stale: "長期未更新",
};

const LAST_SEEN_KEY = "polaris.memoryHousekeeping.lastSeenGeneratedAt";

function readLastSeen(): string | null {
  try {
    return localStorage.getItem(LAST_SEEN_KEY);
  } catch {
    return null;
  }
}

function writeLastSeen(generatedAt: string): void {
  try {
    localStorage.setItem(LAST_SEEN_KEY, generatedAt);
  } catch {
    // プライベートウィンドウ等でlocalStorageが使えない場合は諦める(この回だけ再表示されうる)。
  }
}

/**
 * 記憶テーマの定期棚卸し(024-memory-theme-housekeeping)の通知バナー。ページロード時に
 * 最新の検出結果を取得し、候補が1件以上あれば表示する。`DailySummaryBanner.tsx`と同じ
 * 「コンポーネント内完結」パターン。既読管理はサーバー側に持たず、ブラウザのlocalStorageに
 * 最終既読の`generated_at`を持つ(User Story 3、023の`summary_date`比較と同型)。
 *
 * 生成自体はここでは行わない(`cli/run_memory_housekeeping.py`がcronから叩く)。取得のみ。
 */
export function MemoryHousekeepingBanner() {
  const [data, setData] = useState<MemoryHousekeepingResponse | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch("/api/memory-housekeeping/latest");
        if (!res.ok) {
          return;
        }
        const body = (await res.json()) as MemoryHousekeepingResponse | null;
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

  if (data === null || data.suggestions.length === 0 || dismissed || readLastSeen() === data.generated_at) {
    return null;
  }

  const handleDismiss = () => {
    writeLastSeen(data.generated_at);
    setDismissed(true);
  };

  return (
    <div className="memory-housekeeping-banner">
      <div className="memory-housekeeping-banner-body">
        <span className="memory-housekeeping-banner-title">
          🧹 記憶テーマの整理提案が{data.suggestions.length}件あります
        </span>
        <ul>
          {data.suggestions.map((suggestion, index) => (
            <li key={index}>
              <strong>{SUGGESTION_TYPE_LABELS[suggestion.suggestion_type] ?? suggestion.suggestion_type}</strong>
              {" "}
              ({suggestion.target_themes.join(", ")}): {suggestion.detail}
            </li>
          ))}
        </ul>
      </div>
      <button type="button" onClick={handleDismiss} title="閉じる">
        ✕
      </button>
    </div>
  );
}
