import os
import subprocess
import sys
import shutil

def build_exe():
    """Build the SpeechCraft executable using PyInstaller with spec file"""
    print("Building SpeechCraft Studio Executable...\n")

    # Check for PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Clean old build artifacts
    for folder in ['build', 'dist']:
        if os.path.exists(folder):
            print(f"Cleaning old {folder}/ folder...")
            shutil.rmtree(folder)

    # Run PyInstaller with the spec file
    spec_file = "SpeechCraft_Studio.spec"
    cmd = ["pyinstaller", "--noconfirm", spec_file]

    print(f"Running: {' '.join(cmd)}\n")

    try:
        subprocess.run(cmd, check=True)
        print("\n✅ Build Complete! SpeechCraft Studio ready for distribution")
        print("📁 Executable: dist/SpeechCraft_Studio.exe")

        if os.path.exists("ffmpeg.exe"):
            print("✅ FFmpeg included - full MP3 support available")
        else:
            print("⚠️  FFmpeg not found in project folder - MP3 support needs system FFmpeg")

        # Show final file size
        exe_path = os.path.join("dist", "SpeechCraft_Studio.exe")
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"📦 Executable size: {size_mb:.1f} MB")

    except subprocess.CalledProcessError as e:
        print(f"\n❌ Build Failed: {e}")
        print("\nIf you see 'ModuleNotFoundError', the spec file may need the missing module added to hiddenimports.")
        print("Edit SpeechCraft_Studio.spec and add the module name to the hiddenimports list.")
        sys.exit(1)

if __name__ == "__main__":
    build_exe()