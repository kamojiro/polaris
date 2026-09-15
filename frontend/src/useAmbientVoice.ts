import { useCallback, useEffect, useRef, useState } from "react";
import { getSpeechRecognitionCtor, type SpeechRecognitionLike } from "./useSpeechRecognition";

// クライアント側がバッファをフラッシュする間隔(ミリ秒)。バックエンドの
// settings.ambient_voice.max_wait_seconds(既定60秒)と揃える。設定値をfetchで
// 取りに行くほどの重要度ではないため、既定値をそのままハードコードする
// (ずれても実害は「フラッシュ間隔が想定よりやや長い/短い」程度)。
const FLUSH_INTERVAL_MS = 60_000;

interface UseAmbientVoiceOptions {
  /** 常時認識トグルのON/OFF(App側が持つ状態をそのまま渡す)。 */
  enabled: boolean;
}

/**
 * 常時音声認識(026-voice-input Stage2代替案)。`useWakeWord.ts`と`useSpeechRecognition.ts`の
 * 中間のような役割だが、独自VADは組まない(continuous:trueのセッションが無音区切りで
 * 発話ごとに確定結果を出す仕様をそのまま利用する、spec方針)。WebSocketも使わない
 * (Web Speech APIだけで完結する)。
 *
 * `onresult`は`resultIndex`以降の新規確定結果だけをバッファに積む(`useSpeechRecognition.ts`の
 * 「全結果を毎回joinし直す」方式とは違うので、既存フックを拡張せず新規フックにした)。
 * `FLUSH_INTERVAL_MS`ごとにバッファを結合して`POST /api/ambient-voice/chunk`へ送りクリアする。
 */
export function useAmbientVoice({ enabled }: UseAmbientVoiceOptions) {
  const [isAvailable, setIsAvailable] = useState(false);
  const [isActive, setIsActive] = useState(false);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const bufferRef = useRef<string[]>([]);
  const flushTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  useEffect(() => {
    let cancelled = false;
    fetch("/api/ambient-voice/enabled")
      .then((res) => res.json())
      .then((data: { enabled?: boolean }) => {
        if (!cancelled) {
          setIsAvailable(Boolean(data.enabled));
        }
      })
      .catch(() => {
        // 補助機能なので、確認できなければ非表示のまま静かに諦める。
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const flush = useCallback(() => {
    if (bufferRef.current.length === 0) {
      return;
    }
    const transcript = bufferRef.current.join(" ");
    bufferRef.current = [];
    void fetch("/api/ambient-voice/chunk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript }),
    }).catch(() => {
      // バックグラウンドジョブへの送信なので、失敗しても静かに諦める
      // (次のフラッシュ以降のチャンクとして送られ続けるので、この回ぶんだけ失われる)。
    });
  }, []);

  const stop = useCallback(() => {
    if (flushTimerRef.current !== null) {
      clearInterval(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    flush();
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setIsActive(false);
  }, [flush]);

  const start = useCallback(() => {
    const Ctor = getSpeechRecognitionCtor();
    if (Ctor === undefined || recognitionRef.current !== null) {
      return;
    }
    const recognition = new Ctor();
    recognition.lang = "ja-JP";
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result?.isFinal) {
          const transcript = result[0]?.transcript ?? "";
          if (transcript.trim() !== "") {
            bufferRef.current.push(transcript);
          }
        }
      }
    };
    recognition.onerror = () => {
      recognitionRef.current = null;
      setIsActive(false);
      // enabledがまだtrueなら、useEffectのenabled依存を再トリガーせずここで直接再接続する
      // (rearmはuseWakeWord同様、呼び出し元経由ではなくフック内で完結させる設計)。
      if (enabledRef.current) {
        start();
      }
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      setIsActive(false);
      if (enabledRef.current) {
        start();
      }
    };
    recognitionRef.current = recognition;
    setIsActive(true);
    recognition.start();
  }, []);

  useEffect(() => {
    if (enabled) {
      start();
      flushTimerRef.current = setInterval(flush, FLUSH_INTERVAL_MS);
    } else {
      stop();
    }
    return () => stop();
    // eslint未導入のためexhaustive-depsは効かないが、start/stop/flushはuseCallbackで
    // 安定参照(依存が空または安定した値のみ)なので、enabledの変化だけを見れば十分。
  }, [enabled, start, stop, flush]);

  return { isAvailable, isActive };
}
