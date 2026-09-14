// composerのアイコン(003-chat-ui-polish、2026-09-14のアイコン整理)。
// 新規パッケージを入れずインラインSVGで済ませる方針(既存の.copy-buttonアイコンと同じ、
// App.tsx参照)。線幅・viewBoxもそれに揃えている。

interface IconProps {
  className?: string;
}

const ICON_SIZE = 18;

export function PlusIcon({ className }: IconProps) {
  return (
    <svg
      width={ICON_SIZE}
      height={ICON_SIZE}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
    >
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

/** 音声ボタン本体(常時「話す」「常時待受」共通、状態は配色で示す)。 */
export function WaveformIcon({ className }: IconProps) {
  return (
    <svg
      width={ICON_SIZE}
      height={ICON_SIZE}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
    >
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  );
}

/** 展開メニューの「話す」(プッシュトゥトーク)項目用。 */
export function MicLineIcon({ className }: IconProps) {
  return (
    <svg
      width={ICON_SIZE}
      height={ICON_SIZE}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
    >
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );
}

/** 展開メニューの「常時待受」(ウェイクワード)項目用。耳アイコンは「聞いている」以上の
 * 意味が伝わらないため不採用(003 spec参照)、音波の広がりで表す。 */
export function BroadcastIcon({ className }: IconProps) {
  return (
    <svg
      width={ICON_SIZE}
      height={ICON_SIZE}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
    >
      <path d="M5 12.55a11 11 0 0 1 14.08 0" />
      <path d="M1.42 9a16 16 0 0 1 21.16 0" />
      <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
      <circle cx="12" cy="20" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}
