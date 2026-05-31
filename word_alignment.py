"""
Word-Level Alignment Module for Eyes-Free Audio Editor

Maps words in transcript to their positions in the audio file,
enabling text-based audio editing where deleting words removes audio.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
from pydub import AudioSegment
import json


@dataclass
class WordSegment:
    """Represents a single word with its audio position"""
    text: str
    start_ms: float
    end_ms: float
    char_start: int = 0
    char_end: int = 0
    confidence: float = 1.0
    
    def duration_ms(self) -> float:
        """Get duration in milliseconds"""
        return self.end_ms - self.start_ms
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'text': self.text,
            'start_ms': self.start_ms,
            'end_ms': self.end_ms,
            'confidence': self.confidence,
            'duration_ms': self.duration_ms()
        }


class WordAlignment:
    """Manages word-to-audio alignment"""
    
    def __init__(self):
        """Initialize word alignment"""
        self.word_segments: List[WordSegment] = []
        self.original_audio: Optional[AudioSegment] = None
        
    def add_word(self, text: str, start_ms: float, end_ms: float, confidence: float = 1.0):
        segment = WordSegment(text, start_ms, end_ms, confidence=confidence)
        self.word_segments.append(segment)

    def update_char_offsets(self, text=None):
        """Calculates character offsets based on word text and single space separation.

        Args:
            text: Optional text to use for offset calculation. If None, uses word segments.
        """
        if text:
            # Use provided text to calculate offsets
            words = text.split()
        else:
            # Use word segments text
            words = [seg.text for seg in self.word_segments]

        current_offset = 0
        for i, segment in enumerate(self.word_segments):
            if i < len(words):
                segment.char_start = current_offset
                segment.char_end = current_offset + len(words[i])
                current_offset = segment.char_end + 1  # +1 for space
            else:
                # No corresponding text word — mark with sentinel so callers
                # that check for valid offsets can detect this
                segment.char_start = -1
                segment.char_end = -1
            
    def get_indices_in_char_range(self, start_char: int, end_char: int) -> List[int]:
        """Find indices of all words that overlap with the char range.

        Skips any segment with char_start=-1 (sentinel for mismatched text).
        """
        indices = []
        for i, seg in enumerate(self.word_segments):
            # Skip segments with no valid character offset
            if seg.char_start < 0:
                continue
            # Overlap check
            if seg.char_start < end_char and seg.char_end > start_char:
                indices.append(i)
        return indices
    
    def get_word_at_time(self, time_ms: float) -> Optional[WordSegment]:
        """Get word at a specific time.
        
        Args:
            time_ms: Time in milliseconds
            
        Returns:
            WordSegment if found, None otherwise
        """
        for segment in self.word_segments:
            if segment.start_ms <= time_ms < segment.end_ms:
                return segment
        return None
    
    def get_words_in_range(self, start_ms: float, end_ms: float) -> List[WordSegment]:
        """Get all words in a time range.
        
        Args:
            start_ms: Start time
            end_ms: End time
            
        Returns:
            List of WordSegments in range
        """
        return [
            seg for seg in self.word_segments
            if seg.start_ms < end_ms and seg.end_ms > start_ms
        ]
    
    def remove_word(self, word_index: int, audio: AudioSegment) -> AudioSegment:
        """Remove a word from audio by index.

        Args:
            word_index: Index of word to remove
            audio: Audio to remove word from

        Returns:
            Audio with word removed

        Raises:
            IndexError: If word_index invalid
        """
        if word_index < 0 or word_index >= len(self.word_segments):
            raise IndexError(f"Word index {word_index} out of range")

        word = self.word_segments[word_index]

        # Remove audio segment
        start_ms = int(word.start_ms)
        end_ms = int(word.end_ms)

        result = audio[:start_ms] + audio[end_ms:]

        # Update all subsequent words' times
        duration_removed = end_ms - start_ms
        for i in range(word_index + 1, len(self.word_segments)):
            self.word_segments[i].start_ms -= duration_removed
            self.word_segments[i].end_ms -= duration_removed

        # Remove the word from our list
        self.word_segments.pop(word_index)

        # Rebuild character offsets — removing a word shifts all subsequent
        # char positions so this must be kept in sync
        self._rebuild_char_offsets()

        return result

    def remove_words_by_indices(self, indices: List[int], audio: AudioSegment) -> AudioSegment:
        """Remove multiple words efficiently.

        Args:
            indices: Sorted list of word indices to remove
            audio: Audio to modify

        Returns:
            Audio with words removed
        """
        # Process in reverse order to maintain valid indices
        for idx in sorted(indices, reverse=True):
            audio = self.remove_word(idx, audio)

        return audio

    def _rebuild_char_offsets(self):
        """Recalculate character offsets for all word segments from scratch.

        Called after any operation that changes word positions or count
        (e.g. remove_word) to keep char_start/char_end in sync with the
        actual text. The text is reconstructed from segment.text values.
        """
        current_offset = 0
        for segment in self.word_segments:
            segment.char_start = current_offset
            segment.char_end = current_offset + len(segment.text)
            current_offset = segment.char_end + 1  # +1 for space separator
    
    def get_transcript_text(self) -> str:
        """Get full transcript as text.
        
        Returns:
            Space-separated words
        """
        return ' '.join([seg.text for seg in self.word_segments])
    
    def sync_with_text(self, current_text: str):
        """Synchronize word alignment with current text content
        
        Args:
            current_text: Current text in the editor
        """
        current_words = current_text.split()
        
        # Keep only word segments that still exist in current text
        new_segments = []
        for i, word in enumerate(current_words):
            # Find matching segment
            for segment in self.word_segments:
                if segment.text == word:
                    new_segments.append(segment)
                    break
        
        self.word_segments = new_segments
        
        # Update character offsets with current text
        self.update_char_offsets(current_text)
    
    def find_word_indices(self, text: str) -> List[int]:
        """Find indices of words matching text (case-insensitive).
        
        Args:
            text: Text to find (single word)
            
        Returns:
            List of matching word indices
        """
        text_lower = text.lower()
        return [
            i for i, seg in enumerate(self.word_segments)
            if seg.text.lower() == text_lower
        ]
    
    def to_json(self) -> str:
        """Serialize to JSON.
        
        Returns:
            JSON string
        """
        data = [seg.to_dict() for seg in self.word_segments]
        return json.dumps(data, indent=2)
    
    def from_json(self, json_str: str):
        """Load from JSON.
        
        Args:
            json_str: JSON string to load
        """
        data = json.loads(json_str)
        self.word_segments = [
            WordSegment(
                text=item['text'],
                start_ms=item['start_ms'],
                end_ms=item['end_ms'],
                confidence=item.get('confidence', 1.0)
            )
            for item in data
        ]


class SimpleWordAligner:
    """Simple word aligner that distributes time equally across words.
    
    Uses when word-level timestamps aren't available from transcriber.
    This is a fallback - better to use actual speech recognition with timestamps.
    """
    
    @staticmethod
    def align_words(
        transcript: str,
        audio_duration_ms: float,
        words_per_minute: float = 150.0
    ) -> WordAlignment:
        """Create word alignment by distributing duration equally.
        
        Args:
            transcript: Full transcript text
            audio_duration_ms: Audio duration in milliseconds
            words_per_minute: Expected speaking rate
            
        Returns:
            WordAlignment object
        """
        words = transcript.split()
        
        if not words:
            return WordAlignment()
        
        # Calculate time per word
        time_per_word_ms = audio_duration_ms / len(words)
        
        alignment = WordAlignment()
        current_time = 0.0
        
        for word in words:
            start_ms = current_time
            end_ms = current_time + time_per_word_ms
            alignment.add_word(word, start_ms, end_ms)
            current_time = end_ms
        
        return alignment


def estimate_word_timings(transcript: str, audio_duration_ms: float) -> WordAlignment:
    """Estimate word timings from transcript.
    
    Args:
        transcript: Full transcript
        audio_duration_ms: Audio duration in milliseconds
        
    Returns:
        WordAlignment with estimated timings
    """
    return SimpleWordAligner.align_words(transcript, audio_duration_ms)
