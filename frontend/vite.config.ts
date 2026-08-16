import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Polaris のチャット UI。バックエンド(FastAPI, :8000)へは同一オリジンに見せるため
// /api を Vite の dev server からプロキシする(フロント側は CORS を意識しない)。
// host: true で LAN 上の別デバイスからもアクセスできるようにする
// (プロキシ先は常にこのマシン上の localhost:8000 なので、アクセス元デバイスに関係なく機能する)。
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
