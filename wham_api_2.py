import subprocess
import threading
from pathlib import Path

class VideoProcessor:
    def __init__(
        self,
        wham_dir: str = "/home/ayush22126/WHAM",
        python_exec: str = "/home/ayush22126/miniconda3/envs/wham/bin/python",
        output_pth: str = None,
        calib: str = None,
        estimate_local_only: bool = False,
        visualize: bool = True,
        save_pkl: bool = False,
        run_smplify: bool = False
    ):
        """
        Initialize the VideoProcessor with WHAM configuration and parameters.

        Args:
            wham_dir (str): Path to the WHAM repository directory.
            python_exec (str): Path to the Python executable in the WHAM environment.
            output_pth (str, optional): Default output directory for results.
            calib (str, optional): Path to camera calibration file.
            estimate_local_only (bool): Only estimate local motion if True.
            visualize (bool): Enable visualization of the output mesh.
            save_pkl (bool): Save output as a .pkl file.
            run_smplify (bool): Run Temporal SMPLify for post-processing.
        """
        self.wham_dir = wham_dir
        self.python_exec = python_exec
        self.output_pth = output_pth
        self.calib = calib
        self.estimate_local_only = estimate_local_only
        self.visualize = visualize
        self.save_pkl = save_pkl
        self.run_smplify = run_smplify

        self.completed = False
        self.success = False
        self.output = ""
        self.error = ""
        self.thread = None
        self.completion_event = threading.Event()

    def process_video(self, video_path: str, callback: callable = None) -> None:
        """
        Start processing the video in a background thread.

        Args:
            video_path (str): Path to the input video file.
            callback (callable, optional): Function to call upon completion.
                Signature: callback(success: bool, output: str, error: str)
        """
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        self.completed = False
        self.success = False
        self.completion_event.clear()

        self.thread = threading.Thread(
            target=self._run_command,
            args=(video_path, callback),
            daemon=True
        )
        self.thread.start()

    def _run_command(self, video_path: str, callback: callable) -> None:
        """Internal method to execute the WHAM command."""
        try:
            command = [
                self.python_exec,
                "demo.py",
                "--video", video_path
            ]

            if self.output_pth:
                command.extend(["--output_pth", self.output_pth])
            if self.calib:
                command.extend(["--calib", self.calib])
            if self.estimate_local_only:
                command.append("--estimate_local_only")
            if self.visualize:
                command.append("--visualize")
            if self.save_pkl:
                command.append("--save_pkl")
            if self.run_smplify:
                command.append("--run_smplify")

            result = subprocess.run(
                command,
                cwd=self.wham_dir,
                capture_output=True,
                text=True,
                check=True
            )

            self.output = result.stdout
            self.error = result.stderr
            self.success = True

        except subprocess.CalledProcessError as e:
            self.output = e.stdout
            self.error = e.stderr
            self.success = False
        except Exception as e:
            self.error = str(e)
            self.success = False
        finally:
            self.completed = True
            self.completion_event.set()
            if callback:
                callback(self.success, self.output, self.error)

    def wait_until_complete(self, timeout: float = None) -> tuple:
        """
        Block until the processing completes or timeout occurs.

        Args:
            timeout (float, optional): Maximum time to wait in seconds.

        Returns:
            tuple: (success: bool, output: str, error: str)
        """
        self.completion_event.wait(timeout=timeout)
        return self.success, self.output, self.error

    def is_running(self) -> bool:
        """Check if processing is still running."""
        return not self.completed