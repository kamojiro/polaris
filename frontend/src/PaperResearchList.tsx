import { useCallback, useEffect, useState } from "react";

export interface PaperResearchItem {
  research_id: string;
  seed_title: string;
  result_summary: string;
  completed_at: string;
}

interface PaperResearchListProps {
  onOpenHistory: () => void;
}

/**
 * 完了済みの関連論文調査(027-related-paper-research)のうち、最新1件だけを常時表示する
 * Sidebar内の1セクション。`PaperResearchBanner.tsx`(新着通知、既読で消える)とは別に、
 * 「今わかっていること」をアンビエントに見せる用途(2026-09-13追加)。
 *
 * 過去分すべてを見るには「一覧」ボタンから`PaperResearchHistoryModal.tsx`を開く。
 * 一覧はAG-UIの会話履歴(messages)を一切経由しないchat非依存のUIにしている
 * (ユーザー要望: 「チャット履歴には加えずに出せるとなおいい」)。
 */
export function PaperResearchList({ onOpenHistory }: PaperResearchListProps) {
  const [latest, setLatest] = useState<PaperResearchItem | null>(null);
  const [expanded, setExpanded] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/paper-research/latest");
      if (!res.ok) {
        return;
      }
      setLatest((await res.json()) as PaperResearchItem | null);
    } catch {
      // アンビエントな表示なので、取得に失敗しても静かに諦める。
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (latest === null) {
    return null;
  }

  return (
    <section className="paper-research-list">
      <div className="paper-research-list-header">
        <h2>関連論文調査</h2>
        <button type="button" className="paper-research-list-open-history" onClick={onOpenHistory}>
          一覧
        </button>
      </div>
      <button type="button" className="paper-research-list-item" onClick={() => setExpanded((prev) => !prev)}>
        <span className="paper-research-list-title">{latest.seed_title}</span>
        <span className="paper-research-list-meta">{latest.completed_at.slice(0, 10)}</span>
      </button>
      {expanded && <p className="paper-research-list-detail">{latest.result_summary}</p>}
    </section>
  );
}
