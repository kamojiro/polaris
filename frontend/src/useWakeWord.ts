import { useCallback, useEffect, useRef, useState } from "react";

// AudioWorkletNode/AudioContextの型はDOM libに含まれるが、`audioWorklet.addModule()`が
// 返すPromiseの型は環境によって揺れるため、ここでは標準DOM型をそのまま使う。

const WAKE_WORD_SAMPLE_RATE = 16000;

function buildWebSocketUrl(path: string): string {
  const url = new URL(path, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

interface UseWakeWordOptions {
  /** ハンズフリートグルのON/OFF(App側が持つ状態をそのまま渡す)。 */
  enabled: boolean;
  /** ウェイクワード検知時のコールバック(呼ばれる直前に内部のWS・マイクは完全に停止済み)。 */
  onDetected: () => void;
}

/**
 * ウェイクワード検知(026-voice-input Stage 1.5)。マイク音声を0.4秒チャンクに切り出し、
 * バックエンドの `/api/wake-word/stream` へWebSocket経由で送り続け、検知イベントを待つ。
 *
 * 検知後は自前のWS・マイクを`stop()`で完全に解放してから`onDetected`を呼ぶ
 * (Web Speech APIと同時にマイクを掴むと不安定なため、切り替え時は必ず片方を
 * 完全に手放す設計、`specs/026-voice-input/spec.draft.md`参照)。`onDetected`側の処理
 * (Web Speech APIでの1発話認識)が終わったあとの待ち受け再開は、呼び出し元が
 * `enabled`を維持したまま`rearm()`を呼ぶことで行う(`enabled`自体は変化しないため
 * 内部のuseEffectだけでは再接続が起きない)。
 */
export function useWakeWord({ enabled, onDetected }: UseWakeWordOptions) {
  const [isAvailable, setIsAvailable] = useState(false);
  const [isArmed, setIsArmed] = useState(false);
  const onDetectedRef = useRef(onDetected);
  onDetectedRef.current = onDetected;

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/wake-word/enabled")
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

  const stop = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    workletNodeRef.current?.port.close();
    workletNodeRef.current?.disconnect();
    workletNodeRef.current = null;
    audioContextRef.current?.close().catch(() => {});
    audioContextRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setIsArmed(false);
  }, []);

  const connect = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const audioContext = new AudioContext({ sampleRate: WAKE_WORD_SAMPLE_RATE });
      audioContextRef.current = audioContext;
      await audioContext.audioWorklet.addModule("/wake-word-processor.js");

      const source = audioContext.createMediaStreamSource(stream);
      const workletNode = new AudioWorkletNode(audioContext, "wake-word-processor");
      workletNodeRef.current = workletNode;
      // 出力先(destination)に繋がないとブラウザによってはノードの処理が止まるため、
      // 無音のGainNode経由でdestinationへ繋いでおく(音は一切出さない)。
      const silentGain = audioContext.createGain();
      silentGain.gain.value = 0;
      source.connect(workletNode).connect(silentGain).connect(audioContext.destination);

      const ws = new WebSocket(buildWebSocketUrl("/api/wake-word/stream"));
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => setIsArmed(true);
      ws.onclose = () => setIsArmed(false);
      ws.onerror = () => {
        // 補助機能なので、エラー時は静かに待ち受け停止扱いにする(再接続はrearm任せ)。
        setIsArmed(false);
      };
      ws.onmessage = (event) => {
        if (typeof event.data !== "string") {
          return;
        }
        try {
          const data = JSON.parse(event.data) as { type?: string };
          if (data.type === "detected") {
            stop();
            onDetectedRef.current();
          }
        } catch {
          // 想定外のメッセージは無視する。
        }
      };

      workletNode.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(event.data);
        }
      };
    } catch {
      // マイク拒否・AudioWorklet未対応等。補助機能なので静かに諦める。
      stop();
    }
  }, [stop]);

  useEffect(() => {
    if (enabled) {
      void connect();
    } else {
      stop();
    }
    return () => stop();
  }, [enabled, connect, stop]);

  return { isAvailable, isArmed, rearm: connect };
}
