import { useCallback, useEffect, useState } from "react";

interface PaperResearchItem {
  research_id: string;
  seed_title: string;
  result_summary: string;
  completed_at: string;
}

/**
 * 完了済みの関連論文調査(027-related-paper-research)を新しい順に一覧表示するSidebar内の
 * 1セクション。`PaperResearchBanner.tsx`(直近1件の新着通知)とは別に、過去分も含めて
 * 見返せるようにしたもの(2026-09-13追加、ユーザーからのフィードバックで着想)。
 *
 * `NewsSidebar.tsx`/`DiscordSidebar.tsx`と同じ「ページを開いた時点でアンビエントに取得」
 * パターンだが、行クリックの挙動だけ異なる: あちらはチャットへの引き渡し
 * (`sendMessage`)だが、こちらは統合結果をその場で展開表示する(チャットの会話には
 * 影響させない、単なる閲覧のため)。
 */
export function PaperResearchList() {
  const [items, setItems] = useState<PaperResearchItem[] | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch("/api/paper-research");
      if (!res.ok) {
        return;
      }
      setItems((await res.json()) as PaperResearchItem[]);
    } catch {
      // アンビエントな一覧なので、取得に失敗しても静かに諦める。
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (items === null || items.length === 0) {
    return null;
  }

  return (
    <section className="paper-research-list">
      <div className="paper-research-list-header">
        <h2>関連論文調査</h2>
        <button
          type="button"
          className="paper-research-list-refresh"
          onClick={() => void load()}
          disabled={isLoading}
          title="再読み込み"
        >
          🔄
        </button>
      </div>
      {items.map((item) => {
        const isExpanded = item.research_id === expandedId;
        return (
          <div key={item.research_id} className="paper-research-list-entry">
            <button
              type="button"
              className="paper-research-list-item"
              onClick={() => setExpandedId(isExpanded ? null : item.research_id)}
            >
              <span className="paper-research-list-title">{item.seed_title}</span>
              <span className="paper-research-list-meta">{item.completed_at.slice(0, 10)}</span>
            </button>
            {isExpanded && <p className="paper-research-list-detail">{item.result_summary}</p>}
          </div>
        );
      })}
    </section>
  );
}
