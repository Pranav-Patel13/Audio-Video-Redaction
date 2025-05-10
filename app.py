from flask import Flask, request, send_file, render_template
from utils.ffmpeg_utils import final_redaction
import os

app = Flask(__name__)
UPLOAD_FOLDER = "uploads/"
RED_FOLDER = "static/redacted_videos/"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RED_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/redact', methods=['POST'])
def redact():
    video = request.files['video']
    json_file = request.files['json']
    words = request.form.get('words').split(',')
    # mode = request.form.get('mode', 'beep')

    video_path = os.path.join(UPLOAD_FOLDER, video.filename)
    json_path = os.path.join(UPLOAD_FOLDER, json_file.filename)
    output_path = os.path.join(RED_FOLDER, "4final_redacted.mp4")

    video.save(video_path)
    json_file.save(json_path)

    final_path = final_redaction(video_path, json_path, words, output_path)

    return send_file(final_path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=5013)