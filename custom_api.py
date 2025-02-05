import threading
import subprocess

def run_command(command):
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    print(f"Output: {result.stdout}")
    print(f"Error: {result.stderr}")

# Create and start thread
command = "python demo.py --video example/clip.mov --visualize"  # Example command
thread = threading.Thread(target=run_command, args=(command,))
thread.start()

# Wait for thread to complete
thread.join()

command = "ls /output/demo/clip"
run_command(command)