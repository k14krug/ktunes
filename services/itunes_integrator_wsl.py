import subprocess
from pathlib import Path

# You might need additional imports depending on how you interact with iTunes

class iTunesIntegrator:
    def __init__(self, playlist_name, config):
        self.playlist_name = playlist_name
        self.config = config

    def insert_playlist_to_itunes(self):
        try:
            # Use the passed config data
            itunes_dir = self.config['itunes_dir']

            # Convert the Windows path to a WSL path
            #itunes_dir_wsl = "/mnt/c/" + itunes_dir.replace("C:\\", "").replace("\\", "/")

            # Construct the source file path and destination directory
            src_file = Path.cwd() / (self.playlist_name + ".m3u")
            dest_dir = Path(itunes_dir)

            # Run unix2dos on the file
            subprocess.run(["unix2dos", str(src_file)], capture_output=True, text=True)

            # Print the cp command and its arguments for debugging
            cp_command = ["cp", str(src_file), str(dest_dir)]
            print("Running command:", " ".join(cp_command))

            # Copy the file
            cp_result = subprocess.run(cp_command, capture_output=True, text=True)

            # Print the output and error messages from the cp command
            print("cp output:", cp_result.stdout)
            print("cp error:", cp_result.stderr)

            # Check if the cp command was successful
            if cp_result.returncode != 0:
                raise Exception(f"cp command failed with return code {cp_result.returncode}")

            copy_msg = "{} copied to iTunes directory {}. ".format(self.playlist_name + ".m3u", itunes_dir)

            # Run the VBScript with the playlist file as an argument
            # First, convert paths to Windows format
            vbscript_path = subprocess.run(["wslpath", "-w", str(Path(itunes_dir) / "ImportM3U.vbs")], capture_output=True, text=True).stdout.strip()
            playlist_path = subprocess.run(["wslpath", "-w", str(Path(itunes_dir) / (self.playlist_name + ".m3u"))], capture_output=True, text=True).stdout.strip()


            print("vbscript_path=", vbscript_path, "playlist_path=", playlist_path)
            vbscript_result = subprocess.run(["cmd.exe", "/c", "cscript", vbscript_path, playlist_path], capture_output=True, text=True)

            print("vbs output:", vbscript_result.stdout)
            print("vbs error:", vbscript_result.stderr)

            # Check for success
            if vbscript_result.returncode == 0:
                success = True
                result_message = copy_msg + "VBScript executed successfully."
            else:
                success = False
                result_message = copy_msg + "VBScript execution failed: " + vbscript_result.stderr

            return success, result_message
        except Exception as e:
            return False, str(e)