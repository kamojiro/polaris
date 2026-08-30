import { useState } from "react";
import type { DiaryDayEntry } from "./useChatAgent";

interface DiaryPanelProps {
  entries: DiaryDayEntry[];
}

/**
 * 執筆中の日記パネル(019-diary-domain User Story 6)。
 *
 * 末尾の要素(`updated_at`が最新)を「編集中」として強調表示する。「本日」ではなく「編集中」と
 * 呼んでいるのは、バックフィル(過去日への追記、User Story 4)によって強調対象が発話時点の
 * 当日と一致しないことがあるため(FR-013)。
 */
export function DiaryPanel({ entries }: DiaryPanelProps) {
  const [collapsed, setCollapsed] = useState(false);

  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="diary-panel">
      <div className="diary-panel-header">
        <span>📔 日記</span>
        <button type="button" onClick={() => setCollapsed((prev) => !prev)} title={collapsed ? "展開" : "折りたたむ"}>
          {collapsed ? "▸" : "▾"}
        </button>
      </div>
      {!collapsed && (
        <div className="diary-panel-body">
          {entries.map((entry, index) => {
            const isAnchor = index === entries.length - 1;
            return (
              <div key={entry.entry_date} className={isAnchor ? "diary-panel-entry diary-panel-entry-anchor" : "diary-panel-entry"}>
                <div className="diary-panel-entry-date">
                  {entry.entry_date}
                  {isAnchor && <span className="diary-panel-entry-label">編集中</span>}
                </div>
                <p>{entry.content}</p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
