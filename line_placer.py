"""
Line Placer Module for SpeechCraft

Automatically matches transcribed audio descriptions to script lines
and places audio at correct time codes.

Uses fuzzy matching to find the best matches between transcript
and script descriptions.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
from difflib import SequenceMatcher
from pydub import AudioSegment


@dataclass
class LineMatch:
    """Result of matching a script line to transcript"""
    script_line_number: int
    description: str
    transcript_text: str
    match_score: float          # 0-1 (1 = perfect match)
    audio_start_ms: int         # Start of matching audio
    audio_end_ms: int           # End of matching audio
    script_time_in_ms: int      # Where it should go in final audio
    script_time_out_ms: int     # End time in final audio
    confidence_level: str       # 'high', 'medium', 'low'


class LinePlacerAlgorithm:
    """Matches transcript segments to script lines"""
    
    def __init__(self, min_match_score: float = 0.6):
        """Initialize line placer.
        
        Args:
            min_match_score: Minimum matching score (0-1) to accept match
        """
        self.min_match_score = min_match_score
    
    def match_lines(
        self,
        script_lines: List,           # ScriptLine objects
        transcript_text: str,
        word_alignment=None            # WordAlignment object from transcription
    ) -> List[LineMatch]:
        """Match script lines to transcript segments.
        
        Args:
            script_lines: List of ScriptLine from script file
            transcript_text: Full transcribed text from audio
            word_alignment: Word timing information (optional)
            
        Returns:
            List of LineMatch objects
        """
        matches = []
        
        # Clean transcript
        transcript_cleaned = self._clean_text(transcript_text)
        
        # Try to match each script line to transcript
        for script_line in script_lines:
            description_cleaned = self._clean_text(script_line.description)
            
            # Find best matching segment in transcript
            match_info = self._find_best_match(
                description_cleaned,
                transcript_cleaned,
                word_alignment
            )
            
            if match_info and match_info['score'] >= self.min_match_score:
                audio_start = match_info['audio_start_ms']
                audio_end = match_info['audio_end_ms']
                score = match_info['score']
                
                # Determine confidence level
                if score >= 0.95:
                    confidence = 'high'
                elif score >= 0.80:
                    confidence = 'medium'
                else:
                    confidence = 'low'
                
                match = LineMatch(
                    script_line_number=script_line.line_number,
                    description=script_line.description,
                    transcript_text=match_info['matched_text'],
                    match_score=score,
                    audio_start_ms=audio_start,
                    audio_end_ms=audio_end,
                    script_time_in_ms=script_line.time_in_ms,
                    script_time_out_ms=script_line.time_out_ms,
                    confidence_level=confidence
                )
                
                matches.append(match)
        
        return matches
    
    def _find_best_match(
        self,
        pattern: str,
        text: str,
        word_alignment=None
    ) -> Optional[dict]:
        """Find best matching segment of text for pattern.
        
        Args:
            pattern: Text to search for (cleaned)
            text: Text to search in (cleaned)
            word_alignment: Optional word timing info
            
        Returns:
            Dict with 'score', 'matched_text', 'audio_start_ms', 'audio_end_ms'
        """
        words = text.split()
        pattern_words = pattern.split()
        
        if not pattern_words or not words:
            return None
        
        best_score = 0
        best_start_idx = 0
        best_end_idx = 0
        best_segment = ""
        
        # Try all possible segments of similar length
        pattern_len = len(pattern_words)
        window_range = max(2, int(pattern_len * 0.5))  # Allow ±50% length variation
        
        for start_idx in range(len(words) - pattern_len + window_range + 1):
            for end_idx in range(start_idx + pattern_len - window_range, 
                                start_idx + pattern_len + window_range + 1):
                if end_idx > len(words):
                    continue
                
                segment = ' '.join(words[start_idx:end_idx])
                score = self._calculate_similarity(pattern, segment)
                
                if score > best_score:
                    best_score = score
                    best_start_idx = start_idx
                    best_end_idx = end_idx
                    best_segment = segment
        
        if best_score >= self.min_match_score:
            # Calculate audio timing
            audio_start_ms = 0
            audio_end_ms = 0
            
            if word_alignment:
                # Use word timing if available
                try:
                    # Get timing for matched word range
                    # NOTE: WordAlignment uses word_segments, not .segments
                    segments = getattr(word_alignment, 'word_segments', None)
                    if segments is None:
                        raise AttributeError("no word_segments attribute")
                    if best_start_idx < len(segments):
                        start_segment = segments[best_start_idx]
                        audio_start_ms = int(start_segment.start_ms)

                    if best_end_idx - 1 < len(segments):
                        end_segment = segments[best_end_idx - 1]
                        audio_end_ms = int(end_segment.end_ms)
                except (IndexError, AttributeError):
                    pass
            
            return {
                'score': best_score,
                'matched_text': best_segment,
                'audio_start_ms': audio_start_ms,
                'audio_end_ms': audio_end_ms,
                'start_word_idx': best_start_idx,
                'end_word_idx': best_end_idx
            }
        
        return None
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity score between two texts (0-1).
        
        Uses SequenceMatcher ratio.
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Similarity score 0-1
        """
        return SequenceMatcher(None, text1, text2).ratio()
    
    def _clean_text(self, text: str) -> str:
        """Clean text for matching.
        
        Args:
            text: Text to clean
            
        Returns:
            Cleaned text (lowercase, minimal punctuation)
        """
        # Convert to lowercase
        text = text.lower()
        
        # Remove common punctuation but keep hyphens and apostrophes for contractions
        import string
        remove_chars = string.punctuation.replace("'", "").replace("-", "")
        for char in remove_chars:
            text = text.replace(char, "")
        
        # Normalize whitespace
        text = ' '.join(text.split())
        
        return text


class AudioSegmentPlacer:
    """Place audio segments at script times"""
    
    @staticmethod
    def create_output_audio(
        original_audio: AudioSegment,
        line_matches: List[LineMatch],
        total_duration_ms: int,
        silence_duration_ms: int = 500
    ) -> Tuple[AudioSegment, dict]:
        """Create output audio with matched segments at script times.

        Args:
            original_audio: Original AudioSegment with full recording
            line_matches: List of LineMatch objects
            total_duration_ms: Total duration of output (should match script total)
            silence_duration_ms: Duration of silence between segments

        Returns:
            Tuple of (output_audio, placement_stats)
        """
        # Start with silence the full duration — segments are overlaid on top
        output_audio = AudioSegment.silent(duration=total_duration_ms)
        
        segments_placed = 0
        total_audio_used = 0
        gaps = 0
        
        for match in line_matches:
            try:
                # Extract matched segment from original
                segment = original_audio[match.audio_start_ms:match.audio_end_ms]

                # Overlay the segment at its correct time position in the timeline.
                # Using .overlay() (not +=) so segments genuinely land at
                # script_time_in_ms, even if they overlap or are out of order.
                output_audio = output_audio.overlay(
                    segment,
                    position=match.script_time_in_ms
                )

                segments_placed += 1
                total_audio_used += len(segment)

            except Exception as e:
                print(f"Warning: Could not place segment {match.script_line_number}: {e}")
                continue

        # Trim to exact duration (overlay may have extended it)
        output_audio = output_audio[:total_duration_ms]
        
        stats = {
            'segments_placed': segments_placed,
            'total_audio_used_ms': total_audio_used,
            'total_silence_ms': total_duration_ms - total_audio_used,
            'coverage_percent': (total_audio_used / total_duration_ms * 100) if total_duration_ms > 0 else 0
        }
        
        return output_audio, stats
    
    @staticmethod
    def get_placement_report(line_matches: List[LineMatch]) -> str:
        """Generate human-readable placement report.
        
        Args:
            line_matches: List of LineMatch objects
            
        Returns:
            Formatted report string
        """
        report = "Audio Description Line Placement Report\n"
        report += "=" * 60 + "\n\n"
        
        high_conf = len([m for m in line_matches if m.confidence_level == 'high'])
        med_conf = len([m for m in line_matches if m.confidence_level == 'medium'])
        low_conf = len([m for m in line_matches if m.confidence_level == 'low'])
        
        report += f"Total Matches: {len(line_matches)}\n"
        report += f"  High Confidence: {high_conf}\n"
        report += f"  Medium Confidence: {med_conf}\n"
        report += f"  Low Confidence: {low_conf}\n\n"
        
        report += "Line-by-Line Placements:\n"
        report += "-" * 60 + "\n"
        
        for match in line_matches:
            from script_handler import ScriptUtils
            time_in = ScriptUtils.ms_to_time_str(match.script_time_in_ms)
            time_out = ScriptUtils.ms_to_time_str(match.script_time_out_ms)
            score_pct = int(match.match_score * 100)
            
            report += f"\nLine {match.script_line_number}: [{time_in} --> {time_out}]\n"
            report += f"  Script: {match.description}\n"
            report += f"  Matched: {match.transcript_text}\n"
            report += f"  Match Score: {score_pct}% ({match.confidence_level})\n"
        
        report += "\n" + "=" * 60 + "\n"
        
        return report
