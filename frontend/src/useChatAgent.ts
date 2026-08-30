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
  exit_paper_mode: "論文モードを終了中…",
  web_search: "Webを検索中…",
};

function toolStatusLabel(toolCallName: string): string {
  return TOOL_STATUS_LABELS[toolCallName] ?? `${toolCallName} を実行中…`;
}

interface ProgressResponse {
  lines: string[];
}

/**
 * チャットの会話状態(論文モードは015拡張、日記モードは019拡張)。バックエンドの
 * `ChatUIState`(chat_agent.py)とフィールド名を揃えている。AG-UI の state 機構
 * (RunAgentInput.state ⇄ StateSnapshotEvent)で毎ターン自動的にサーバー↔クライアント間を
 * 往復する。`active_paper`(エンティティ紐付き型)と`diary_mode`(姿勢型)は独立したフィールドで、
 * 両者は排他ではなく共存できる。
 */
export interface ActivePaper {
  item_id: string;
  title: string;
}

export interface ChatUIState {
  active_paper: ActivePaper | null;
  diary_mode: boolean;
}

const INITIAL_CHAT_UI_STATE: ChatUIState = { active_paper: null, diary_mode: false };

/**
 * 1ターン(agent.run 1回分、内部で複数回のLLMリクエストがあれば合算済み)のトークン使用量・
 * コスト。バックエンドの `_emit_usage_event`(api/app.py)が AG-UI の CUSTOM イベントとして
 * 送ってくる `RunUsage` の値をそのまま受け取る。
 */
export interface TurnUsage {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number | null;
  cost_jpy: number | null;
}

const ZERO_USAGE: TurnUsage = {
  input_tokens: 0,
  output_tokens: 0,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  cost_usd: 0,
  cost_jpy: 0,
};

/**
 * 1回のtool呼び出しにかかった実行時間。バックエンドの`_tool_call_durations`
 * (api/app.py)が`ToolCallPart`/`ToolReturnPart`のtimestamp差分から算出したもの。
 */
export interface ToolTiming {
  tool_name: string;
  duration_seconds: number;
}

function addUsage(a: TurnUsage, b: TurnUsage): TurnUsage {
  return {
    input_tokens: a.input_tokens + b.input_tokens,
    output_tokens: a.output_tokens + b.output_tokens,
    cache_read_tokens: a.cache_read_tokens + b.cache_read_tokens,
    cache_write_tokens: a.cache_write_tokens + b.cache_write_tokens,
    cost_usd: a.cost_usd !== null && b.cost_usd !== null ? a.cost_usd + b.cost_usd : null,
    cost_jpy: a.cost_jpy !== null && b.cost_jpy !== null ? a.cost_jpy + b.cost_jpy : null,
  };
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
  const [usageByMessageId, setUsageByMessageId] = useState<Record<string, TurnUsage>>({});
  const [totalUsage, setTotalUsage] = useState<TurnUsage>(ZERO_USAGE);
  const [timingsByMessageId, setTimingsByMessageId] = useState<Record<string, ToolTiming[]>>({});
  const [uiState, setUiState] = useState<ChatUIState>(INITIAL_CHAT_UI_STATE);

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
            onCustomEvent: ({ event, messages: snapshotMessages }) => {
              const lastMessage = snapshotMessages[snapshotMessages.length - 1];
              if (event.name === "usage") {
                const usage = event.value as TurnUsage;
                if (lastMessage) {
                  setUsageByMessageId((prev) => ({ ...prev, [lastMessage.id]: usage }));
                }
                setTotalUsage((prev) => addUsage(prev, usage));
              } else if (event.name === "tool_timings") {
                const timings = event.value as ToolTiming[];
                if (lastMessage) {
                  setTimingsByMessageId((prev) => ({ ...prev, [lastMessage.id]: timings }));
                }
              }
            },
          },
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setIsRunning(false);
        setStatus([]);
        // agent.state は STATE_SNAPSHOT イベント受信時点で既に更新済み(run完了を
        // 待つ processApplyEvents の中で同期的に適用される)。onStateSnapshotEvent
        // サブスクライバの state 引数は更新「前」の値を渡す実装だったため使わず、
        // run完了後にここで直接読む。
        const state = agent.state as Partial<ChatUIState> | undefined;
        setUiState({ active_paper: state?.active_paper ?? null, diary_mode: state?.diary_mode ?? false });
      }
    },
    [agent],
  );

  const exitPaperMode = useCallback(() => {
    // LLMのターンを挟まず、クライアント側から即座にstateを書き換える。
    // 次回送信時に RunAgentInput.state として自動的にサーバーへ送られる。
    // diary_mode は独立したフィールドなので、論文モードの終了では変更しない(FR-006、両モードは排他ではない)。
    setUiState((prev) => {
      const next: ChatUIState = { active_paper: null, diary_mode: prev.diary_mode };
      agent.setState(next);
      return next;
    });
  }, [agent]);

  const toggleDiaryMode = useCallback(() => {
    // 論文モードと同じく、LLMのターンを挟まずクライアント側から即座に切り替える(019-diary-domain)。
    setUiState((prev) => {
      const next: ChatUIState = { active_paper: prev.active_paper, diary_mode: !prev.diary_mode };
      agent.setState(next);
      return next;
    });
  }, [agent]);

  return {
    messages,
    isRunning,
    status,
    error,
    sendMessage,
    usageByMessageId,
    totalUsage,
    timingsByMessageId,
    uiState,
    exitPaperMode,
    toggleDiaryMode,
  };
}
