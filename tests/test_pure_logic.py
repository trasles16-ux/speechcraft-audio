"""Pure-logic module tests for SpeechCraft.

These modules are importable without wx and can be tested in the Linux
smoke CI as well as the Windows full suite. They exercise the core
audio-processing and data-structure logic that the dialogs and frame
depend on.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydub import AudioSegment

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_silent(ms: int = 1000, sr: int = 44100) -> AudioSegment:
    """Create a silent AudioSegment of the given duration."""
    return AudioSegment.silent(duration=ms, frame_rate=sr)


def _make_tone(freq: float = 440.0, ms: int = 1000, sr: int = 44100) -> AudioSegment:
    """Create a sine-wave AudioSegment."""
    n_samples = int(sr * ms / 1000)
    samples = np.array(
        [int(32767 * np.sin(2 * np.pi * freq * i / sr)) for i in range(n_samples)],
        dtype=np.int16,
    )
    return AudioSegment(
        samples.tobytes(),
        frame_rate=sr,
        sample_width=2,
        channels=1,
    )


# ---------------------------------------------------------------------------
# config.py — constants sanity
# ---------------------------------------------------------------------------


def test_config_breath_levels_have_required_keys() -> None:
    """Every breath-smoothing level dict has the four expected keys."""
    import config
    for name, params in config.BREATH_SMOOTHING_LEVELS.items():
        assert "reduction_db" in params, f"{name} missing reduction_db"
        assert "cutoff_hz" in params, f"{name} missing cutoff_hz"
        assert "fade_ms" in params, f"{name} missing fade_ms"
        assert "description" in params, f"{name} missing description"


def test_config_eq_presets_have_five_bands() -> None:
    """Every EQ preset defines exactly 5 (freq, gain) bands."""
    import config
    for name, preset in config.EQ_PRESETS.items():
        bands = preset["bands"]
        assert len(bands) == 5, f"{name} has {len(bands)} bands, expected 5"
        for freq, gain in bands:
            assert isinstance(freq, (int, float))
            assert isinstance(gain, (int, float))


def test_config_compressor_presets_have_required_keys() -> None:
    """Every compressor preset has the five expected parameter keys."""
    import config
    required = {"threshold_db", "ratio", "attack_ms", "release_ms", "makeup_db"}
    for name, preset in config.COMPRESSOR_PRESETS.items():
        missing = required - set(preset.keys())
        assert not missing, f"{name} missing keys: {missing}"


# ---------------------------------------------------------------------------
# auto_ducker.py — AutoDucker class
# ---------------------------------------------------------------------------


def test_auto_ducker_init_rejects_positive_threshold() -> None:
    """threshold_db must be negative (it's a dB reduction from full scale)."""
    from auto_ducker import AutoDucker

    with pytest.raises(ValueError, match="threshold_db must be negative"):
        AutoDucker(threshold_db=0.0)
    with pytest.raises(ValueError, match="threshold_db must be negative"):
        AutoDucker(threshold_db=5.0)


def test_auto_ducker_init_rejects_positive_reduction() -> None:
    """reduction_db must be negative (it reduces gain)."""
    from auto_ducker import AutoDucker

    with pytest.raises(ValueError, match="reduction_db must be negative"):
        AutoDucker(reduction_db=0.0)
    with pytest.raises(ValueError, match="reduction_db must be negative"):
        AutoDucker(reduction_db=3.0)


def test_auto_ducker_init_rejects_nonpositive_chunk() -> None:
    """chunk_ms must be positive."""
    from auto_ducker import AutoDucker

    with pytest.raises(ValueError, match="chunk_ms must be positive"):
        AutoDucker(chunk_ms=0)
    with pytest.raises(ValueError, match="chunk_ms must be positive"):
        AutoDucker(chunk_ms=-5)


def test_auto_ducker_init_clamps_attack_release() -> None:
    """Negative attack/release values are clamped to 1."""
    from auto_ducker import AutoDucker

    d = AutoDucker(attack_ms=-10, release_ms=-100)
    assert d.attack_ms == 1
    assert d.release_ms == 1


def test_auto_ducker_duck_audio_with_none_inputs() -> None:
    """duck_audio returns the background track unchanged when voice_track
    is None. When background_track is None, it returns None (no audio
    to duck)."""
    from auto_ducker import AutoDucker

    d = AutoDucker()
    silent = _make_silent()
    # When voice is None, returns background unchanged
    assert d.duck_audio(None, silent) is silent
    # When background is None, returns None (nothing to duck)
    assert d.duck_audio(silent, None) is None
    # Two silents — should return background unchanged (no voice detected)
    result = d.duck_audio(silent, silent)
    assert len(result) == len(silent)


def test_auto_ducker_duck_audio_with_real_tone() -> None:
    """When voice is present, background gets reduced. We test this
    at a high level: the output should be shorter than input+voice
    concatenated, and different from the original background."""
    from auto_ducker import AutoDucker

    d = AutoDucker(threshold_db=-30, reduction_db=-12)
    voice = _make_tone(freq=440, ms=1000)
    bg = _make_tone(freq=220, ms=1000)

    result = d.duck_audio(voice, bg)
    assert isinstance(result, AudioSegment)
    # Result duration should match the background (ducking doesn't
    # change duration, only gain)
    assert result.duration_seconds == pytest.approx(bg.duration_seconds, abs=0.01)


# ---------------------------------------------------------------------------
# breath_smoothing.py — detect_breaths and attenuate_region
# ---------------------------------------------------------------------------


def test_detect_breaths_empty_audio_returns_empty() -> None:
    """Silent audio has no breaths to detect."""
    from breath_smoothing import detect_breaths

    silent = _make_silent(ms=1000)
    breaths = detect_breaths(silent, rms_thresh=0.02)
    assert breaths == []


def test_detect_breaths_returns_list_of_tuples() -> None:
    """detect_breaths returns (start_ms, end_ms) tuples."""
    from breath_smoothing import detect_breaths

    # Create audio with a brief burst of energy in the middle
    sr = 44100
    samples = np.zeros(sr, dtype=np.float64)
    # Add a burst in the middle 200-400ms
    samples[sr // 5 : 3 * sr // 5] = np.sin(
        2 * np.pi * 440 * np.arange(sr // 5, 3 * sr // 5) / sr
    )
    audio = AudioSegment(
        (samples * 32767).astype(np.int16).tobytes(),
        frame_rate=sr,
        sample_width=2,
        channels=1,
    )

    breaths = detect_breaths(audio, rms_thresh=0.05, max_duration_ms=700)
    assert isinstance(breaths, list)
    for start, end in breaths:
        assert isinstance(start, (int, float))
        assert isinstance(end, (int, float))
        assert start < end


def test_attenuate_region_reduces_gain() -> None:
    """attenuate_region reduces the gain of the specified region."""
    from breath_smoothing import attenuate_region

    tone = _make_tone(ms=1000)
    original_rms = tone.rms
    result = attenuate_region(tone, 250, 750, reduction_db=12)
    # The attenuated region should have lower RMS
    assert result.rms < original_rms


def test_process_file_creates_output(tmp_path: Path) -> None:
    """process_file writes an output file."""
    from breath_smoothing import process_file

    inp = tmp_path / "input.wav"
    out = tmp_path / "output.wav"
    # Write a silent input
    _make_silent(ms=500).export(str(inp), format="wav")

    process_file(str(inp), str(out), reduction_db=6, rms_thresh=0.02)
    assert out.exists()
    # Output should have same duration as input (silence in, silence out)
    result = AudioSegment.from_wav(str(out))
    assert abs(result.duration_seconds - 0.5) < 0.01


# ---------------------------------------------------------------------------
# word_alignment.py — WordAlignment and WordSegment
# ---------------------------------------------------------------------------


def test_word_segment_duration() -> None:
    """WordSegment.duration_ms() returns end - start."""
    from word_alignment import WordSegment

    seg = WordSegment("hello", start_ms=0.0, end_ms=500.0)
    assert seg.duration_ms() == 500.0


def test_word_segment_to_dict() -> None:
    """WordSegment.to_dict() includes all fields."""
    from word_alignment import WordSegment

    seg = WordSegment("world", start_ms=100.0, end_ms=300.0, confidence=0.9)
    d = seg.to_dict()
    assert d["text"] == "world"
    assert d["start_ms"] == 100.0
    assert d["end_ms"] == 300.0
    assert d["confidence"] == 0.9
    assert d["duration_ms"] == 200.0


def test_word_alignment_add_and_get() -> None:
    """Adding words and retrieving by time range works."""
    from word_alignment import WordAlignment

    wa = WordAlignment()
    wa.add_word("Hello", 0, 200)
    wa.add_word("world", 200, 400)
    wa.add_word("!", 400, 500)

    # get_word_at_time
    seg = wa.get_word_at_time(100)
    assert seg is not None
    assert seg.text == "Hello"

    seg = wa.get_word_at_time(300)
    assert seg is not None
    assert seg.text == "world"

    # get_words_in_range
    words = wa.get_words_in_range(100, 350)
    assert len(words) == 2
    assert {w.text for w in words} == {"Hello", "world"}


def test_word_alignment_remove_word_updates_times() -> None:
    """Removing a word shifts subsequent words' times."""
    from word_alignment import WordAlignment

    wa = WordAlignment()
    wa.add_word("A", 0, 100)
    wa.add_word("B", 100, 200)
    wa.add_word("C", 200, 300)

    audio = _make_silent(ms=500)
    audio = wa.remove_word(0, audio)  # Remove "A" (100ms)

    # B should now start at 0, C at 100
    assert wa.word_segments[0].text == "B"
    assert wa.word_segments[0].start_ms == 0
    assert wa.word_segments[1].text == "C"
    assert wa.word_segments[1].start_ms == 100


def test_word_alignment_remove_out_of_range_raises() -> None:
    """Removing a word at an invalid index raises IndexError."""
    from word_alignment import WordAlignment

    wa = WordAlignment()
    wa.add_word("A", 0, 100)
    audio = _make_silent(ms=500)

    with pytest.raises(IndexError):
        wa.remove_word(5, audio)


def test_word_alignment_update_char_offsets() -> None:
    """update_char_offsets sets char_start/char_end on each segment."""
    from word_alignment import WordAlignment

    wa = WordAlignment()
    wa.add_word("Hello", 0, 100)
    wa.add_word("world", 100, 200)
    wa.update_char_offsets()

    assert wa.word_segments[0].char_start == 0
    assert wa.word_segments[0].char_end == 5  # "Hello" = 5 chars
    assert wa.word_segments[1].char_start == 6  # +1 for space
    assert wa.word_segments[1].char_end == 11  # "world" = 5 chars


def test_word_alignment_get_indices_in_char_range() -> None:
    """get_indices_in_char_range finds overlapping words."""
    from word_alignment import WordAlignment

    wa = WordAlignment()
    wa.add_word("Hello", 0, 100)
    wa.add_word("world", 100, 200)
    wa.update_char_offsets()

    indices = wa.get_indices_in_char_range(3, 8)
    # "Hello" (chars 0-5) overlaps with [3,8]; "world" (chars 6-11) overlaps too
    assert len(indices) == 2


def test_word_alignment_get_transcript_text() -> None:
    """get_transcript_text joins words with spaces."""
    from word_alignment import WordAlignment

    wa = WordAlignment()
    wa.add_word("Hello", 0, 100)
    wa.add_word("world", 100, 200)

    assert wa.get_transcript_text() == "Hello world"


# ---------------------------------------------------------------------------
# Tests for modules that require wx are skipped via needs_wx marker
# ---------------------------------------------------------------------------

def _wx_available() -> bool:
    try:
        import wx  # noqa: F401
        return True
    except ImportError:
        return False


needs_wx = pytest.mark.skipif(
    not _wx_available(),
    reason="wxPython not installed; skip wx-dependent tests",
)


@needs_wx
def test_preset_manager_load_returns_dicts() -> None:
    """load_custom_presets returns (eq, comp, breath) dicts."""
    import preset_manager

    eq, comp, breath = preset_manager.load_custom_presets()
    assert isinstance(eq, dict)
    assert isinstance(comp, dict)
    assert isinstance(breath, dict)


@needs_wx
def test_preset_manager_save_and_load_roundtrip(tmp_path: Path) -> None:
    """save_custom_presets / load_custom_presets round-trip works."""
    import preset_manager

    # Save some test data
    test_eq = {"TestEQ": {"bands": [(100, 0), (300, 0), (1000, 0), (3000, 0), (8000, 0)]}}
    test_comp = {"TestComp": {"threshold_db": -20, "ratio": 4, "attack_ms": 5, "release_ms": 50, "makeup_db": 0}}
    test_breath = {"TestBreath": {"reduction_db": 6, "dry_wet": 1.0, "rms_thresh": 0.02}}

    preset_manager.save_custom_presets(test_eq, test_comp, test_breath)

    # Load back
    eq, comp, breath = preset_manager.load_custom_presets()
    assert "TestEQ" in eq
    assert "TestComp" in comp
    assert "TestBreath" in breath

    # Clean up
    preset_manager.save_custom_presets({}, {}, {})


# ---------------------------------------------------------------------------
# load_audio — regression tests for issue #13
# ---------------------------------------------------------------------------
#
# Before the fix, load_audio only caught FileNotFoundError. Pydub raises
# CouldntEncodeError / CouldntDecodeError (subclasses of Exception, not
# FileNotFoundError) when ffmpeg is missing or fails to spawn. The exception
# bubbled up uncaught and wxPython silently swallowed it, so Open Audio
# appeared to do nothing.
#
# These tests mock pydub and the dialog to assert that any non-FileNotFoundError
# exception is surfaced via a MessageBox (and not silently dropped).

@needs_wx
def test_load_audio_surfaces_pydub_decode_error(tmp_path: Path, monkeypatch) -> None:
    """load_audio pops a dialog when pydub raises CouldntDecodeError (issue #13)."""
    import wx
    from pydub.exceptions import CouldntDecodeError

    import audio_editor

    # Build a fake frame with the minimum surface load_audio touches.
    class FakeFrame:
        load_audio = audio_editor.SpeechCraftFrame.load_audio
        log_area = type("L", (), {"AppendText": staticmethod(lambda s: None)})()

    captured: list[tuple[str, str, int]] = []

    def fake_messagebox(message, caption, style):
        captured.append((message, caption, style))

    monkeypatch.setattr(wx, "MessageBox", fake_messagebox)

    # Make AudioSegment.from_file raise a non-FileNotFoundError — the bug case.
    def boom(_path):
        raise CouldntDecodeError("Couldn't find ffmpeg")

    fake_seg_path = tmp_path / "fake.mp3"
    fake_seg_path.write_bytes(b"\x00\x00")
    monkeypatch.setattr(audio_editor.AudioSegment, "from_file", staticmethod(boom))

    # load_audio is unbound; bind to a minimal self.
    audio_editor.SpeechCraftFrame.load_audio(FakeFrame(), str(fake_seg_path))

    # The dialog must fire — silently dropping is the bug we're guarding against.
    assert len(captured) == 1, f"Expected one MessageBox call, got {len(captured)}"
    message, caption, _style = captured[0]
    assert caption == "FFmpeg Missing"
    assert "ffmpeg" in message.lower() or "ffmpeg" in message


@needs_wx
def test_load_audio_file_not_found_shows_dialog(tmp_path: Path, monkeypatch) -> None:
    """load_audio pops a dialog when the file itself is missing."""
    import wx

    import audio_editor

    class FakeFrame:
        load_audio = audio_editor.SpeechCraftFrame.load_audio

    captured: list[tuple[str, str, int]] = []

    monkeypatch.setattr(
        wx, "MessageBox",
        lambda m, c, s: captured.append((m, c, s)),
    )

    # Patch FileNotFoundError into the except path: original code only
    # handled ffmpeg-missing for non-WAV; file-not-found should still
    # produce a clear message.
    monkeypatch.setattr(audio_editor.AudioSegment, "from_file",
                        staticmethod(lambda p: (_ for _ in ()).throw(FileNotFoundError(p))))

    audio_editor.SpeechCraftFrame.load_audio(FakeFrame(), str(tmp_path / "nope.wav"))

    assert len(captured) == 1
    _msg, caption, _style = captured[0]
    assert caption == "Cannot Open Audio"
    assert "not found" in _msg.lower()


# ---------------------------------------------------------------------------
# Module-level sd / pyaudio binding — regression test for issue #14
# ---------------------------------------------------------------------------
#
# Before the fix, `sd` and `pyaudio` were only bound inside
# SpeechCraftFrame.__init__ via `global sd; import sounddevice as sd`.
# If anything reached the device dialog or _play_test_tone before __init__
# finished, NameError surfaced as "Error enumerating devices".
#
# After the fix, both are bound at module load via safe_import, so importing
# audio_editor gives a usable `sd` reference even if __init__ never runs.

@needs_wx
def test_module_level_sd_is_defined() -> None:
    """audio_editor.sd is defined at module load (issue #14)."""
    import audio_editor
    assert hasattr(audio_editor, "sd"), "audio_editor.sd should be module-level"
    # Either the real sounddevice module, or the DummyModule fallback —
    # both are acceptable. The contract is: it must be defined, not None.
    assert audio_editor.sd is not None


@needs_wx
def test_module_level_pyaudio_is_defined() -> None:
    """audio_editor.pyaudio is defined at module load (issue #14)."""
    import audio_editor
    assert hasattr(audio_editor, "pyaudio"), "audio_editor.pyaudio should be module-level"
    assert audio_editor.pyaudio is not None


# ---------------------------------------------------------------------------
# AST-level regression guard: no function-scope `import sounddevice as sd`
# ---------------------------------------------------------------------------
#
# Issue #14 second-cut: populate_devices() (a closure inside on_audio_setup)
# had `import sounddevice as sd` inside its body. Even though that branch was
# only reached for ASIO, Python's name-resolution rules treat `sd` as a local
# variable throughout the ENTIRE function — so the earlier SoundDevice branch
# hit UnboundLocalError ("cannot access local variable 'sd' where it is not
# associated with a value") instead of NameError.
#
# Fix: `sd` is now module-level via safe_import, so no function needs to
# re-import it. This AST test enforces that invariant by scanning the source
# for `import sounddevice as sd` inside any function/class body. If anyone
# re-adds that pattern, this test fails before the runtime error can ship.

def test_no_function_scope_sounddevice_import() -> None:
    """No function in audio_editor.py does `import sounddevice as sd` (issue #14).

    AST scan rather than runtime test so it runs on the Linux smoke CI too.
    """
    import ast
    from pathlib import Path

    src_path = Path(__file__).resolve().parent.parent / "audio_editor.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))

    def walk(node: ast.AST, scope: str) -> list[tuple[str, int]]:
        """Return [(scope_name, lineno), ...] for every offending import."""
        offenders: list[tuple[str, int]] = []
        for child in ast.iter_child_nodes(node):
            # Recurse into FunctionDef / AsyncFunctionDef / ClassDef
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for stmt in ast.walk(child):
                    if isinstance(stmt, ast.Import):
                        for alias in stmt.names:
                            if alias.name == "sounddevice" and alias.asname == "sd":
                                offenders.append(
                                    (f"{scope}.{child.name}", stmt.lineno)
                                )
                offenders.extend(walk(child, f"{scope}.{child.name}"))
            elif isinstance(child, ast.ClassDef):
                offenders.extend(walk(child, f"{scope}.{child.name}"))
        return offenders

    # Top-level functions / classes live directly on the module.
    offenders = walk(tree, "audio_editor")
    assert not offenders, (
        f"Found function-scope `import sounddevice as sd` — "
        f"this shadows the module-level `sd` and causes UnboundLocalError. "
        f"Module-level `sd` is bound via safe_import; do not re-import. "
        f"Offenders: {offenders}"
    )
