from flask import Flask, request, send_file
import tempfile
import os
from wham_api_2 import VideoProcessor

app = Flask(__name__)
wham_processor = VideoProcessor(visualize=True)

@app.route('/process', methods=['POST'])
def process_video():
    # Create temp directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save received video
        video_path = os.path.join(temp_dir, 'input.mp4')
        request.files['video'].save(video_path)
        
        # Process with WHAM
        output_dir = os.path.join(temp_dir, 'output')
        success, _, _ = wham_processor.process_video(
            video_path,
            output_pth=output_dir
        )
        wham_processor.wait_until_complete()
        
        # Return processed video
        output_path = os.path.join(output_dir, 'input_vis.mp4')
        return send_file(output_path, mimetype='video/mp4')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)