/** Complete PCM16 WAV contract shared with magi_plugin_sdk.audio. */
export const MAX_AUDIO_BYTES = 2 * 1024 * 1024;
export const MAX_AUDIO_SECONDS = 60;
export const CAPTURE_SAMPLE_RATE = 16_000;

export type AudioErrorCode =
  | 'unsupported' | 'permission_denied' | 'no_microphone' | 'device_unavailable'
  | 'empty_recording' | 'capture_failed' | 'invalid_audio' | 'queue_full'
  | 'sequence_error' | 'playback_blocked' | 'recording_active' | 'playback_failed';

export class AudioIOError extends Error {
  constructor(readonly code: AudioErrorCode, message: string) {
    super(message);
    this.name = 'AudioIOError';
  }
}

export function audioError(reason: unknown, code: AudioErrorCode): AudioIOError {
  if (reason instanceof AudioIOError) return reason;
  if (reason instanceof DOMException) {
    if (reason.name === 'NotAllowedError' || reason.name === 'SecurityError') {
      return new AudioIOError('permission_denied', 'Microphone permission was denied');
    }
    if (reason.name === 'NotFoundError') return new AudioIOError('no_microphone', 'No microphone is available');
    if (reason.name === 'NotReadableError') return new AudioIOError('device_unavailable', 'Microphone is unavailable');
  }
  return new AudioIOError(code, reason instanceof Error ? reason.message : 'Audio operation failed');
}

function invalid(): never {
  throw new AudioIOError('invalid_audio', 'Audio must be a complete bounded PCM16 WAV file');
}

export function inspectWav(bytes: ArrayBuffer): { sampleRate: number; channels: number; frames: number } {
  if (bytes.byteLength < 44 || bytes.byteLength > MAX_AUDIO_BYTES) invalid();
  const view = new DataView(bytes);
  const tag = (at: number) => String.fromCharCode(...new Uint8Array(bytes, at, 4));
  if (tag(0) !== 'RIFF' || tag(8) !== 'WAVE' || view.getUint32(4, true) + 8 !== bytes.byteLength) invalid();
  let rate = 0;
  let channels = 0;
  let dataSize = 0;
  let foundFormat = false;
  let foundData = false;
  for (let offset = 12; offset < bytes.byteLength;) {
    if (offset + 8 > bytes.byteLength) invalid();
    const kind = tag(offset);
    const size = view.getUint32(offset + 4, true);
    const next = offset + 8 + size + (size % 2);
    if (next > bytes.byteLength) invalid();
    if (kind === 'fmt ') {
      if (foundFormat || size < 16 || view.getUint16(offset + 8, true) !== 1) invalid();
      channels = view.getUint16(offset + 10, true);
      rate = view.getUint32(offset + 12, true);
      if (view.getUint16(offset + 22, true) !== 16) invalid();
      if (view.getUint16(offset + 20, true) !== channels * 2) invalid();
      if (view.getUint32(offset + 16, true) !== rate * channels * 2) invalid();
      foundFormat = true;
    }
    if (kind === 'data') {
      if (!foundFormat || foundData) invalid();
      dataSize = size;
      foundData = true;
    }
    offset = next;
  }
  if (!foundFormat || !foundData || ![1, 2].includes(channels) || rate < 8000 || rate > 96000) invalid();
  const frames = dataSize / (channels * 2);
  if (!Number.isInteger(frames) || frames <= 0 || frames > rate * MAX_AUDIO_SECONDS) invalid();
  return { sampleRate: rate, channels, frames };
}

export function encodeMonoWav(samples: Float32Array, rate = CAPTURE_SAMPLE_RATE): ArrayBuffer {
  if (samples.length === 0) throw new AudioIOError('empty_recording', 'No audio samples were captured');
  if (!Number.isInteger(rate) || rate < 8000 || rate > 96000
    || samples.length > rate * MAX_AUDIO_SECONDS || samples.length * 2 + 44 > MAX_AUDIO_BYTES) invalid();
  const bytes = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(bytes);
  const writeTag = (offset: number, tag: string) => {
    for (let i = 0; i < tag.length; i += 1) view.setUint8(offset + i, tag.charCodeAt(i));
  };
  writeTag(0, 'RIFF'); view.setUint32(4, bytes.byteLength - 8, true);
  writeTag(8, 'WAVE'); writeTag(12, 'fmt '); view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  writeTag(36, 'data'); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i += 1) {
    if (!Number.isFinite(samples[i])) invalid();
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
  }
  return bytes;
}

/** Filter at the source rate before resampling: browser resampling alone may alias. */
export async function normalizeRecording(samples: Float32Array, sourceRate: number): Promise<ArrayBuffer> {
  if (sourceRate === CAPTURE_SAMPLE_RATE) return encodeMonoWav(samples);
  if (!samples.length) throw new AudioIOError('empty_recording', 'No audio samples were captured');
  if (!Number.isFinite(sourceRate) || sourceRate < 8000 || sourceRate > 96000
    || samples.length > sourceRate * MAX_AUDIO_SECONDS) invalid();
  let filtered = samples;
  if (sourceRate > CAPTURE_SAMPLE_RATE) {
    const filterContext = new OfflineAudioContext(1, samples.length, sourceRate);
    const input = filterContext.createBuffer(1, samples.length, sourceRate);
    input.getChannelData(0).set(samples);
    const source = filterContext.createBufferSource();
    source.buffer = input;
    let previous: AudioNode = source;
    // Eight-pole Butterworth low-pass, leaving a transition band below 8 kHz.
    for (const q of [0.50979558, 0.60134489, 0.89997622, 2.56291545]) {
      const filter = filterContext.createBiquadFilter();
      filter.type = 'lowpass';
      filter.frequency.value = 6400;
      // Web Audio expresses low-pass Q in decibels, not as the linear factor.
      filter.Q.value = 20 * Math.log10(q);
      previous.connect(filter);
      previous = filter;
    }
    previous.connect(filterContext.destination);
    source.start();
    filtered = (await filterContext.startRendering()).getChannelData(0);
  }
  const length = Math.ceil(samples.length * CAPTURE_SAMPLE_RATE / sourceRate);
  const offline = new OfflineAudioContext(1, length, CAPTURE_SAMPLE_RATE);
  const input = offline.createBuffer(1, samples.length, sourceRate);
  input.getChannelData(0).set(filtered);
  const source = offline.createBufferSource();
  source.buffer = input;
  source.connect(offline.destination);
  source.start();
  const rendered = await offline.startRendering();
  return encodeMonoWav(rendered.getChannelData(0));
}
