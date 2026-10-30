// Browser audio helpers for device names and the wizard's microphone check.
// The core records through sounddevice; names from the webview are close enough to match on.

export async function listAudioDevices(kind: MediaDeviceKind): Promise<string[]> {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const names = devices
      .filter((d) => d.kind === kind && d.label && d.deviceId !== "default")
      .map((d) => d.label);
    return [...new Set(names)];
  } catch {
    return [];
  }
}

/** Peak level of a block of samples in 0..1. */
export function peakLevel(samples: ArrayLike<number>): number {
  let peak = 0;
  for (let i = 0; i < samples.length; i++) peak = Math.max(peak, Math.abs(samples[i] ?? 0));
  return Math.min(1, peak);
}

/** Calls onLevel ~30 times a second with the microphone level. Resolves to a stop function. */
export async function watchMicLevel(onLevel: (level: number) => void): Promise<() => void> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const context = new AudioContext();
  const analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  context.createMediaStreamSource(stream).connect(analyser);
  const buffer = new Float32Array(analyser.fftSize);
  let frame = 0;
  const tick = () => {
    analyser.getFloatTimeDomainData(buffer);
    onLevel(peakLevel(buffer));
    frame = requestAnimationFrame(tick);
  };
  tick();
  return () => {
    cancelAnimationFrame(frame);
    stream.getTracks().forEach((track) => track.stop());
    void context.close();
  };
}
