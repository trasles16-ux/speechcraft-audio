"""
Breath Smoothing Module for Audio Processing

Detects breath sounds in audio and softens them while maintaining naturalness.
Uses RMS-based detection and lowpass filtering with fade crossfades.
"""

import sys
from pydub import AudioSegment
import numpy as np
from scipy.signal import butter, lfilter


def rms_frames(samples, frame_size, hop_size):
    """Calculate RMS (Root Mean Square) for audio frames.
    
    Args:
        samples: Audio samples array
        frame_size: Size of each frame in samples
        hop_size: Hop size between frames in samples
        
    Returns:
        Array of RMS values for each frame
    """
    rms = []
    for start in range(0, len(samples) - frame_size + 1, hop_size):
        frame = samples[start:start+frame_size]
        rms.append(np.sqrt(np.mean(frame.astype(np.float64)**2)))
    return np.array(rms)


def butter_lowpass(cutoff, fs, order=4):
    """Design a Butterworth lowpass filter.
    
    Args:
        cutoff: Cutoff frequency in Hz
        fs: Sampling frequency in Hz
        order: Filter order
        
    Returns:
        Tuple of (b, a) filter coefficients
    """
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    return b, a


def lowpass_filter(data, cutoff, fs, order=4):
    """Apply Butterworth lowpass filter to audio data.
    
    Args:
        data: Audio samples
        cutoff: Cutoff frequency in Hz
        fs: Sampling frequency in Hz
        order: Filter order
        
    Returns:
        Filtered audio samples
    """
    b, a = butter_lowpass(cutoff, fs, order=order)
    y = lfilter(b, a, data)
    return y


def detect_breaths(audio_seg, frame_ms=50, hop_ms=25, rms_thresh=0.02, max_duration_ms=700):
    """Detect breath regions in audio using RMS-based analysis.

    Args:
        audio_seg: AudioSegment object
        frame_ms: Frame size in milliseconds
        hop_ms: Hop size in milliseconds
        rms_thresh: RMS threshold for breath detection (normalized to 0-1).
            Higher = less sensitive (fewer detected breaths).
            Range: 0.01 (very sensitive) to 0.10 (very insensitive).
        max_duration_ms: Maximum breath duration in milliseconds.

    Returns:
        List of (start_ms, end_ms) tuples for detected breaths
    """
    samples = np.array(audio_seg.get_array_of_samples())
    if audio_seg.channels > 1:
        samples = samples.reshape((-1, audio_seg.channels)).mean(axis=1)

    fs = audio_seg.frame_rate
    frame_size = int(fs * (frame_ms / 1000.0))
    hop_size = int(fs * (hop_ms / 1000.0))

    rms = rms_frames(samples, frame_size, hop_size)

    max_rms = np.max(rms)
    if max_rms < 1e-7:
        # Audio is essentially silent — no breaths to detect
        return []
    rms = rms / max_rms

    breath_flags = rms > rms_thresh

    # aggregate contiguous frames
    breaths = []
    start = None
    for i, flag in enumerate(breath_flags):
        if flag and start is None:
            start = i
        if not flag and start is not None:
            end = i
            duration_ms = (end - start) * hop_ms
            if duration_ms <= max_duration_ms:
                breaths.append((start*hop_ms, end*hop_ms))
            start = None

    if start is not None:
        breaths.append((start*hop_ms, len(breath_flags)*hop_ms))

    return breaths


def attenuate_region(seg, start_ms, end_ms, reduction_db=8):
    """Attenuate a region of audio with crossfading.
    
    Args:
        seg: AudioSegment to process
        start_ms: Start position in milliseconds
        end_ms: End position in milliseconds
        reduction_db: Amount of attenuation in dB
        
    Returns:
        AudioSegment with attenuated region
    """
    segment = seg[start_ms:end_ms]
    attenuated = segment - reduction_db
    # small crossfades to mask edits
    fade = min(20, int((end_ms - start_ms) / 4))
    attenuated = attenuated.fade_in(fade).fade_out(fade)
    return seg[:start_ms] + attenuated + seg[end_ms:]


def process_file(in_path, out_path, reduction_db=6, rms_thresh=0.02, dry_wet=1.0):
    """Process audio file with breath smoothing.

    Detects breath regions and softens them by:
    1. Applying lowpass filter to remove harsh frequencies
    2. Reducing volume
    3. Adding fade in/out for natural transitions
    4. Blending processed audio with original based on dry_wet

    Args:
        in_path: Input audio file path
        out_path: Output audio file path
        reduction_db: Amount of volume reduction in dB (default 6).
            Higher = more reduction of breath sounds.
        rms_thresh: Breath detection sensitivity, 0.01 (very sensitive) to 0.10 (insensitive).
            Default 0.02. Lower = detect more breaths.
        dry_wet: Blend factor 0.0 to 1.0. 1.0 = fully processed (default).
            0.5 = half the reduction applied (subtle). 0.0 = no processing.
    """
    audio = AudioSegment.from_file(in_path)
    if len(audio) == 0 or audio.frame_rate == 0:
        out = audio
    else:
        breaths = detect_breaths(audio, rms_thresh=rms_thresh)
        out = audio

        # Effective reduction scaled by dry/wet
        effective_reduction = reduction_db * dry_wet

        for (s, e) in breaths:
            s = int(max(0, s))
            e = int(min(len(out), e))
            region = out[s:e]

            # Build the processed version
            samples = np.array(region.get_array_of_samples()).astype(np.float32)
            if region.channels > 1:
                samples = samples.reshape((-1, region.channels)).mean(axis=1)

            filtered = lowpass_filter(samples, cutoff=6000, fs=region.frame_rate)
            filtered_segment = region._spawn(filtered.astype(region.array_type).tobytes())
            filtered_segment = filtered_segment - effective_reduction
            filtered_segment = filtered_segment.fade_in(10).fade_out(10)

            if dry_wet >= 1.0:
                # Full wet — use processed
                out = out[:s] + filtered_segment + out[e:]
            elif dry_wet > 0.0:
                # Blend: dry = original, wet = processed
                blended = region.overlay(
                    filtered_segment,
                    gain_level1=(1.0 - dry_wet),  # reduce original by (1-dry_wet)
                    gain_level=dry_wet              # reduce processed by dry_wet
                )
                out = out[:s] + blended + out[e:]
            # dry_wet == 0.0 → skip (leave original)

    out.export(out_path, format='wav')


# Alias for backwards compatibility
def process(in_path, out_path, reduction_db=6, rms_thresh=0.02, dry_wet=1.0):
    """Alias for process_file()."""
    process_file(in_path, out_path, reduction_db=reduction_db,
                 rms_thresh=rms_thresh, dry_wet=dry_wet)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python breath_smoothing.py input.wav output.wav')
        sys.exit(2)
    in_path = sys.argv[1]
    out_path = sys.argv[2]
    process_file(in_path, out_path)
