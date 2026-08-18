import { useRef, useState } from "react";
import type { Message } from "@ag-ui/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PaperList, type PaperListResult } from "./PaperList";
import { useChatAgent } from "./useChatAgent";

const LIST_PAPERS_TOOL_NAME = "list_papers";

function messageText(message: Message): string {
  if (typeof message.content === "string") {
    return message.content;
  }
  return "";
}

/**
 * assistant メッセージが list_papers を呼んでいれば、対応する tool メッセージの
 * 結果(JSON文字列)を messages 配列から探して構造化データとして返す。
 * pydantic-ai の AG-UI アダプタは list/dict のツール結果を JSON 文字列化して
 * ToolMessage.content に乗せるため、JSON.parse するだけで良い。
 */
function findPaperListResults(message: Message, allMessages: readonly Message[]): PaperListResult[] {
  if (message.role !== "assistant" || !message.toolCalls) {
    return [];
  }
  const results: PaperListResult[] = [];
  for (const call of message.toolCalls) {
    if (call.function.name !== LIST_PAPERS_TOOL_NAME) {
      continue;
    }
    const toolMessage = allMessages.find((m) => m.role === "tool" && m.toolCallId === call.id);
    if (!toolMessage || typeof toolMessage.content !== "string") {
      continue;
    }
    try {
      results.push(JSON.parse(toolMessage.content) as PaperListResult);
    } catch {
      // ツール結果が期待した形式でなければ無視する(壊れた表示より何も出さない方が良い)
    }
  }
  return results;
}

const TEXTAREA_MAX_HEIGHT_PX = 200;

function autoResize(el: HTMLTextAreaElement) {
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, TEXTAREA_MAX_HEIGHT_PX)}px`;
}

export default function App() {
  const { messages, isRunning, status, error, sendMessage } = useChatAgent();
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className="app">
      <header>
        <h1>Polaris</h1>
        <p>arXiv の URL を貼ると論文を保存します。「保存した論文は?」で一覧を確認できます。</p>
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
              {findPaperListResults(message, messages).map((result, i) => (
                // 同一メッセージ内で list_papers を複数回呼ぶことは想定していないが、
                // 念のため index も key に含めて一意にしておく。
                <PaperList key={`${message.id}-${i}`} papers={result.papers} total_count={result.total_count} />
              ))}
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

      <form className="composer" onSubmit={handleSubmit}>
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(event) => {
            setInput(event.target.value);
            autoResize(event.target);
          }}
          onKeyDown={handleKeyDown}
          placeholder="arXiv の URL を貼るか、質問を入力…(Shift+Enter で改行)"
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
