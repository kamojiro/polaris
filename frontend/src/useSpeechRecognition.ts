import { useCallback, useEffect, useRef, useState } from "react";

// Web Speech API(SpeechRecognition)は標準のlib.dom.d.tsに型が無く、対応ブラウザも
// prefix付き(`webkitSpeechRecognition`)のことが多い。Chrome前提(2026-09-13時点、
// Safariは挙動が異なるため対象外)の最小限の型だけをここで宣言する。

interface SpeechRecognitionResultLike {
  transcript: string;
}

interface SpeechRecognitionEventLike extends Event {
  results: ArrayLike<ArrayLike<SpeechRecognitionResultLike>>;
}

interface SpeechRecognitionLike extends EventTarget {
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

function getSpeechRecognitionCtor(): (new () => SpeechRecognitionLike) | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  return window.SpeechRecognition ?? window.webkitSpeechRecognition;
}

/**
 * Web Speech APIによる音声入力(Chrome前提)。1回の発話を認識してテキスト化する。
 * 継続的な逐次認識(interimResults)はせず、発話が終わったタイミングでまとめて
 * `onResult`を呼ぶ単純な方式にしている(チャットの入力欄への差し込み用途にはこれで十分)。
 *
 * `start()`は結果の宛先を1回分だけ差し替える`overrideOnResult`を受け取れる
 * (026-voice-input Stage 1.5: ウェイクワード検知起動時はフック既定の「入力欄に差し込む」
 * ではなく「そのまま送信する」に切り替えるため。手動のマイクボタン(`toggle`)は
 * 常に既定の`onResult`を使う)。
 */
export function useSpeechRecognition(onResult: (text: string) => void) {
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;
  const overrideOnResultRef = useRef<((text: string) => void) | null>(null);

  const isSupported = getSpeechRecognitionCtor() !== undefined;

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const start = useCallback((overrideOnResult?: (text: string) => void) => {
    const Ctor = getSpeechRecognitionCtor();
    if (Ctor === undefined || recognitionRef.current !== null) {
      return;
    }
    overrideOnResultRef.current = overrideOnResult ?? null;
    const recognition = new Ctor();
    recognition.lang = "ja-JP";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript ?? "")
        .join("");
      if (transcript.trim() !== "") {
        (overrideOnResultRef.current ?? onResultRef.current)(transcript);
      }
    };
    recognition.onerror = () => {
      recognitionRef.current = null;
      setIsListening(false);
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      setIsListening(false);
    };
    recognitionRef.current = recognition;
    setIsListening(true);
    recognition.start();
  }, []);

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
