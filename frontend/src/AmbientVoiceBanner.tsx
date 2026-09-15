import { useEffect, useState } from "react";

interface AmbientVoiceResponse {
  chunk_id: string;
  comment: string;
  completed_at: string;
}

const LAST_SEEN_KEY = "polaris.ambientVoice.lastSeenChunkId";

function readLastSeen(): string | null {
  try {
    return localStorage.getItem(LAST_SEEN_KEY);
  } catch {
    return null;
  }
}

function writeLastSeen(chunkId: string): void {
  try {
    localStorage.setItem(LAST_SEEN_KEY, chunkId);
  } catch {
    // プライベートウィンドウ等でlocalStorageが使えない場合は諦める(この回だけ再表示されうる)。
  }
}

/**
 * 常時音声認識(026-voice-input Stage2代替案)の反応通知バナー。`PaperResearchBanner.tsx`と
 * 同じ「コンポーネント内完結」パターン。既読管理はサーバー側に持たず、ブラウザの
 * localStorageに最終既読の`chunk_id`を持つ(`completed_at`ではなく`chunk_id`で比較するのは、
 * 判定処理が数秒〜数十秒で連続して走った場合に同じ`completed_at`秒になりうるため)。
 *
 * 生成自体はここでは行わない(`cli/run_ambient_voice.py`がcronから叩く)。取得のみ。
 */
export function AmbientVoiceBanner() {
  const [data, setData] = useState<AmbientVoiceResponse | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch("/api/ambient-voice/latest");
        if (!res.ok) {
          return;
        }
        const body = (await res.json()) as AmbientVoiceResponse | null;
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

  if (data === null || dismissed || readLastSeen() === data.chunk_id) {
    return null;
  }

  const handleDismiss = () => {
    writeLastSeen(data.chunk_id);
    setDismissed(true);
  };

  return (
    <div className="ambient-voice-banner">
      <span className="ambient-voice-banner-title">🎧 {data.comment}</span>
      <button type="button" onClick={handleDismiss} title="閉じる">
        ✕
      </button>
    </div>
  );
}
