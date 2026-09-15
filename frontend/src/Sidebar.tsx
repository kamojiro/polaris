import type { ReactNode } from "react";

interface SidebarProps {
  children: ReactNode;
}

/**
 * チャット欄右側の汎用パネル(008拡張のニュースピックアップから着手)。
 * レイアウトの器だけを持ち、中身(何を表示するか)は呼び出し側が children で渡す。
 *
 * 日記モード中(019拡張)はこのSidebarごと`.diary-canvas`に差し替えるため、幅を可変にする
 * propは持たない(2026-09-15方針決定: サイドバーを広げるのではなく一時的に隠す)。
 */
export function Sidebar({ children }: SidebarProps) {
  return <aside className="sidebar">{children}</aside>;
}
