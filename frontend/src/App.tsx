import { useRef, useState } from "react";
import type { Message } from "@ag-ui/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { DailySummaryBanner } from "./DailySummaryBanner";
import { MemoryHousekeepingBanner } from "./MemoryHousekeepingBanner";
import { PaperResearchBanner } from "./PaperResearchBanner";
import { PaperResearchHistoryModal } from "./PaperResearchHistoryModal";
import { PaperResearchList } from "./PaperResearchList";
import { DiaryPanel } from "./DiaryPanel";
import { IrList, type IrListResult } from "./IrList";
import { NewsList, type NewsListResult } from "./NewsList";
import { DiscordSidebar, type SidebarDiscordItem } from "./DiscordSidebar";
import { NewsSidebar, type SidebarNewsItem } from "./NewsSidebar";
import { PaperList, type PaperListResult } from "./PaperList";
import { Sidebar } from "./Sidebar";
import { TodoList, type TodoListResult } from "./TodoList";
import { type ToolTiming, type TurnUsage, useChatAgent } from "./useChatAgent";
import { useSpeechRecognition } from "./useSpeechRecognition";

const LIST_PAPERS_TOOL_NAME = "list_papers";
const LIST_TODOS_TOOL_NAME = "list_todos";
const LIST_NEWS_TOOL_NAME = "list_news";
const LIST_IR_DOCUMENTS_TOOL_NAME = "list_ir_documents";

function messageText(message: Message): string {
  if (typeof message.content === "string") {
    return message.content;
  }
  return "";
}

/**
 * assistant メッセージが指定した名前のツールを呼んでいれば、対応する tool メッセージの
 * 結果(JSON文字列)を messages 配列から探して構造化データとして返す。
 * pydantic-ai の AG-UI アダプタは list/dict のツール結果を JSON 文字列化して
 * ToolMessage.content に乗せるため、JSON.parse するだけで良い(list_papers/list_todos共通)。
 */
function findToolResults<T>(toolName: string, message: Message, allMessages: readonly Message[]): T[] {
  if (message.role !== "assistant" || !message.toolCalls) {
    return [];
  }
  const results: T[] = [];
  for (const call of message.toolCalls) {
    if (call.function.name !== toolName) {
      continue;
    }
    const toolMessage = allMessages.find((m) => m.role === "tool" && m.toolCallId === call.id);
    if (!toolMessage || typeof toolMessage.content !== "string") {
      continue;
    }
    try {
      results.push(JSON.parse(toolMessage.content) as T);
    } catch {
      // ツール結果が期待した形式でなければ無視する(壊れた表示より何も出さない方が良い)
    }
  }
  return results;
}

/**
 * トークン使用量・コストの表示用フォーマット。cache_read_tokens は
 * (015-paper-qa-chatで実測した通り)不安定にしか効かないため、0件のときは表示自体を省略する。
 */
function formatUsageLine(usage: TurnUsage): string {
  const parts = [`入力 ${usage.input_tokens.toLocaleString()}`, `出力 ${usage.output_tokens.toLocaleString()}`];
  if (usage.cache_read_tokens > 0) {
    parts.push(`キャッシュ読込 ${usage.cache_read_tokens.toLocaleString()}`);
  }
  const costPart =
    usage.cost_jpy !== null && usage.cost_usd !== null
      ? ` · ¥${usage.cost_jpy.toFixed(2)} ($${usage.cost_usd.toFixed(4)})`
      : "";
  return `${parts.join(" / ")}${costPart}`;
}

/**
 * tool呼び出しごとの所要時間の表示用フォーマット(例: "web_search 2.1s / save_paper 8.4s")。
 * どのtoolが遅かったか一目でわかるようにする(「実行が遅かった」原因調査で毎回ログの
 * タイムスタンプを手で見比べていた反省から追加、api/app.py の `_tool_call_durations` 参照)。
 */
function formatTimingsLine(timings: ToolTiming[]): string {
  return timings.map((t) => `${t.tool_name} ${t.duration_seconds.toFixed(1)}s`).join(" / ");
}

/**
 * `navigator.clipboard`はセキュアコンテキスト(HTTPSまたはlocalhost)でのみ使える。
 * `vite.config.ts`の`server.host: true`はLAN上の別デバイス(スマホ等)からのアクセスを
 * 意図的に許可しており、その経路は平文HTTPになるため`navigator.clipboard`が
 * 存在しない(コピーボタンを押しても何も起きないように見える不具合の原因、2026-08-31)。
 * 非セキュアコンテキストでも動く`document.execCommand("copy")`(非推奨だが後方互換用に
 * 現行ブラウザもまだ実装している)にフォールバックする。
 */
async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // セキュアコンテキストでも権限拒否等で失敗しうるため、フォールバックへ続行する。
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  let succeeded = false;
  try {
    succeeded = document.execCommand("copy");
  } catch {
    succeeded = false;
  }
  document.body.removeChild(textarea);
  return succeeded;
}

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  const handleCopy = async () => {
    const succeeded = await copyText(text);
    setState(succeeded ? "copied" : "failed");
    setTimeout(() => setState("idle"), 1500);
  };

  const label = state === "copied" ? "コピーしました" : state === "failed" ? "コピーに失敗しました" : "メッセージをコピー";

  return (
    <button type="button" className="copy-button" onClick={() => void handleCopy()} aria-label={label} title={label}>
      {state === "copied" ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      ) : state === "failed" ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="9" y="9" width="13" height="13" rx="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
    </button>
  );
}

const TEXTAREA_MAX_HEIGHT_PX = 200;

function autoResize(el: HTMLTextAreaElement) {
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, TEXTAREA_MAX_HEIGHT_PX)}px`;
}

interface UploadResponse {
  upload_id: string;
  filename: string;
}

export default function App() {
  const {
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
    diaryEntries,
  } = useChatAgent();
  const [input, setInput] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isPaperResearchHistoryOpen, setIsPaperResearchHistoryOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // IME変換確定のEnterで誤送信しないためのフラグ。event.nativeEvent.isComposing だけだと
  // Safari で compositionend 直後の keydown でも true になり損ねることがあるため、
  // compositionstart/compositionend でも独自に追跡して二重にガードする。
  const isComposingRef = useRef(false);

  // 音声入力(Web Speech API、Chrome前提)。認識結果を入力欄に差し込むだけで、
  // 送信するかどうかは他の入力方法と同じくユーザーの明示的な送信操作に委ねる。
  const { isSupported: isSpeechSupported, isListening, toggle: toggleListening } = useSpeechRecognition(
    (transcript) => {
      setInput((prev) => (prev.trim() === "" ? transcript : `${prev} ${transcript}`));
      requestAnimationFrame(() => {
        if (textareaRef.current) {
          autoResize(textareaRef.current);
          textareaRef.current.focus();
        }
      });
    },
  );

  const handleToggleDiaryMode = () => {
    toggleDiaryMode();
    // トグル直後にそのままメッセージを打ち始められるよう、入力欄へフォーカスを移す。
    textareaRef.current?.focus();
  };

  const submit = () => {
    const text = input.trim();
    if (text === "" || isRunning) {
      return;
    }
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    void sendMessage(text);
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    submit();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !isComposingRef.current) {
      event.preventDefault();
      submit();
    }
  };

  // 014-paper-url-pdf-ingest: ローカルPDFはまず /api/papers/upload に保存だけしてもらい、
  // 返ってきた upload_id を通常のチャットメッセージとして送る。こうすると save_paper
  // ツール経由の既存の導線(進捗SSE・チャット履歴・一覧更新)がそのまま使える。
  const handleFileSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = ""; // 同じファイルを連続選択しても onChange が発火するようにする
    if (!file || isRunning || isUploading) {
      return;
    }
    setUploadError(null);
    setIsUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/papers/upload", { method: "POST", body: formData });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(body?.detail ?? `アップロードに失敗しました(status=${res.status})`);
      }
      const { upload_id: uploadId, filename } = (await res.json()) as UploadResponse;
      void sendMessage(`「${filename}」を保存して (upload://${uploadId})`);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsUploading(false);
    }
  };

  const handleSelectSidebarNews = (item: SidebarNewsItem) => {
    // URLの前後を全角括弧で囲むと、remark-gfm のオートリンクが閉じ括弧までURLに
    // 含めてしまう(末尾が「）」のURLになる)ため、半角スペース区切りにする。
    void sendMessage(`「${item.title}」について詳しく教えて ${item.source_url}`);
  };

  const handleSelectDiscordMessage = (item: SidebarDiscordItem) => {
    void sendMessage(`このDiscordメッセージについて詳しく教えて: ${item.content}`);
  };

  return (
    <div className="app-layout">
      <div className="app">
        <header>
          <h1>Polaris</h1>
          <p>
            arXiv/PDFのURLを貼るか📎でPDFをアップロードすると論文を保存します。TODOも「明日までに〇〇したい」のように話しかけると追加できます。「保存した論文は?」「TODO一覧見せて」で一覧を確認できます。
          </p>
          {totalUsage.input_tokens > 0 && (
            <p className="usage-total">この会話の使用量: {formatUsageLine(totalUsage)}</p>
          )}
        </header>

        <main className="messages">
          {messages
            .filter((message) => message.role === "user" || message.role === "assistant")
            .map((message) => (
              <div key={message.id} className="message-group">
                {messageText(message) !== "" && (
                  <>
                    <div className={`bubble bubble-${message.role}`}>
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{messageText(message)}</ReactMarkdown>
                    </div>
                    <div className={`message-actions message-actions-${message.role}`}>
                      <CopyButton text={messageText(message)} />
                    </div>
                  </>
                )}
                {findToolResults<PaperListResult>(LIST_PAPERS_TOOL_NAME, message, messages).map((result, i) => (
                  // 同一メッセージ内で同じツールを複数回呼ぶことは想定していないが、
                  // 念のため index も key に含めて一意にしておく。
                  <PaperList
                    key={`${message.id}-papers-${i}`}
                    papers={result.papers}
                    total_count={result.total_count}
                    onSelectPaper={(title) => void sendMessage(`『${title}』について教えて`)}
                  />
                ))}
                {findToolResults<TodoListResult>(LIST_TODOS_TOOL_NAME, message, messages).map((result, i) => (
                  <TodoList key={`${message.id}-todos-${i}`} todos={result.todos} />
                ))}
                {findToolResults<NewsListResult>(LIST_NEWS_TOOL_NAME, message, messages).map((result, i) => (
                  <NewsList key={`${message.id}-news-${i}`} news={result.news} />
                ))}
                {findToolResults<IrListResult>(LIST_IR_DOCUMENTS_TOOL_NAME, message, messages).map((result, i) => (
                  <IrList
                    key={`${message.id}-ir-${i}`}
                    documents={result.documents}
                    total_count={result.total_count}
                  />
                ))}
                {message.role === "assistant" && timingsByMessageId[message.id]?.length > 0 && (
                  <p className="usage-line">{formatTimingsLine(timingsByMessageId[message.id])}</p>
                )}
                {message.role === "assistant" && usageByMessageId[message.id] && (
                  <p className="usage-line">{formatUsageLine(usageByMessageId[message.id])}</p>
                )}
              </div>
            ))}
          {isRunning && (
            <div className="bubble bubble-assistant bubble-pending">
              {status.length > 0
                ? status.map((line) => <div key={line}>{line}</div>)
                : "…"}
            </div>
          )}
        </main>

        <DailySummaryBanner />
        <MemoryHousekeepingBanner />
        <PaperResearchBanner />

        {error !== null && <div className="error">{error}</div>}
        {uploadError !== null && <div className="error">{uploadError}</div>}

        {(uiState.active_paper !== null || uiState.diary_mode) && (
          <div className="mode-chips">
            {uiState.active_paper !== null && (
              <div className="paper-mode-badge">
                <span>📄 読書中: {uiState.active_paper.title}</span>
                <button type="button" onClick={exitPaperMode} title="論文モードを終了">
                  ✕
                </button>
              </div>
            )}
            {uiState.diary_mode && (
              <div className="diary-mode-badge">
                <span>📔 日記モード</span>
                <button type="button" onClick={handleToggleDiaryMode} title="日記モードを終了">
                  ✕
                </button>
              </div>
            )}
          </div>
        )}

        <form className="composer" onSubmit={handleSubmit}>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            hidden
            onChange={(event) => void handleFileSelected(event)}
          />
          <button
            type="button"
            className="attach"
            disabled={isRunning || isUploading}
            onClick={() => fileInputRef.current?.click()}
            title="PDFをアップロードして保存"
          >
            {isUploading ? "…" : "📎"}
          </button>
          <button
            type="button"
            className="quick-action"
            disabled={isRunning}
            onClick={() => void sendMessage("論文一覧ちょうだい")}
            title="論文一覧を表示"
          >
            📚
          </button>
          <button
            type="button"
            className={uiState.diary_mode ? "diary-mode-toggle diary-mode-toggle-active" : "diary-mode-toggle"}
            aria-pressed={uiState.diary_mode}
            onClick={handleToggleDiaryMode}
            title={uiState.diary_mode ? "日記モードを終了" : "日記モードを開始"}
          >
            📔
          </button>
          {isSpeechSupported && (
            <button
              type="button"
              className={isListening ? "mic-button mic-button-active" : "mic-button"}
              aria-pressed={isListening}
              disabled={isRunning}
              onClick={toggleListening}
              title={isListening ? "音声入力を停止" : "音声入力を開始"}
            >
              {isListening ? "⏹️" : "🎙️"}
            </button>
          )}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(event) => {
              setInput(event.target.value);
              autoResize(event.target);
            }}
            onKeyDown={handleKeyDown}
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={() => {
              isComposingRef.current = false;
            }}
            placeholder="arXiv の URL / PDFの直リンクを貼るか、質問を入力…(Shift+Enter で改行)"
            rows={1}
            disabled={isRunning}
          />
          <button type="submit" disabled={isRunning || input.trim() === ""}>
            送信
          </button>
        </form>
      </div>

      <Sidebar wide={uiState.diary_mode}>
        <NewsSidebar onSelect={handleSelectSidebarNews} />
        <DiscordSidebar onSelect={handleSelectDiscordMessage} />
        <PaperResearchList onOpenHistory={() => setIsPaperResearchHistoryOpen(true)} />
        {uiState.diary_mode && <DiaryPanel entries={diaryEntries} />}
      </Sidebar>

      {isPaperResearchHistoryOpen && (
        <PaperResearchHistoryModal onClose={() => setIsPaperResearchHistoryOpen(false)} />
      )}
    </div>
  );
}
