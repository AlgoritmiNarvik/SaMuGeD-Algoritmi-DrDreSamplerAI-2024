"""Check browser WAV encoding against exact signed PCM sample values."""
import json
from pathlib import Path
import shutil
import subprocess
import wave

import pytest


def test_browser_wav_encoder_preserves_pcm24_samples(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the browser WAV encoder")
    encoder = Path(__file__).resolve().parents[1] / "scripts/loop_downloads.js"
    samples = [-8388608, -4194304, -1, 0, 1, 4194304, 8388607]
    output = tmp_path / "download.wav"
    script = """
const {encodePcm24Wav} = require(process.argv[1]);
const fs = require('node:fs');
const values = JSON.parse(process.argv[3]);
const buffer = {
  numberOfChannels: 2, sampleRate: 48000, length: values.length,
  getChannelData: c => Float32Array.from(c ? [...values].reverse() : values, n => n / 8388608)
};
fs.writeFileSync(process.argv[2], Buffer.from(encodePcm24Wav(buffer)));
"""
    subprocess.run([node, "-e", script, str(encoder), str(output), json.dumps(samples)], check=True)
    with wave.open(str(output)) as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (2, 3, 48000)
        expected = b"".join(n.to_bytes(3, "little", signed=True) for pair in zip(samples, reversed(samples)) for n in pair)
        assert audio.readframes(audio.getnframes()) == expected
