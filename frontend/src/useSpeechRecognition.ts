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
 */
export function useSpeechRecognition(onResult: (text: string) => void) {
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;

  const isSupported = getSpeechRecognitionCtor() !== undefined;

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Ctor = getSpeechRecognitionCtor();
    if (Ctor === undefined || recognitionRef.current !== null) {
      return;
    }
    const recognition = new Ctor();
    recognition.lang = "ja-JP";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript ?? "")
        .join("");
      if (transcript.trim() !== "") {
        onResultRef.current(transcript);
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

  return { isSupported, isListening, toggle };
}
