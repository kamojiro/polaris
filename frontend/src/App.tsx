import { useState } from "react";
import type { Message } from "@ag-ui/client";
import { useChatAgent } from "./useChatAgent";

function messageText(message: Message): string {
  if (typeof message.content === "string") {
    return message.content;
  }
  return "";
}

export default function App() {
  const { messages, isRunning, error, sendMessage } = useChatAgent();
  const [input, setInput] = useState("");

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const text = input.trim();
    if (text === "" || isRunning) {
      return;
    }
    setInput("");
    void sendMessage(text);
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
            <div key={message.id} className={`bubble bubble-${message.role}`}>
              {messageText(message)}
            </div>
          ))}
        {isRunning && <div className="bubble bubble-assistant bubble-pending">…</div>}
      </main>

      {error !== null && <div className="error">{error}</div>}

      <form className="composer" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="arXiv の URL を貼るか、質問を入力…"
          disabled={isRunning}
        />
        <button type="submit" disabled={isRunning || input.trim() === ""}>
          送信
        </button>
      </form>
    </div>
  );
}
