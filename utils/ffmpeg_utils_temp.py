import os
import json
import string
import ffmpeg
import cv2
import re
import datetime
import time
import shutil  # new import for file copy

TEMP_SEGMENT_FOLDER = "temp/segments/"
TEMP_AUDIO_FOLDER = "temp/audio/"

os.makedirs(TEMP_SEGMENT_FOLDER, exist_ok=True)
os.makedirs(TEMP_AUDIO_FOLDER, exist_ok=True)

def get_redacted_timestamps(json_path, sensitive_words):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    redacted_timestamps = []

    for segment in data:
        for word_info in segment.get("words", []):
            word = word_info["word"].strip().strip(string.punctuation).lower()
            if word in [w.lower() for w in sensitive_words]:
                redacted_timestamps.append((word_info["start"], word_info["end"]))

    return redacted_timestamps

def generate_segments(redacted_segments, total_duration):
    segments = []
    last_end = 0.0
    for start, end in sorted(redacted_segments):
        if last_end < start:
            segments.append(('keep', last_end, start))
        segments.append(('redact', start, end))
        last_end = end
    if last_end < total_duration:
        segments.append(('keep', last_end, total_duration))
    return segments

def create_video_segment(input_video, start, end, output_path):
    try:
        (
            ffmpeg
            .input(input_video, ss=start, to=end)
            .output(output_path, vcodec='libx264', pix_fmt='yuv420p', acodec='aac')
            .run(overwrite_output=True)
        )
        print(f"Segment created: {output_path}")
    except ffmpeg.Error as e:
        print("ffmpeg error:", e.stderr.decode('utf-8') if e.stderr else 'No stderr')

def convert_to_ts(input_file, ts_output):
    try:
        (
            ffmpeg
            .input(input_file)
            .output(ts_output, format='mpegts', vcodec='libx264', acodec='aac', preset="ultrafast", pix_fmt='yuv420p')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        print("TS file created:", ts_output)
    except ffmpeg.Error as e:
        print("FFmpeg error (convert_to_ts):", e.stderr.decode() if e.stderr else "unknown error")

def wait_for_file(path, timeout=5):
    start_time = time.time()
    while not os.path.exists(path):
        if time.time() - start_time > timeout:
            raise FileNotFoundError(f"Timeout waiting for file: {path}")
        time.sleep(0.1)

def concatenate_segments(segment_files, output_path):
    ts_files = []
    for file in segment_files:
        if not os.path.exists(file):
            print(f"Missing segment file: {file}")
            continue
        ts_file = file.replace(".mp4", ".ts")
        convert_to_ts(file, ts_file)
        wait_for_file(ts_file)
        ts_files.append(ts_file)

    if not ts_files:
        print("No segments to concatenate.")
        return

    input_str = '|'.join(ts_files)
    try:
        (
            ffmpeg
            .input(f"concat:{input_str}")
            .output(output_path, c="copy", format="mp4")
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        print("Final video created at:", output_path)
    except ffmpeg.Error as e:
        print("FFmpeg concat error:", e.stderr.decode() if e.stderr else "Unknown error")

def final_redaction(video_path, json_path, redaction_list, output_path):
    print(datetime.datetime.now())
    redaction_times = get_redacted_timestamps(json_path, redaction_list)
    print("Redacted times:", redaction_times)

    cap = cv2.VideoCapture(video_path)
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    segments = generate_segments(redaction_times, duration)
    segment_files = []

    for i, (segment_type, start, end) in enumerate(segments):
        print(f"Processing segment {i} - Type: {segment_type} | {start:.2f} to {end:.2f}")
        filename = os.path.join(TEMP_SEGMENT_FOLDER, f"01segment_{i}.mp4")
        if segment_type == "keep":
            create_video_segment(video_path, start, end, filename)
        else:
            # Just copy your already-prepared redacted clip
            shutil.copy("assets/redacted_clip.mp4", filename)
            print(f"Redacted segment added from existing clip: {filename}")
        segment_files.append(filename)

    concatenate_segments(segment_files, output_path)
    print(datetime.datetime.now())
    return output_path

if __name__ == "__main__":
    video_path = "input/video_input.mp4"  # Path to your input video
    json_path = "input/updated_transcription.json"  # Path to your transcription file
    output_path = "output/01final_redacted.mp4"
    redaction_words = ["Georgia", "English" , "learning"]  # Example redaction words

    os.makedirs("output", exist_ok=True)
    final_video = final_redaction(video_path, json_path, redaction_words, output_path)
    print(f"\n✅ Final redacted video saved at: {final_video}")