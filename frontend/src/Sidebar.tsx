import type { ReactNode } from "react";

/**
 * チャット欄右側の汎用パネル(008拡張のニュースピックアップから着手)。
 * レイアウトの器だけを持ち、中身(何を表示するか)は呼び出し側が children で渡す。
 */
export function Sidebar({ children }: { children: ReactNode }) {
  return <aside className="sidebar">{children}</aside>;
}
