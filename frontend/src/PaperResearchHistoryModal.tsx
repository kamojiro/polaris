import { useEffect, useState } from "react";
import type { PaperResearchItem } from "./PaperResearchList";

interface PaperResearchHistoryModalProps {
  onClose: () => void;
}

/**
 * 完了済みの関連論文調査(027-related-paper-research)を新しい順に一覧表示するモーダル。
 * `PaperResearchList.tsx`の「一覧」ボタンから開く。AG-UIの会話履歴(messages)には
 * 一切触れないchat非依存のUI(2026-09-13追加、ユーザー要望「チャット履歴には加えずに
 * 出せるとなおいい」)。行クリックで、その場に統合結果の全文を展開する。
 */
export function PaperResearchHistoryModal({ onClose }: PaperResearchHistoryModalProps) {
  const [items, setItems] = useState<PaperResearchItem[] | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch("/api/paper-research");
        const body = res.ok ? ((await res.json()) as PaperResearchItem[]) : [];
        if (!cancelled) {
          setItems(body);
        }
      } catch {
        if (!cancelled) {
          setItems([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="paper-research-history-backdrop" onClick={onClose}>
      <div className="paper-research-history-modal" onClick={(event) => event.stopPropagation()}>
        <div className="paper-research-history-header">
          <h2>関連論文調査の履歴</h2>
          <button type="button" onClick={onClose} title="閉じる">
            ✕
          </button>
        </div>
        <div className="paper-research-history-body">
          {items === null && <p className="paper-research-history-loading">読み込み中…</p>}
          {items !== null && items.length === 0 && (
            <p className="paper-research-history-empty">完了した調査はまだありません。</p>
          )}
          {items?.map((item) => {
            const isExpanded = item.research_id === expandedId;
            return (
              <div key={item.research_id} className="paper-research-history-entry">
                <button
                  type="button"
                  className="paper-research-history-item"
                  onClick={() => setExpandedId(isExpanded ? null : item.research_id)}
                >
                  <span className="paper-research-history-title">{item.seed_title}</span>
                  <span className="paper-research-history-meta">{item.completed_at.slice(0, 10)}</span>
                </button>
                {isExpanded && <p className="paper-research-history-detail">{item.result_summary}</p>}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
