import os
import json
import zipfile
import shutil
import tempfile
from pathlib import Path
from pydub import AudioSegment
import audio_tracks

class ProjectHandler:
    """Handles saving and loading of SpeechCraft Projects (.scproj)"""
    
    @staticmethod
    def get_default_project_dir():
        """Returns path to My Documents/SpeechCraft Projects"""
        docs = Path(os.path.expanduser("~")) / "Documents"
        proj_dir = docs / "SpeechCraft Projects"
        if not proj_dir.exists():
            proj_dir.mkdir(parents=True, exist_ok=True)
        return str(proj_dir)

    @staticmethod
    def save_project(path, track_manager, transcript, alignment, script=None):
        """
        Saves the current state to a .scproj (zip) file.
        Structure:
          - project.json (Metadata, transcript, settings)
          - audio/ (Folder containing .wav files for each track)
        """
        try:
            # Create a temporary directory to assemble the project
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                audio_dir = temp_path / "audio"
                audio_dir.mkdir()
                
                # 1. Prepare Metadata
                metadata = {
                    "version": "1.0",
                    "transcript": transcript,
                    "alignment": alignment, # Assuming alignment is serializable (list of dicts)
                    "script": script, # List of strings
                    "tracks": []
                }
                
                # 2. Export Tracks
                for track in track_manager.tracks:
                    track_filename = f"{track.track_id}.wav"
                    
                    # Serialize Track Info
                    t_data = {
                        "id": track.track_id,
                        "name": track.name,
                        "type": track.track_type.value,
                        "volume_db": track.volume_db,
                        "muted": track.muted,
                        "solo": track.solo,
                        "pan": track.pan,
                        "start_offset_ms": track.start_offset_ms,
                        "filename": track_filename,
                        "visible": track.visible
                    }
                    metadata["tracks"].append(t_data)
                    
                    # Save Audio File
                    if track.audio_segment:
                        out_path = audio_dir / track_filename
                        track.audio_segment.export(str(out_path), format="wav")
                
                # 3. Write JSON
                with open(temp_path / "project.json", "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=4)
                    
                # 4. Zip it up
                with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    # Add JSON
                    zipf.write(temp_path / "project.json", arcname="project.json")
                    # Add Audio Files
                    for file in audio_dir.glob("*.wav"):
                        zipf.write(file, arcname=f"audio/{file.name}")
                        
            return True, "Project saved successfully."
        except Exception as e:
            import traceback
            return False, f"Failed to save project: {e}\n{traceback.format_exc()}"

    @staticmethod
    def load_project(path, track_manager):
        """
        Loads a .scproj file.
        Returns: (success, result_dict_or_error)
        result_dict keys: transcript, alignment, script
        """
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # 1. Extract Zip
                with zipfile.ZipFile(path, 'r') as zipf:
                    zipf.extractall(temp_dir)
                
                base = Path(temp_dir)
                json_path = base / "project.json"
                
                if not json_path.exists():
                    return False, "Invalid project file: missing project.json"
                
                # 2. Read Metadata
                with open(json_path, 'r', encoding="utf-8") as f:
                    metadata = json.load(f)
                
                # 3. Clear existing tracks
                track_manager.tracks = []
                
                # 4. Reconstruct Tracks
                audio_dir = base / "audio"
                
                for t_data in metadata["tracks"]:
                    # Load audio
                    audio_file = audio_dir / t_data["filename"]
                    seg = None
                    if audio_file.exists():
                        seg = AudioSegment.from_wav(str(audio_file))
                    
                    # Create Track
                    # Map string type back to Enum
                    t_type = audio_tracks.TrackType(t_data["type"])
                    
                    track = track_manager.add_track(
                        name=t_data["name"],
                        audio_segment=seg,
                        track_type=t_type,
                        start_offset_ms=t_data.get("start_offset_ms", 0)
                    )
                    
                    # Restore properties
                    track.track_id = t_data["id"] # Keep ID consistent? Or let manager assign?
                    # Manager assigns new IDs usually, but for save/load consistency we might want to keep?
                    # track_manager.add_track increments ID. 
                    # Let's overwrite properties.
                    track.volume_db = t_data["volume_db"]
                    track.muted = t_data["muted"]
                    track.solo = t_data["solo"]
                    track.pan = t_data["pan"]
                    track.visible = t_data.get("visible", True)

                return True, {
                    "transcript": metadata.get("transcript", ""),
                    "alignment": metadata.get("alignment", None),
                    "script": metadata.get("script", None)
                }

        except Exception as e:
            import traceback
            return False, f"Failed to load project: {e}\n{traceback.format_exc()}"

    @staticmethod
    def export_mixdown(path, track_manager, fmt="wav"):
        """Exports the mixed audio to a file"""
        try:
            mixed = track_manager.mix_down()
            if not mixed:
                return False, "No audio to export."
            
            mixed.export(path, format=fmt)
            return True, "Export successful."
        except Exception as e:
            return False, f"Export failed: {e}"
