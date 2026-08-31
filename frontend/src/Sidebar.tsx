import type { ReactNode } from "react";

interface SidebarProps {
  children: ReactNode;
  /** 追加のCSSクラス(例: 日記モード中に幅を広げる"sidebar-wide")。 */
  wide?: boolean;
}

/**
 * チャット欄右側の汎用パネル(008拡張のニュースピックアップから着手)。
 * レイアウトの器だけを持ち、中身(何を表示するか)は呼び出し側が children で渡す。
 */
export function Sidebar({ children, wide = false }: SidebarProps) {
  return <aside className={wide ? "sidebar sidebar-wide" : "sidebar"}>{children}</aside>;
}
