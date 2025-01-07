import subprocess
from pathlib import Path
import shutil  # To replace 'cp'

class iTunesIntegrator:
    def __init__(self, playlist_name, config):
        self.playlist_name = playlist_name
        self.config = config

    def insert_playlist_to_itunes(self):
        try:
            # Use the passed config data
            itunes_dir = self.config['itunes_dir']

            # Construct the source file path and destination directory
            src_file = Path.cwd() / (self.playlist_name + ".m3u")
            dest_file = Path(itunes_dir) / (self.playlist_name + ".m3u")

            # Convert line endings (if necessary)
            self.convert_line_endings(src_file)

            # Copy the file to the iTunes directory
            print(f"Copying {src_file} to {dest_file}")
            shutil.copy(src_file, dest_file)

            # Execute the VBScript to import the playlist
            vbscript_path = str(Path(itunes_dir) / "ImportM3U.vbs")
            result = subprocess.run(
                ["cscript", vbscript_path, str(dest_file)],
                capture_output=True, text=True
            )

            # Check for success
            if result.returncode == 0:
                success = True
                result_message = f"{dest_file} imported successfully."
            else:
                success = False
                result_message = f"VBScript failed: {result.stderr}"

            return success, result_message

        except Exception as e:
            return False, str(e)

    def convert_line_endings(self, file_path):
        """Convert line endings to Windows-style (CRLF)."""
        try:
            with open(file_path, 'r', newline='') as f:
                content = f.read()
            with open(file_path, 'w', newline='\r\n') as f:
                f.write(content)
            print(f"Converted line endings for {file_path}")
        except Exception as e:
            print(f"Error converting line endings: {e}")
