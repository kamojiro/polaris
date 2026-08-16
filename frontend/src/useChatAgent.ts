import type { Message } from "@ag-ui/client";
import { HttpAgent } from "@ag-ui/client";
import { useCallback, useRef, useState } from "react";

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
  const [error, setError] = useState<string | null>(null);

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
      try {
        await agent.runAgent(
          {},
          {
            onMessagesChanged: ({ messages: updated }) => {
              setMessages([...updated]);
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
      }
    },
    [agent],
  );

  return { messages, isRunning, error, sendMessage };
}
