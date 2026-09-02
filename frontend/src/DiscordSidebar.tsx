import { useCallback, useEffect, useState } from "react";

export interface SidebarDiscordItem {
  id: string;
  content: string;
  author_name: string;
  created_at: string;
}

interface DiscordSidebarProps {
  onSelect: (item: SidebarDiscordItem) => void;
}

/**
 * Discordの監視対象チャンネルの直近メッセージを表示する、Sidebar内の1セクション
 * (021-discord-integration 方向性3)。`NewsSidebar.tsx`と同じ「ページを開いた時点で
 * アンビエントに見せる」パターンだが、永続化はしない(`GET /api/discord/recent`が
 * Discord APIをその場でライブに叩くだけ)。
 *
 * `settings.discord`が未設定の利用者には空リストが返る。その場合はNewsSidebarと違い
 * 「メッセージがありません」的な空表示はせず、セクションごと非表示にする(Discord連携を
 * 使わない大半の利用者に空セクションを見せないため)。
 *
 * クリックすると `onSelect` 経由で親(App.tsx)がチャットメッセージを送り、通常の会話の
 * 流れで詳しい説明を引き出す(NewsSidebar.tsx と同じ考え方)。
 */
export function DiscordSidebar({ onSelect }: DiscordSidebarProps) {
  const [items, setItems] = useState<SidebarDiscordItem[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch("/api/discord/recent");
      if (!res.ok) {
        return;
      }
      setItems((await res.json()) as SidebarDiscordItem[]);
    } catch {
      // アンビエントな表示機能なので、取得に失敗しても静かに諦める。
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
    <section className="discord-sidebar">
      <div className="discord-sidebar-header">
        <h2>Discord</h2>
        <button
          type="button"
          className="discord-sidebar-refresh"
          onClick={() => void load()}
          disabled={isLoading}
          title="更新"
        >
          🔀
        </button>
      </div>
      {items.map((item) => (
        <button key={item.id} type="button" className="discord-sidebar-item" onClick={() => onSelect(item)}>
          <span className="discord-sidebar-content">{item.content}</span>
          <span className="discord-sidebar-meta">{item.author_name}</span>
        </button>
      ))}
    </section>
  );
}
