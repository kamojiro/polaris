import { useCallback, useEffect, useRef, useState } from "react";

// Web Speech API(SpeechRecognition)は標準のlib.dom.d.tsに型が無く、対応ブラウザも
// prefix付き(`webkitSpeechRecognition`)のことが多い。Chrome前提(2026-09-13時点、
// Safariは挙動が異なるため対象外)の最小限の型だけをここで宣言する。

interface SpeechRecognitionAlternativeLike {
  transcript: string;
}

// `results[i]`(1発話ぶん)。`isFinal`はcontinuous:trueのセッションで「確定済みか」を示す
// (`useAmbientVoice.ts`が`resultIndex`と合わせてバッファリングに使う)。
export interface SpeechRecognitionResultLike extends ArrayLike<SpeechRecognitionAlternativeLike> {
  isFinal: boolean;
}

export interface SpeechRecognitionEventLike extends Event {
  // continuous:trueのセッションで、このイベントから新規に確定・更新された結果の開始位置。
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}

export interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: Event) => void) | null;
  onend: (() => void) | null;
}

declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  }
}

// `useAmbientVoice.ts`(026-voice-input Stage2代替案)も同じWeb Speech API型を使うため、
// `declare global`のWindow拡張を2箇所に書いて型の不整合を起こさないよう、ここでexportして
// 再利用する。
export function getSpeechRecognitionCtor(): (new () => SpeechRecognitionLike) | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  return window.SpeechRecognition ?? window.webkitSpeechRecognition;
}

// ウェイクワード(ハンズフリー)モードで、最後の認識イベントからこの時間だけ無音が
// 続いたら発話が終わったとみなす(026-voice-input「長文発話が途中で送信されてしまう」
// 対応、2026-09-15)。Chromeの非continuousセッションは内部の発話終了判定が敏感で、
// 息継ぎ程度の間でもセッション自体を終えてしまうため、continuous+interimResultsで
// セッションを継続させつつ、この無音タイマーで「発話の終わり」を自前判定する
// (簡易VAD。026 spec Stage2の本格的なVADとはスコープが異なる、録音終了判定専用)。
const HANDS_FREE_SILENCE_TIMEOUT_MS = 1200;

interface StartOptions {
  /** 結果の宛先を1回分だけ差し替える(既定は入力欄への差し込み)。 */
  onResult?: (text: string) => void;
  /** trueならcontinuous+interimResultsで動かし、無音区間の検出で発話終了を判定する。 */
  handsFree?: boolean;
}

/**
 * Web Speech APIによる音声入力(Chrome前提)。1回の発話を認識してテキスト化する。
 *
 * 既定(`handsFree`未指定、手動マイクボタン用)は継続的な逐次認識をせず、Chrome自身が
 * 発話終了と判定したタイミングでまとめて`onResult`を呼ぶ単純な方式(チャットの入力欄への
 * 差し込み用途にはこれで十分)。`handsFree: true`(ウェイクワード検知起動時)は
 * continuous+interimResultsで動かし、無音タイマーで自前に発話終了を判定する
 * (Chromeの非continuousセッションだと長い発話が息継ぎで打ち切られるため)。
 *
 * `start()`は結果の宛先を1回分だけ差し替える`onResult`を受け取れる(026-voice-input
 * Stage 1.5: ウェイクワード検知起動時はフック既定の「入力欄に差し込む」ではなく
 * 呼び出し側が指定するコールバックに切り替えるため。手動のマイクボタン(`toggle`)は
 * 常に既定の`onResult`を使う)。
 */
export function useSpeechRecognition(onResult: (text: string) => void) {
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;
  const overrideOnResultRef = useRef<((text: string) => void) | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isSupported = getSpeechRecognitionCtor() !== undefined;

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current !== null) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    clearSilenceTimer();
    recognitionRef.current?.stop();
  }, [clearSilenceTimer]);

  const start = useCallback(
    (options?: StartOptions) => {
      const Ctor = getSpeechRecognitionCtor();
      if (Ctor === undefined || recognitionRef.current !== null) {
        return;
      }
      const handsFree = options?.handsFree ?? false;
      overrideOnResultRef.current = options?.onResult ?? null;
      const recognition = new Ctor();
      recognition.lang = "ja-JP";
      recognition.continuous = handsFree;
      recognition.interimResults = handsFree;

      let latestTranscript = "";
      const finalize = () => {
        clearSilenceTimer();
        const transcript = latestTranscript.trim();
        if (transcript !== "") {
          (overrideOnResultRef.current ?? onResultRef.current)(transcript);
        }
        recognition.stop();
      };

      recognition.onresult = (event) => {
        const transcript = Array.from(event.results)
          .map((result) => result[0]?.transcript ?? "")
          .join("");
        latestTranscript = transcript;
        if (!handsFree) {
          if (transcript.trim() !== "") {
            (overrideOnResultRef.current ?? onResultRef.current)(transcript);
          }
          return;
        }
        // 発話が続いている間はイベントが来るたびタイマーを延長し、無音が
        // HANDS_FREE_SILENCE_TIMEOUT_MS続いたら発話終了とみなして確定する。
        clearSilenceTimer();
        silenceTimerRef.current = setTimeout(finalize, HANDS_FREE_SILENCE_TIMEOUT_MS);
      };
      recognition.onerror = () => {
        clearSilenceTimer();
        recognitionRef.current = null;
        setIsListening(false);
      };
      recognition.onend = () => {
        clearSilenceTimer();
        recognitionRef.current = null;
        setIsListening(false);
      };
      recognitionRef.current = recognition;
      setIsListening(true);
      recognition.start();
    },
    [clearSilenceTimer],
  );

  const toggle = useCallback(() => {
    if (recognitionRef.current !== null) {
      stop();
    } else {
      start();
    }
  }, [start, stop]);

  useEffect(() => stop, [stop]);

  return { isSupported, isListening, toggle, start };
}
