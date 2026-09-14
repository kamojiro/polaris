// composerのアイコン(003-chat-ui-polish、2026-09-14のアイコン整理)。
// 新規パッケージを入れずインラインSVGで済ませる方針(既存の.copy-buttonアイコンと同じ、
// App.tsx参照)。パスは`specs/003-chat-ui-polish/composer-mockup.html`(実装用モックアップ、
// 過去に文章のみの指示で実装した際に見た目がズレた反省から作られた)のものをそのまま使う。

interface IconProps {
  className?: string;
}

const ICON_SIZE = 18;

/** 音声ボタン本体(常に同じ形、状態は配色で示す)。展開メニューでは使わない。 */
export function WaveformIcon({ className }: IconProps) {
  return (
    <svg
      width={ICON_SIZE}
      height={ICON_SIZE}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      className={className}
    >
      <path d="M12 3v2M12 19v2M6 8v8M18 8v8M9 5v14M15 5v14" />
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
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3z" />
      <path d="M19 11a7 7 0 0 1-14 0" />
    </svg>
  );
}

/** 展開メニューの「常時待受」(ウェイクワード)項目用。中心の点から信号が広がる形。 */
export function BroadcastIcon({ className }: IconProps) {
  return (
    <svg
      width={ICON_SIZE}
      height={ICON_SIZE}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      className={className}
    >
      <circle cx="12" cy="12" r="2" />
      <path d="M12 5v-2M12 21v-2M5 12h-2M21 12h-2M7.5 7.5l-1.4-1.4M17.9 17.9l-1.4-1.4M7.5 16.5l-1.4 1.4M17.9 6.1l-1.4 1.4" />
    </svg>
  );
}

/** 展開メニューを開くシェブロン(塗りつぶしの小さな三角形)。 */
export function ChevronIcon({ className }: IconProps) {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M7 10l5 5 5-5z" />
    </svg>
  );
}
