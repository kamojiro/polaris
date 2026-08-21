import { useRef, useState } from "react";
import type { Message } from "@ag-ui/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PaperList, type PaperListResult } from "./PaperList";
import { TodoList, type TodoListResult } from "./TodoList";
import { type TurnUsage, useChatAgent } from "./useChatAgent";

const LIST_PAPERS_TOOL_NAME = "list_papers";
const LIST_TODOS_TOOL_NAME = "list_todos";

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
  const { messages, isRunning, status, error, sendMessage, usageByMessageId, totalUsage } = useChatAgent();
  const [input, setInput] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // IME変換確定のEnterで誤送信しないためのフラグ。event.nativeEvent.isComposing だけだと
  // Safari で compositionend 直後の keydown でも true になり損ねることがあるため、
  // compositionstart/compositionend でも独自に追跡して二重にガードする。
  const isComposingRef = useRef(false);

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

  return (
    <div className="app">
      <header>
        <h1>Polaris</h1>
        <p>
          arXiv/PDFのURLを貼るか📎でPDFをアップロードすると論文を保存します。TODOも「明日までに〇〇したい」のように話しかけると追加できます。「保存した論文は?」「TODO一覧見せて」で一覧を確認できます。
        </p>
        {totalUsage.input_tokens > 0 && <p className="usage-total">この会話の使用量: {formatUsageLine(totalUsage)}</p>}
      </header>

      <main className="messages">
        {messages
          .filter((message) => message.role === "user" || message.role === "assistant")
          .map((message) => (
            <div key={message.id} className="message-group">
              {messageText(message) !== "" && (
                <div className={`bubble bubble-${message.role}`}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{messageText(message)}</ReactMarkdown>
                </div>
              )}
              {findToolResults<PaperListResult>(LIST_PAPERS_TOOL_NAME, message, messages).map((result, i) => (
                // 同一メッセージ内で同じツールを複数回呼ぶことは想定していないが、
                // 念のため index も key に含めて一意にしておく。
                <PaperList key={`${message.id}-papers-${i}`} papers={result.papers} total_count={result.total_count} />
              ))}
              {findToolResults<TodoListResult>(LIST_TODOS_TOOL_NAME, message, messages).map((result, i) => (
                <TodoList key={`${message.id}-todos-${i}`} todos={result.todos} />
              ))}
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

      {error !== null && <div className="error">{error}</div>}
      {uploadError !== null && <div className="error">{uploadError}</div>}

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
  );
}
