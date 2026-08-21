import type { Message } from "@ag-ui/client";
import { HttpAgent } from "@ag-ui/client";
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * crypto.randomUUID() はセキュアコンテキスト(HTTPS または localhost)専用で、
 * LAN IP への http:// アクセスでは使えない。getRandomValues はその制限が無いので
 * それを使って UUID v4 を組み立てる。
 */
function randomId(): string {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`;
}

// ツール呼び出し中に何をしているか分かるように、既知のツール名を日本語ラベルに変換する。
const TOOL_STATUS_LABELS: Record<string, string> = {
  save_paper: "論文を保存中…(PDF取得・要約・Embedding生成)",
  list_papers: "論文一覧を取得中…",
  get_paper_full_text: "論文の全文を読み込み中…",
};

function toolStatusLabel(toolCallName: string): string {
  return TOOL_STATUS_LABELS[toolCallName] ?? `${toolCallName} を実行中…`;
}

interface ProgressResponse {
  lines: string[];
}

/**
 * AG-UI の HttpAgent をラップし、React から使いやすい形で公開するフック。
 * バックエンドは Vite の dev proxy 経由で /api/chat に接続する(同一オリジン扱い)。
 */
export function useChatAgent() {
  const agentRef = useRef<HttpAgent | null>(null);
  if (agentRef.current === null) {
    agentRef.current = new HttpAgent({ url: "/api/chat" });
  }
  const agent = agentRef.current;

  const [messages, setMessages] = useState<readonly Message[]>(agent.messages);
  const [isRunning, setIsRunning] = useState(false);
  // 要約生成とEmbedding生成が並行して走るため、状態表示は単一の文字列ではなく
  // 複数行(0件のこともある)として扱う。
  const [status, setStatus] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isRunning) {
      return;
    }
    // /api/chat の AG-UI ストリームとは別チャネルだが、ポーリングではなく SSE で
    // push してもらう(サーバー側の `/api/progress/stream` 参照)。
    const source = new EventSource("/api/progress/stream");
    source.onmessage = (event: MessageEvent<string>) => {
      const data = JSON.parse(event.data) as ProgressResponse;
      // 行が無い間(まだ具体的な進捗段階に来ていない等)は、
      // ツール呼び出しイベント側が既に設定した状態表示を上書きしない。
      if (data.lines.length > 0) {
        setStatus(data.lines);
      }
    };
    return () => source.close();
  }, [isRunning]);

  const sendMessage = useCallback(
    async (content: string) => {
      setError(null);
      agent.addMessage({
        id: randomId(),
        role: "user",
        content,
      });
      setMessages([...agent.messages]);

      setIsRunning(true);
      setStatus(["考え中…"]);
      try {
        await agent.runAgent(
          {},
          {
            onMessagesChanged: ({ messages: updated }) => {
              setMessages([...updated]);
            },
            onToolCallStartEvent: ({ event }) => {
              setStatus([toolStatusLabel(event.toolCallName)]);
            },
            onTextMessageStartEvent: () => {
              // 実際のテキストが流れ始めたら、それ自体が最新状況を示すので状態表示は消す。
              setStatus([]);
            },
            onRunErrorEvent: ({ event }) => {
              setError(event.message);
            },
          },
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setIsRunning(false);
        setStatus([]);
      }
    },
    [agent],
  );

  return { messages, isRunning, status, error, sendMessage };
}
