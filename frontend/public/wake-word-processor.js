// ウェイクワード検知(026-voice-input Stage 1.5)用のAudioWorkletProcessor。
//
// マイクの生音声(128サンプルずつ`process()`に渡ってくる)を、バックエンドの
// WAKE_WORD__CHUNK_SECONDS(既定0.4秒)ぶんのサンプル数まで溜めてから、
// float32 [-1, 1] を int16 PCM に変換してメインスレッドへ送る。`src/`の外(tscの
// 型チェック対象外)に置き、`AudioContext.audioWorklet.addModule()`から直接読み込む。

const SAMPLE_RATE = 16000;
const CHUNK_SECONDS = 0.4;
const CHUNK_SAMPLES = Math.round(SAMPLE_RATE * CHUNK_SECONDS);

class WakeWordProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Float32Array(CHUNK_SAMPLES);
    this._offset = 0;
  }

  process(inputs) {
    const channelData = inputs[0]?.[0];
    if (!channelData) {
      return true;
    }

    let readOffset = 0;
    while (readOffset < channelData.length) {
      const remaining = CHUNK_SAMPLES - this._offset;
      const toCopy = Math.min(remaining, channelData.length - readOffset);
      this._buffer.set(channelData.subarray(readOffset, readOffset + toCopy), this._offset);
      this._offset += toCopy;
      readOffset += toCopy;

      if (this._offset === CHUNK_SAMPLES) {
        const int16 = new Int16Array(CHUNK_SAMPLES);
        for (let i = 0; i < CHUNK_SAMPLES; i++) {
          const clamped = Math.max(-1, Math.min(1, this._buffer[i]));
          int16[i] = clamped < 0 ? clamped * 32768 : clamped * 32767;
        }
        this.port.postMessage(int16.buffer, [int16.buffer]);
        this._offset = 0;
      }
    }

    return true;
  }
}

registerProcessor("wake-word-processor", WakeWordProcessor);
