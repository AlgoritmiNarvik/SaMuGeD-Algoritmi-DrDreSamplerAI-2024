/* Decode the lossless source at its original rate, then export PCM24 WAV. */
'use strict';
function encodePcm24Wav(buffer) {
  const channels = buffer.numberOfChannels, frames = buffer.length;
  const bytes = new ArrayBuffer(44 + frames * channels * 3), view = new DataView(bytes);
  const text = (offset, value) => [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, 'RIFF'); view.setUint32(4, bytes.byteLength - 8, true); text(8, 'WAVE');
  text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, channels, true); view.setUint32(24, buffer.sampleRate, true);
  view.setUint32(28, buffer.sampleRate * channels * 3, true);
  view.setUint16(32, channels * 3, true); view.setUint16(34, 24, true);
  text(36, 'data'); view.setUint32(40, frames * channels * 3, true);
  const planes = Array.from({length: channels}, (_, i) => buffer.getChannelData(i));
  let offset = 44;
  for (let i = 0; i < frames; i++) for (let c = 0; c < channels; c++) {
    const sample = Math.max(-8388608, Math.min(8388607, Math.round(planes[c][i] * 8388608)));
    view.setUint8(offset++, sample & 255);
    view.setUint8(offset++, (sample >> 8) & 255);
    view.setUint8(offset++, (sample >> 16) & 255);
  }
  return bytes;
}
if (typeof document !== 'undefined') document.addEventListener('click', async event => {
  const link = event.target.closest('a[data-wav-download]');
  if (!link) return;
  event.preventDefault();
  if (link.getAttribute('aria-busy') === 'true') return;
  const source = link.href, label = link.textContent;
  link.setAttribute('aria-busy', 'true'); link.textContent = 'Preparing WAV…';
  try {
    const response = await fetch(source);
    if (!response.ok) throw new Error('Audio download failed');
    const context = new OfflineAudioContext(2, 1, 48000);
    const buffer = await context.decodeAudioData(await response.arrayBuffer());
    if (buffer.sampleRate !== 48000 || buffer.numberOfChannels !== 2) throw new Error('Unexpected audio format');
    const url = URL.createObjectURL(new Blob([encodePcm24Wav(buffer)], {type: 'audio/wav'}));
    const download = document.createElement('a'); download.href = url;
    download.download = new URL(source).pathname.split('/').at(-2) + '.wav';
    document.body.append(download); download.click(); download.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) {
    const status = document.getElementById('status');
    if (status) status.textContent = 'WAV could not be prepared. Try again or download FLAC.';
  } finally {
    link.textContent = label; link.removeAttribute('aria-busy');
  }
});
if (typeof module !== 'undefined') module.exports = {encodePcm24Wav};
