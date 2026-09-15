import type { DiaryDayEntry } from "./useChatAgent";

interface DiaryPanelProps {
  entries: DiaryDayEntry[];
}

/**
 * 執筆中の日記パネル(019-diary-domain User Story 6)の本文(`.diary-canvas-body`の中身)。
 *
 * 末尾の要素(`updated_at`が最新)を「編集中」として強調表示する。「本日」ではなく「編集中」と
 * 呼んでいるのは、バックフィル(過去日への追記、User Story 4)によって強調対象が発話時点の
 * 当日と一致しないことがあるため(FR-013)。
 *
 * 2026-09-15: canvas的な半々分割レイアウト(specs/019-diary-domain/layout-mockup.html)への
 * 変更に伴い、開閉トグル・見出し(📔日記)は親(App.tsxの.diary-canvas-header)が持つように
 * なったため、このコンポーネントはエントリのカード一覧だけを描画する。
 */
export function DiaryPanel({ entries }: DiaryPanelProps) {
  if (entries.length === 0) {
    return null;
  }

  return (
    <>
      {entries.map((entry, index) => {
        const isAnchor = index === entries.length - 1;
        return (
          <div key={entry.entry_date} className={isAnchor ? "entry-card entry-card-today" : "entry-card"}>
            <div className="entry-card-date">
              {entry.entry_date}
              {isAnchor && <span className="entry-card-badge">編集中</span>}
            </div>
            <p className="entry-card-text">{entry.content}</p>
          </div>
        );
      })}
    </>
  );
}
