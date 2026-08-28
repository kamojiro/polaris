import { useCallback, useEffect, useState } from "react";

export interface SidebarNewsItem {
  display_title: string;
  title: string;
  source_name: string;
  source_label: string;
  published_at: string;
  source_url: string;
}

interface NewsSidebarProps {
  onSelect: (item: SidebarNewsItem) => void;
}

const SIDEBAR_COUNT = 5;

/**
 * 取り込み済みニュースからランダムに数件をピックして表示する、Sidebar内の1セクション
 * (008-daily-digest-domain拡張)。チャットの list_news ツール結果(会話履歴の一部としてのみ
 * 表示される)とは別に、ページを開いた時点でアンビエントに見せたいため、専用のREST
 * エンドポイント(`/api/news/picks`)から直接取得する(チャット履歴を汚さない)。
 *
 * クリックすると `onSelect` 経由で親(App.tsx)がチャットメッセージを送り、通常の会話の
 * 流れで詳しい説明を引き出す(PaperList.tsx の「タイトルクリックで論文モードへ」と同じ考え方)。
 */
export function NewsSidebar({ onSelect }: NewsSidebarProps) {
  const [items, setItems] = useState<SidebarNewsItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/news/picks?count=${SIDEBAR_COUNT}`);
      if (!res.ok) {
        throw new Error(`取得に失敗しました(status=${res.status})`);
      }
      setItems((await res.json()) as SidebarNewsItem[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="news-sidebar">
      <div className="news-sidebar-header">
        <h2>ピックアップ</h2>
        <button
          type="button"
          className="news-sidebar-refresh"
          onClick={() => void load()}
          disabled={isLoading}
          title="入れ替える"
        >
          🔀
        </button>
      </div>
      {error !== null && <p className="news-sidebar-empty">{error}</p>}
      {error === null && items === null && <p className="news-sidebar-loading">読み込み中…</p>}
      {error === null && items !== null && items.length === 0 && (
        <p className="news-sidebar-empty">取り込み済みのニュースはまだありません。</p>
      )}
      {items !== null &&
        items.map((item) => (
          <button
            key={item.source_url}
            type="button"
            className={`news-sidebar-item news-bucket-${item.source_label}`}
            onClick={() => onSelect(item)}
          >
            <span className="news-sidebar-title">{item.display_title}</span>
            <span className="news-sidebar-meta">{item.source_name}</span>
          </button>
        ))}
    </section>
  );
}
