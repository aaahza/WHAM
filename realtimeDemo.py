import cv2
import numpy as np
import os
import tempfile
import time
import shutil
import threading
from queue import Queue
from datetime import datetime
from wham_api_2 import VideoProcessor

class WebcamProcessor:
    def __init__(self, webcam_id=0, clip_duration=1, fps=30, display_scale=0.7):
        self.webcam_id = webcam_id
        self.clip_duration = clip_duration
        self.target_fps = fps
        self.display_scale = display_scale
        
        self.cap = cv2.VideoCapture(self.webcam_id)
        self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        self.frames_buffer = []
        self.processing_queue = Queue(maxsize=2)
        self.current_output = None
        self.running = False
        self.current_temp_dir = None
        self.live_overlay = None
        
        # Initialize WHAM processor
        self.wham_processor = VideoProcessor(
            visualize=True,
            save_pkl=False,
            run_smplify=False
        )

    def start(self):
        self.running = True
        threading.Thread(target=self._capture_frames, daemon=True).start()
        threading.Thread(target=self._process_clips, daemon=True).start()
        self._display_loop()

    def _capture_frames(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                continue
                
            # Store frame and live overlay
            self.frames_buffer.append(frame)
            self.live_overlay = frame.copy()
            
            # Maintain buffer for 1 second + 1 extra second buffer
            if len(self.frames_buffer) > self.target_fps * (self.clip_duration + 1):
                self.frames_buffer.pop(0)

    def _create_clip(self):
        # Get last N frames for 1 second clip
        clip_frames = self.frames_buffer[-self.target_fps * self.clip_duration:]
        
        # Create temp directory
        temp_dir = tempfile.mkdtemp(prefix="wham_clip_")
        input_path = os.path.join(temp_dir, "input.mp4")
        
        # Save clip
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(
            input_path, 
            fourcc, 
            self.target_fps, 
            (self.frame_width, self.frame_height)
        )
        
        for frame in clip_frames:
            out.write(frame)
        out.release()
        
        return temp_dir, input_path

    def _process_clips(self):
        while self.running:
            if self.processing_queue.empty() and len(self.frames_buffer) >= self.target_fps * self.clip_duration:
                temp_dir, input_path = self._create_clip()
                output_dir = os.path.join(temp_dir, "output")
                os.makedirs(output_dir, exist_ok=True)
                
                self.processing_queue.put({
                    'temp_dir': temp_dir,
                    'input_path': input_path,
                    'output_dir': output_dir,
                    'timestamp': datetime.now()
                })
                
                # Process in background
                self.wham_processor.process_video(
                    input_path,
                    output_pth=output_dir,
                    callback=lambda success, out, err: self._processing_done(temp_dir, success)
                )
            time.sleep(0.1)

    def _processing_done(self, temp_dir, success):
        if success:
            output_path = os.path.join(temp_dir, "output", "input_vis.mp4")
            if os.path.exists(output_path):
                self.current_output = self._load_output_video(output_path)
        shutil.rmtree(temp_dir, ignore_errors=True)

    def _load_output_video(self, path):
        cap = cv2.VideoCapture(path)
        frames = []
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
        cap.release()
        return frames

    def _display_loop(self):
        while self.running:
            # Create main display frame
            display_frame = np.zeros((self.frame_height, self.frame_width * 2, 3), dtype=np.uint8)
            
            # Show live overlay (top-left corner)
            if self.live_overlay is not None:
                overlay = cv2.resize(self.live_overlay, (0,0), fx=0.3, fy=0.3)
                h, w = overlay.shape[:2]
                display_frame[:h, :w] = overlay
            
            # Show processed output
            if self.current_output is not None:
                current_frame_idx = min(int(time.time() * self.target_fps) % len(self.current_output), len(self.current_output)-1)
                processed_frame = self.current_output[current_frame_idx]
                
                # Resize to match original dimensions
                processed_frame = cv2.resize(processed_frame, (self.frame_width, self.frame_height))
                
                # Combine input and output
                display_frame[:, :self.frame_width] = self.frames_buffer[-1] if self.frames_buffer else np.zeros_like(display_frame[:, :self.frame_width])
                display_frame[:, self.frame_width:] = processed_frame
            
            # Resize for display
            final_display = cv2.resize(display_frame, (0,0), fx=self.display_scale, fy=self.display_scale)
            cv2.imshow('WHAM Real-time Processing', final_display)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                self.running = False
                break

        self.cap.release()
        cv2.destroyAllWindows()
        if self.current_temp_dir and os.path.exists(self.current_temp_dir):
            shutil.rmtree(self.current_temp_dir)

if __name__ == "__main__":
    processor = WebcamProcessor(
        webcam_id=0,
        clip_duration=1,  # 1 second clips
        fps=30,           # Target processing FPS
        display_scale=0.7 # Adjust based on your monitor size
    )
    processor.start()