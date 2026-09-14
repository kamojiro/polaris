import { useEffect, useRef, useState } from "react";
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
import { useWakeWord } from "./useWakeWord";
import { BroadcastIcon, MicLineIcon, PlusIcon, WaveformIcon } from "./icons";

const HANDS_FREE_PLACEHOLDER = "『かもも』と話しかけてください…";
const DEFAULT_PLACEHOLDER = "arXiv の URL / PDFの直リンクを貼るか、質問を入力…(Shift+Enter で改行)";

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
  // composerのアイコン整理(003 spec、2026-09-14): 📎📚📔を「+」1個の展開メニューへ、
  // 🎙️👂を波形アイコン1個+シェブロン展開メニューへ集約する。
  const [isAttachMenuOpen, setIsAttachMenuOpen] = useState(false);
  const [isVoiceMenuOpen, setIsVoiceMenuOpen] = useState(false);
  const attachMenuRef = useRef<HTMLDivElement>(null);
  const voiceMenuRef = useRef<HTMLDivElement>(null);
  // IME変換確定のEnterで誤送信しないためのフラグ。event.nativeEvent.isComposing だけだと
  // Safari で compositionend 直後の keydown でも true になり損ねることがあるため、
  // compositionstart/compositionend でも独自に追跡して二重にガードする。
  const isComposingRef = useRef(false);

  // 音声入力(Web Speech API、Chrome前提)。手動のマイクボタン経由では認識結果を
  // 入力欄に差し込むだけで、送信するかどうかは他の入力方法と同じくユーザーの
  // 明示的な送信操作に委ねる。
  const { isSupported: isSpeechSupported, isListening, toggle: toggleListening, start: startListening } =
    useSpeechRecognition((transcript) => {
      setInput((prev) => (prev.trim() === "" ? transcript : `${prev} ${transcript}`));
      requestAnimationFrame(() => {
        if (textareaRef.current) {
          autoResize(textareaRef.current);
          textareaRef.current.focus();
        }
      });
    });

  // ウェイクワード検知(026-voice-input Stage 1.5)。検知したら手動マイクボタンとは
  // 別経路で認識を自動起動し、結果は入力欄に差し込まず直接送信する(真のハンズフリー)。
  // 認識セッション終了後は、ハンズフリーモードがまだONならウェイクワード待ち受けを
  // 再開する(下のuseEffect参照、rearmWakeWordはuseWakeWordが公開するconnect相当)。
  //
  // isRunningによる二重ガード(実機検証で発見: 応答が返ってくる前に2通連続で送信される
  // 不具合の対策、2026-09-14)。手動マイクボタンは`disabled={isRunning}`で自然にガードが
  // 効くが、ウェイクワードは常時リスニング+検知トリガーの構造上そうならない:
  // 1つ目は下のuseEffectで、認識セッション終了(`isListening`)だけでなくエージェントの
  // 応答完了(`isRunning`)も待ってから待ち受けを再開することで、「1通目の応答待ち中に
  // 2回目の検知→2通目を送信してしまう」レースを防ぐ。2つ目は`onDetected`自身で、
  // 何らかの理由でisRunning中に検知イベントが届いても新しいターンを開始せず
  // 待ち受けだけ再開する(defense in depth、本質的な直し方は1つ目)。
  const [isHandsFreeEnabled, setIsHandsFreeEnabled] = useState(false);
  const pendingRearmRef = useRef(false);
  const { isAvailable: isWakeWordAvailable, isArmed: isWakeWordArmed, rearm: rearmWakeWord } = useWakeWord({
    enabled: isHandsFreeEnabled,
    onDetected: () => {
      if (isRunning) {
        void rearmWakeWord();
        return;
      }
      pendingRearmRef.current = true;
      startListening((transcript) => {
        void sendMessage(transcript);
      });
    },
  });

  useEffect(() => {
    if (!isListening && !isRunning && pendingRearmRef.current) {
      pendingRearmRef.current = false;
      if (isHandsFreeEnabled) {
        void rearmWakeWord();
      }
    }
  }, [isListening, isRunning, isHandsFreeEnabled, rearmWakeWord]);

  // composerの展開メニュー(+/音声)を、外側クリックまたはEscapeで閉じる。
  useEffect(() => {
    if (!isAttachMenuOpen && !isVoiceMenuOpen) {
      return;
    }
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (attachMenuRef.current && !attachMenuRef.current.contains(target)) {
        setIsAttachMenuOpen(false);
      }
      if (voiceMenuRef.current && !voiceMenuRef.current.contains(target)) {
        setIsVoiceMenuOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsAttachMenuOpen(false);
        setIsVoiceMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isAttachMenuOpen, isVoiceMenuOpen]);

  const handleVoiceButtonClick = () => {
    if (isHandsFreeEnabled) {
      // 常時待受モード中にメインボタンを押したら、常時待受を終了してアイドルに戻る
      // (003 spec「トグルオフ挙動」決定)。
      setIsHandsFreeEnabled(false);
      return;
    }
    toggleListening();
  };

  const handleSelectPushToTalk = () => {
    setIsVoiceMenuOpen(false);
    if (isHandsFreeEnabled) {
      setIsHandsFreeEnabled(false);
    }
    if (!isListening) {
      toggleListening();
    }
  };

  const handleSelectHandsFree = () => {
    setIsVoiceMenuOpen(false);
    if (isListening) {
      toggleListening();
    }
    setIsHandsFreeEnabled(true);
  };

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

        {(uiState.active_paper !== null || uiState.diary_mode || isHandsFreeEnabled) && (
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
            {isHandsFreeEnabled && (
              <div className="hands-free-badge">
                <span>
                  {isListening
                    ? "🎙️ 聞き取り中…(話し終えると自動送信されます)"
                    : isWakeWordArmed
                      ? "📡 常時待受中(「かもも」と話しかけてください)"
                      : "⏳ 常時待受を準備中…"}
                </span>
                <button type="button" onClick={() => setIsHandsFreeEnabled(false)} title="常時待受を終了">
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
          <div className="composer-menu-group" ref={attachMenuRef}>
            <button
              type="button"
              className="composer-plus-button"
              disabled={isRunning || isUploading}
              aria-expanded={isAttachMenuOpen}
              onClick={() => setIsAttachMenuOpen((prev) => !prev)}
              title="添付・論文一覧・日記モード"
            >
              {isUploading ? "…" : <PlusIcon />}
            </button>
            {isAttachMenuOpen && (
              <div className="composer-menu">
                <button
                  type="button"
                  onClick={() => {
                    setIsAttachMenuOpen(false);
                    fileInputRef.current?.click();
                  }}
                >
                  📎 PDFを添付
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setIsAttachMenuOpen(false);
                    void sendMessage("論文一覧ちょうだい");
                  }}
                >
                  📚 論文一覧
                </button>
                <button
                  type="button"
                  className={uiState.diary_mode ? "composer-menu-item-active" : undefined}
                  onClick={() => {
                    setIsAttachMenuOpen(false);
                    handleToggleDiaryMode();
                  }}
                >
                  📔 {uiState.diary_mode ? "日記モードを終了" : "日記モードを開始"}
                </button>
              </div>
            )}
          </div>
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
            placeholder={isHandsFreeEnabled ? HANDS_FREE_PLACEHOLDER : DEFAULT_PLACEHOLDER}
            rows={1}
            disabled={isRunning}
          />
          {isSpeechSupported && (
            <div className="composer-menu-group" ref={voiceMenuRef}>
              <button
                type="button"
                className={
                  isHandsFreeEnabled
                    ? "composer-voice-button composer-voice-button-handsfree"
                    : isListening
                      ? "composer-voice-button composer-voice-button-listening"
                      : "composer-voice-button"
                }
                aria-pressed={isListening || isHandsFreeEnabled}
                disabled={isRunning}
                onClick={handleVoiceButtonClick}
                title={
                  isHandsFreeEnabled
                    ? isWakeWordArmed
                      ? "常時待受を終了(ウェイクワード待ち受け中)"
                      : "常時待受を終了"
                    : isListening
                      ? "音声入力を停止"
                      : "音声入力を開始"
                }
              >
                <WaveformIcon />
              </button>
              {isWakeWordAvailable && (
                <button
                  type="button"
                  className="composer-voice-chevron"
                  disabled={isRunning}
                  aria-expanded={isVoiceMenuOpen}
                  onClick={() => setIsVoiceMenuOpen((prev) => !prev)}
                  title="音声入力の方式を選ぶ"
                >
                  ▾
                </button>
              )}
              {isVoiceMenuOpen && (
                <div className="composer-menu composer-menu-right">
                  <button type="button" className="composer-menu-item-speak" onClick={handleSelectPushToTalk}>
                    <MicLineIcon /> 話す
                  </button>
                  <button type="button" onClick={handleSelectHandsFree}>
                    <BroadcastIcon /> 常時待受
                  </button>
                </div>
              )}
            </div>
          )}
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
