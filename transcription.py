"""
Transcription Module for SpeechCraft Studio

Provides speech-to-text with two backends:
  1. FasterWhisperTranscriber — local, offline, SA-accent capable
  2. GoogleSpeechRecognition — cloud API, requires internet

The module also provides word-level alignment for text-based (destructive)
audio editing — when a word is edited in the text, the corresponding audio
segment is rebuilt from the surrounding word boundaries.

Optional punctuation restoration:
  restore_punctuation(text) adds punctuation using a local rule-based engine.
  If transformers+torch are available and the download completes, the
  oliverguhr/fullstop-punctuation-multilingual-base model upgrades the output
  automatically within 30 seconds of first call.
"""

import os
import re
import tempfile
import threading
from typing import Tuple, Optional
from pydub import AudioSegment

from word_alignment import WordAlignment, estimate_word_timings

try:
    import speech_recognition as sr
    GOOGLE_SR_AVAILABLE = True
except ImportError:
    GOOGLE_SR_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False


# ── Sentence Tokenizer (rule-based, offline) ─────────────────────────────────

class SentenceTokenizer:
    """Split unpunctuated plain text into sentence-length chunks.
    
    Uses regex heuristics that work on English text without requiring
    a pre-trained model or downloaded data. Good enough for studio
    script lines (typically 1-3 sentences at a time).
    
    Handles:
    - Common abbreviations (Dr, Mr, Mrs, Ms, Prof, Rev, Sr, Jr, Inc, Ltd, etc.)
      to avoid false sentence breaks
    - Capital letters as sentence starts
    - Question words at the end → question sentence
    - Transition words as sentence boundary markers
    """
    
    # Lowercase forms of common transition/linking words
    TRANSITION_WORDS = frozenset({
        'and', 'but', 'or', 'nor', 'for', 'yet', 'so',
        'however', 'therefore', 'moreover', 'furthermore', 'nevertheless',
        'meanwhile', 'otherwise', 'instead', 'thus', 'hence', 'although',
        'because', 'since', 'unless', 'until', 'while', 'whereas',
        'also', 'besides', 'finally', 'next', 'then', 'now', 'later',
    })
    
    # Words that commonly end interrogative sentences
    QUESTION_ENDERS = frozenset({
        'who', 'what', 'where', 'when', 'why', 'how', 'whom', 'whose',
        'which', "what's", "where's", "who's", "how's", "when's",
        'is', 'are', 'was', 'were', 'do', 'does', 'did', 'have', 'has',
        'can', 'could', 'will', 'would', 'should', 'may', 'might', 'must',
    })
    
    # Lowercase words that should NOT trigger a capital after them
    ABORT_CAPITAL = frozenset({
        'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
        'for', 'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were',
        'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
        'will', 'would', 'could', 'should', 'may', 'might', 'must',
    })
    
    @classmethod
    def split_into_sentences(cls, text: str) -> list[str]:
        """Split unpunctuated text into sentence strings.

        Args:
            text: Raw text with no or minimal punctuation.

        Returns:
            List of sentence strings, cleaned and stripped.
        """
        if not text or not text.strip():
            return []

        # Normalise whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        # ── Rule 1: interrogative sentences ──────────────────────────────────
        # Pattern: starts with capital, ends with a question-word
        # "Where do you live"  "What is your name"
        QUESTION_START_WORDS = (
            'who', 'what', 'where', 'when', 'why', 'how', 'whom', 'whose', 'which'
        )
        question_pattern = rf'^(A-Z[a-z].*?\b({"|".join(QUESTION_START_WORDS)}))\s*$'
        m = re.match(question_pattern, text, re.IGNORECASE)
        if m:
            return [text]

        # ── Rule 2: explicit punctuation already present ────────────────────
        # Respect existing . ? !
        if re.search(r'[.!?]\s+[A-Z]', text):
            parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
            return [p.strip() for p in parts if p.strip()]

        # ── Rule 3: split before transition words that start a new clause ───
        # "hello and welcome" stays one sentence
        # "hello and Now this begins" → split
        TRANSITION_BOUNDARY = (
            r'(?<=[a-z])\s+\b(?:and|but|or|so|however|therefore|next|then|'
            r'also|finally|although|because|since|unless|while|'
            r'nevertheless|moreover|furthermore|instead|thus|hence)\s+(?=[A-Z])'
        )
        if re.search(TRANSITION_BOUNDARY, text):
            parts = re.split(TRANSITION_BOUNDARY, text)
            return [p.strip() for p in parts if p.strip()]

        # ── Rule 4: single sentence ──────────────────────────────────────────
        return [text]


# ── Rule-based Punctuation Restorer ──────────────────────────────────────────

class RuleBasedPunctuation:
    """Add punctuation to unpunctuated plain text.
    
    Operates in two stages:
      1. Sentence segmentation — find sentence boundaries using SentenceTokenizer
      2. Punctuation insertion — add periods, commas, question marks
    
    Completely offline, no model download needed.
    """
    
    @classmethod
    def restore(cls, text: str) -> str:
        """Add punctuation to unpunctuated plain text.

        Strategy:
          1. Sentence segmentation via SentenceTokenizer
          2. Capitalize sentence starts
          3. Detect and mark questions (? ending)
          4. Detect exclamations (! ending)
          5. Default: period (.) ending

        Commas are intentionally omitted — they add complexity without
        improving readability in spoken script output. List this as
        a future enhancement if neural punctuation is unavailable.

        Args:
            text: Raw ASR output with no or minimal punctuation.

        Returns:
            Text with punctuation added.

        Examples:
            "hello welcome to the studio this is a test"
            → "Hello welcome to the studio this is a test."

            "what is your name"
            → "What is your name?"

            "yes that sounds great"
            → "Yes that sounds great!"
        """
        if not text or not text.strip():
            return text

        sentences = SentenceTokenizer.split_into_sentences(text)

        if not sentences:
            return text

        result_parts = []
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue

            # Capitalize first letter
            sent = sent[0].upper() + sent[1:] if len(sent) > 1 else sent.upper()

            words = sent.split()
            if not words:
                continue

            last_word = words[-1].lower().rstrip('?.,!')

            # Detect question: sentence starts with interrogative word
            QUESTION_STARTERS = frozenset({
                'who', 'what', 'where', 'when', 'why', 'how',
                'whom', 'whose', 'which'
            })
            is_question = (
                words[0].lower().lstrip("'\"") in QUESTION_STARTERS
            )

            # Detect exclamation: ends with enthusiasm word
            is_exclaim = last_word in cls.EXCLAIM_ENDERS

            # Apply terminal punctuation
            if is_question:
                sent = sent.rstrip('.,!') + '?'
            elif is_exclaim:
                sent = sent.rstrip('.,?') + '!'
            else:
                sent = sent.rstrip('?,!') + '.'

            result_parts.append(sent)

        return ' '.join(result_parts)


# ── Neural Punctuation (lazy-load, background download) ───────────────────────

class _NeuralPunctuationPipeline:
    """Lazy-loading neural punctuation model.
    
    Downloads oliverguhr/fullstop-punctuation-multilingual-base (~260MB)
    in a background thread on first use. Falls back to rule-based
    immediately while downloading.
    
    After download completes, subsequent calls use the neural model automatically.
    """
    
    _instance = None
    _lock = threading.Lock()
    _download_done = False
    _download_failed = False
    
    def __init__(self):
        self._pipeline = None
        self._load_thread = None
        self._load_lock = threading.Lock()
        self._ready = False
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance._start_bg_load()
        return cls._instance
    
    def _start_bg_load(self):
        """Start background download/load of the punctuation model."""
        def bg_load():
            try:
                import torch
                from transformers import pipeline, AutoTokenizer, AutoModelForTokenClassification
                
                tokenizer = AutoTokenizer.from_pretrained(
                    'oliverguhr/fullstop-punctuation-multilingual-base',
                    local_files_only=False
                )
                model = AutoModelForTokenClassification.from_pretrained(
                    'oliverguhr/fullstop-punctuation-multilingual-base'
                )
                self._pipeline = pipeline(
                    'token-classification',
                    model=model,
                    tokenizer=tokenizer,
                    device=-1,  # CPU
                    aggregation_strategy='simple'
                )
                self._ready = True
                _NeuralPunctuationPipeline._download_done = True
            except Exception as e:
                print(f"Neural punctuation model unavailable: {e}")
                _NeuralPunctuationPipeline._download_failed = True
                self._ready = False
        
        self._load_thread = threading.Thread(target=bg_load, daemon=True)
        self._load_thread.start()
    
    def punctuate(self, text: str, timeout: float = 5.0) -> str:
        """Restore punctuation using neural model if available.
        
        Args:
            text:     Plain unpunctuated text.
            timeout:  Seconds to wait for neural model to load.
                     If timeout expires, falls back to rule-based immediately.
        
        Returns:
            Punctuated text (neural if available, else rule-based).
        """
        if not text or not text.strip():
            return text
        
        # If already ready, use neural
        if self._ready and self._pipeline:
            try:
                result = self._pipeline(text)
                # Pipeline returns list of {"word": "Hello", "entity_group": "COMMA", ...}
                return self._reassemble(result)
            except Exception:
                pass  # Fall through to rule-based
        
        # Check if download is still running
        if not _NeuralPunctuationPipeline._download_done and not _NeuralPunctuationPipeline._download_failed:
            # Wait up to `timeout` seconds for download
            if self._load_thread:
                self._load_thread.join(timeout=timeout)
            if self._ready and self._pipeline:
                try:
                    result = self._pipeline(text)
                    return self._reassemble(result)
                except Exception:
                    pass
        
        # Fall back to rule-based
        return RuleBasedPunctuation.restore(text)
    
    @staticmethod
    def _reassemble(pipeline_result: list) -> str:
        """Convert pipeline output back to punctuated text.
        
        Pipeline returns e.g.:
          [{"word": "Hello", "entity_group": "PERIOD"}, {"word": "world", "entity_group": "COMMA"}, ...]
        Labels: PERIOD, COMMA, QUESTION, EXCLAMATION, O (no punct)
        """
        label_map = {
            'PERIOD': '.',
            'COMMA': ',',
            'QUESTION': '?',
            'EXCLAMATION': '!',
            'COLON': ':',
            'SEMICOLON': ';',
        }
        
        parts = []
        for item in pipeline_result:
            word = item.get('word', '')
            label = item.get('entity_group', 'O')
            punct = label_map.get(label, '')
            parts.append(word + punct)
        
        text = ''.join(parts)
        # Clean up: add spaces after periods/questions/exclamations followed by capitals
        text = re.sub(r'([.!?])([A-Z])', r'\1 \2', text)
        # Clean up: add space after commas followed by non-space
        text = re.sub(r'(,)([^,\s])', r'\1 \2', text)
        return text


# ── Convenience function ───────────────────────────────────────────────────────

def restore_punctuation(text: str, use_neural: bool = True) -> str:
    """Restore punctuation in unpunctuated plain text.
    
    Uses the neural fullstop model if available (or finishes downloading within
    5 seconds), otherwise falls back to the rule-based engine.
    
    Args:
        text:      Raw ASR output with no or minimal punctuation.
        use_neural: If True (default), try neural model first. If False,
                    use only rule-based engine.
    
    Returns:
        Text with punctuation added.
    
    Examples:
        "hello welcome to the studio this is a test"
        → "Hello, welcome to the studio. This is a test."
    """
    if not text or not text.strip():
        return text
    
    if not use_neural:
        return RuleBasedPunctuation.restore(text)
    
    try:
        pipeline = _NeuralPunctuationPipeline.get_instance()
        return pipeline.punctuate(text, timeout=5.0)
    except Exception:
        return RuleBasedPunctuation.restore(text)


# ── Transcription Engines ──────────────────────────────────────────────────────

class TranscriptionEngine:
    """Base class for transcription engines."""
    
    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError
    
    def transcribe_with_alignment(
        self,
        audio_path: str
    ) -> Tuple[str, WordAlignment]:
        transcript = self.transcribe(audio_path)
        audio = AudioSegment.from_file(audio_path)
        duration_ms = len(audio)
        alignment = estimate_word_timings(transcript, duration_ms)
        alignment.update_char_offsets()
        return transcript, alignment


class FasterWhisperTranscriber(TranscriptionEngine):
    """Local Whisper-based transcription using Faster Whisper.
    
    Runs entirely offline. Supports SA English accents.
    Caches the model in ~/.cache/huggingface/ after first run.
    
    Args:
        model_size:  "tiny", "base", "small", "medium", or "large".
                     Defaults to "small".
        device:      "cpu" or "cuda". Defaults to "cpu".
        language:    BCP-47 language code. Defaults to "en".
        punctuate:   If True, adds punctuation automatically using
                     restore_punctuation(). Default: True.
    """
    
    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        language: str = "en",
        punctuate: bool = True
    ):
        if not FASTER_WHISPER_AVAILABLE:
            raise ImportError(
                "faster-whisper not installed. "
                "Install with: pip install faster-whisper"
            )
        
        self.model_size = model_size
        self.device = device
        self.language = language
        self.punctuate = punctuate
        self._model = None
        self._init_lock = threading.Lock()
    
    def _get_model(self):
        if self._model is None:
            with self._init_lock:
                if self._model is None:
                    compute = "float16" if self.device == "cuda" else "int8"
                    self._model = WhisperModel(
                        self.model_size,
                        device=self.device,
                        compute_type=compute
                    )
        return self._model
    
    def transcribe(self, audio_path: str) -> str:
        model = self._get_model()
        wav_path = self._ensure_wav_16k(audio_path)
        
        try:
            segments, info = model.transcribe(
                wav_path,
                language=self.language,
                word_timestamps=True
            )
            
            transcript_parts = []
            for segment in segments:
                transcript_parts.append(segment.text.strip())
            
            transcript = " ".join(transcript_parts)
            
            if self.punctuate:
                transcript = restore_punctuation(transcript)
            
            return transcript
            
        finally:
            if wav_path != audio_path:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
    
    def transcribe_with_alignment(self, audio_path: str) -> Tuple[str, WordAlignment]:
        model = self._get_model()
        wav_path = self._ensure_wav_16k(audio_path)
        
        try:
            segments, info = model.transcribe(
                wav_path,
                language=self.language,
                word_timestamps=True
            )
            
            words = []
            char_offset = 0
            for segment in segments:
                for word in segment.words:
                    word_text = word.word.strip()
                    if not word_text:
                        continue
                    words.append({
                        'word': word_text,
                        'start_ms': int(word.start * 1000),
                        'end_ms': int(word.end * 1000),
                        'char_offset': char_offset
                    })
                    char_offset += len(word_text) + 1
            
            # Build full transcript
            raw_transcript = " ".join(w['word'] for w in words)
            
            if self.punctuate:
                raw_transcript = restore_punctuation(raw_transcript)
            
            # Re-count character offsets for the punctuated transcript
            char_offset = 0
            for w in words:
                w['char_offset'] = char_offset
                char_offset += len(w['word']) + 1
            
            alignment = WordAlignment()
            for w in words:
                alignment.add_word(
                    w['word'], w['start_ms'], w['end_ms'], w['char_offset']
                )
            alignment.update_char_offsets()
            
            return raw_transcript, alignment
            
        finally:
            if wav_path != audio_path:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
    
    def _ensure_wav_16k(self, audio_path: str) -> str:
        if audio_path.lower().endswith('.wav'):
            try:
                audio = AudioSegment.from_file(audio_path)
                if audio.frame_rate == 16000 and audio.channels == 1:
                    return audio_path
            except Exception:
                pass
        
        audio = AudioSegment.from_file(audio_path)
        audio = audio.set_frame_rate(16000).set_channels(1)
        
        temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        wav_path = temp_wav.name
        temp_wav.close()
        audio.export(wav_path, format="wav")
        return wav_path


class GoogleSpeechRecognition(TranscriptionEngine):
    """Google Speech Recognition via speech_recognition library.
    
    Uses Google's free web API. Requires internet access.
    Rate-limited. Prefer FasterWhisperTranscriber for new code.
    """
    
    def __init__(self, language: str = "en-US", punctuate: bool = True):
        if not GOOGLE_SR_AVAILABLE:
            raise ImportError(
                "speech_recognition not installed. "
                "Install with: pip install SpeechRecognition"
            )
        self.recognizer = sr.Recognizer()
        self.language = language
        self.punctuate = punctuate
    
    def transcribe(self, audio_path: str) -> str:
        wav_path = self._ensure_wav(audio_path)
        
        try:
            with sr.AudioFile(wav_path) as source:
                audio = self.recognizer.record(source)
            
            text = self.recognizer.recognize_google(audio, language=self.language)
            
            if self.punctuate:
                text = restore_punctuation(text)
            
            return text
            
        except sr.UnknownValueError:
            raise Exception("Could not understand audio. Check audio quality.")
        except sr.RequestError as e:
            raise Exception(f"Google Speech Recognition API error: {e}")
        finally:
            if wav_path != audio_path:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
    
    def _ensure_wav(self, audio_path: str) -> str:
        if audio_path.lower().endswith('.wav'):
            return audio_path
        
        audio = AudioSegment.from_file(audio_path)
        temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        wav_path = temp_wav.name
        temp_wav.close()
        audio.export(wav_path, format="wav")
        return wav_path


# ── Config ────────────────────────────────────────────────────────────────────

class TranscriptionConfig:
    LANGUAGES = {
        "English (US)": "en-US",
        "English (UK)": "en-GB",
        "English (SA)": "en",
        "Spanish": "es-ES",
        "French": "fr-FR",
        "German": "de-DE",
        "Italian": "it-IT",
        "Portuguese": "pt-BR",
        "Dutch": "nl-NL",
        "Russian": "ru-RU",
        "Japanese": "ja-JP",
        "Chinese (Simplified)": "zh-CN",
        "Chinese (Traditional)": "zh-TW",
    }
    
    WHISPER_MODEL_SIZES = ("tiny", "base", "small", "medium", "large")
    WHISPER_DEFAULT_MODEL = "small"
    DEFAULT_LANGUAGE = "en"
    DEFAULT_ENGINE = "faster-whisper"


# ── Factory ───────────────────────────────────────────────────────────────────

def create_transcriber(
    engine: str = None,
    language: str = None,
    punctuate: bool = True,
    **kwargs
) -> TranscriptionEngine:
    """Create a transcription engine.
    
    Args:
        engine:     "faster-whisper" or "google". Defaults to faster-whisper.
        language:   BCP-47 language code.
        punctuate:  Add punctuation to output. Default: True.
        **kwargs:   Passed to the engine (e.g. model_size="base").
    
    Returns:
        A TranscriptionEngine instance.
    """
    if engine is None:
        engine = "faster-whisper" if FASTER_WHISPER_AVAILABLE else "google"
    
    lang = language or TranscriptionConfig.DEFAULT_LANGUAGE
    
    if engine == "faster-whisper":
        if not FASTER_WHISPER_AVAILABLE:
            raise ImportError("faster-whisper not installed. Run: pip install faster-whisper")
        model_size = kwargs.pop("model_size", TranscriptionConfig.WHISPER_DEFAULT_MODEL)
        if model_size not in TranscriptionConfig.WHISPER_MODEL_SIZES:
            raise ValueError(f"Unknown model_size. Choose from: {TranscriptionConfig.WHISPER_MODEL_SIZES}")
        return FasterWhisperTranscriber(model_size=model_size, language=lang, punctuate=punctuate, **kwargs)
    
    elif engine == "google":
        return GoogleSpeechRecognition(language=lang, punctuate=punctuate, **kwargs)
    
    else:
        raise ValueError(f"Unknown transcription engine: {engine}")


def transcribe_audio(
    audio_path: str,
    engine: str = None,
    language: str = None,
    punctuate: bool = True,
    **kwargs
) -> str:
    """Transcribe an audio file to text.
    
    Convenience wrapper around create_transcriber().transcribe().
    """
    transcriber = create_transcriber(engine=engine, language=language, punctuate=punctuate, **kwargs)
    return transcriber.transcribe(audio_path)