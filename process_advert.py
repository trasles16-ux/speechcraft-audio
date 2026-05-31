"""
Rejuven8Me Audio Ad Processing Script
Pure pedalboard pipeline — no pydub conversion in the chain.
Run from c:\python\breath_smoothing\ directory:
  python process_advert.py
"""

import os
import numpy as np
from pydub import AudioSegment
import pedalboard
from pedalboard import Pedalboard

INPUT_FILE = r"C:\Users\trace\Documents\REAPER Media\Advert.wav"
OUTPUT_FILE = r"C:\Users\trace\Documents\REAPER Media\Advert_clean.wav"

def load_wav(path):
    """Load WAV as float32 numpy array (channels, samples), sample rate."""
    seg = AudioSegment.from_file(path)
    sr = seg.frame_rate
    channels = seg.channels
    samples = np.array(seg.get_array_of_samples()).astype(np.float32)
    max_val = float(1 << (8 * seg.sample_width - 1))
    samples = samples / max_val
    # Shape: (channels, samples) — pedalboard expects this
    samples = samples.reshape((-1, channels)).T
    return samples, sr, len(seg) / 1000.0, seg.channels, seg.sample_width

def save_wav(samples, sr, out_path, channels, sample_width):
    """Save float32 numpy array (channels, samples) as WAV."""
    # Pad to ensure divisible by (channels * sample_width)
    frame_size = channels * sample_width
    total_samples = samples.shape[1]
    pad_len = (frame_size - total_samples % frame_size) % frame_size
    if pad_len:
        samples = np.pad(samples, ((0, 0), (0, pad_len)), mode='constant', constant_values=0)

    max_val = float(1 << (8 * sample_width - 1))
    out = (samples.T.flatten() * (max_val - 1)).astype(np.int16)
    seg = AudioSegment(
        data=out.tobytes(),
        sample_width=sample_width,
        frame_rate=sr,
        channels=channels
    )
    seg.export(out_path, format="wav")

def main():
    print(f"Loading: {INPUT_FILE}")
    samples, sr, orig_dur, channels, sw = load_wav(INPUT_FILE)
    print(f"Duration: {orig_dur:.1f}s, Sample rate: {sr}, Channels: {channels}")
    print(f"Sample shape: {samples.shape}, dtype: {samples.dtype}")

    print("Step 1/4: Breath Smoothing (pydub)...")
    # Reconstruct AudioSegment for breath_smoothing
    max_val = float(1 << (8 * sw - 1))
    seg_data = (samples.T.flatten() * (max_val - 1)).astype(np.int16).tobytes()
    seg = AudioSegment(data=seg_data, sample_width=sw, frame_rate=sr, channels=channels)
    import breath_smoothing as bs
    temp1 = r"C:\Users\trace\Documents\REAPER Media\advert_temp1.wav"
    bs.process_file(INPUT_FILE, temp1, reduction_db=6, rms_thresh=0.02, dry_wet=1.0)
    samples, sr, dur1, channels, sw = load_wav(temp1)
    print(f"  Breath smoothing done. Duration: {dur1:.1f}s, shape: {samples.shape}")

    print("Step 2/4: Normalize...")
    peak = np.max(np.abs(samples))
    target_db = -1.0
    target_linear = 10 ** (target_db / 20.0)
    gain_db = 20 * np.log10(target_linear / peak)
    norm_board = Pedalboard([pedalboard.Gain(gain_db=gain_db)])
    samples = norm_board(samples, sr)
    print(f"  Peak after normalize: {np.max(np.abs(samples)):.4f} (linear), {20*np.log10(np.max(np.abs(samples))):.1f} dBFS")

    print("Step 3/4: Noise Gate...")
    gate_board = Pedalboard([pedalboard.NoiseGate(threshold_db=-40.0)])
    samples = gate_board(samples, sr)
    print(f"  After noise gate: {20*np.log10(np.max(np.abs(samples))):.1f} dBFS")

    print("Step 4/4: Compressor...")
    comp_board = Pedalboard([
        pedalboard.Compressor(threshold_db=-20.0, ratio=4.0, attack_ms=5.0, release_ms=50.0),
        pedalboard.Gain(gain_db=6.0)
    ])
    samples = comp_board(samples, sr)
    print(f"  After compressor: {20*np.log10(np.max(np.abs(samples))):.1f} dBFS")

    # Clip to valid range
    samples = np.clip(samples, -1.0, 1.0)
    dur_out = samples.shape[1] / sr
    print(f"  Final duration: {dur_out:.1f}s")

    print(f"Exporting: {OUTPUT_FILE}")
    save_wav(samples, sr, OUTPUT_FILE, channels, sw)

    size = os.path.getsize(OUTPUT_FILE)
    print(f"\nDone! Output: {OUTPUT_FILE} ({size/1024/1024:.1f} MB)")
    print(f"Duration: {dur_out:.1f}s (original: {orig_dur:.1f}s)")

    try:
        os.remove(temp1)
    except Exception:
        pass

if __name__ == "__main__":
    main()