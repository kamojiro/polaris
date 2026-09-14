import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Polaris のチャット UI。バックエンド(FastAPI, :8000)へは同一オリジンに見せるため
// /api を Vite の dev server からプロキシする(フロント側は CORS を意識しない)。
// host: true で LAN 上の別デバイスからもアクセスできるようにする
// (プロキシ先は常にこのマシン上の localhost:8000 なので、アクセス元デバイスに関係なく機能する)。

// LAN上の別デバイス(スマホ等)からアクセスする場合、getUserMedia()はセキュアコンテキスト
// (HTTPS or localhost)でないと使えない(026-voice-input Stage 1.5のウェイクワード検知・
// Web Speech APIのマイク利用に必須)。mkcert等で発行したLAN IP向け証明書をリポジトリ直下の
// `cert/`(.gitignore対象、個人用の秘密鍵を含むためコミットしない)に置いてあれば、devサーバーを
// HTTPS化する。証明書が無い環境(別の開発者のマシン等)でも `vite`/`npm run build` 自体は
// 壊れないよう、存在チェックしてから有効化する(無ければ従来通りHTTPで動く)。
const certDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "cert");
const keyPath = path.join(certDir, "192.168.0.20+1-key.pem");
const certPath = path.join(certDir, "192.168.0.20+1.pem");
const httpsOptions =
  fs.existsSync(keyPath) && fs.existsSync(certPath)
    ? { key: fs.readFileSync(keyPath), cert: fs.readFileSync(certPath) }
    : undefined;

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    https: httpsOptions,
    proxy: {
      // ws: true が無いと /api/wake-word/stream (026-voice-input Stage 1.5) の
      // WebSocket Upgrade が中継されない。
      "/api": { target: "http://localhost:8000", ws: true },
    },
  },
});
