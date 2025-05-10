import glob
import os
import json
import string
import subprocess
import ffmpeg
import cv2
import datetime
from pydub import AudioSegment
from pydub.generators import Sine


TEMP_SEGMENT_FOLDER = "temp/segments/"
TEMP_AUDIO_FOLDER = "temp/audio/"

os.makedirs(TEMP_SEGMENT_FOLDER, exist_ok=True)
os.makedirs(TEMP_AUDIO_FOLDER, exist_ok=True)

# def get_redacted_timestamps(json_path, redaction_list, redact_phone, redact_email, redact_ssn):
""" {get_redacted_timestamps} it generates the list of timestamps (starting time and ending time) for the given video. """

def get_redacted_timestamps(json_path, speaker_to_redact=None, redaction_list=None):
    with open(json_path, "r", encoding="utf-8") as file:
        data = json.load(file)

    redacted_timestamps = []
    cleaned_redaction_list = [word_in_list.strip(string.punctuation).lower() for word_in_list in redaction_list]

    # phone_regex = re.compile(r"\b(?:\+?\d{1,3})?[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,5}[-.\s]?\d{4}\b")
    # email_regex = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
    # ssn_regex = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

    for segment in data:
        print(segment)
        # print(segment["speaker"])
        # if segment["speaker"] == ""
        if speaker_to_redact and segment.get("speaker", "").lower() == speaker_to_redact.lower():
            redacted_timestamps.append((segment["start_time"], segment["end_time"]))
        elif redaction_list:
            for word_info in segment.get("words", []):
                word = word_info["word"].strip().strip(string.punctuation).lower()
                if word in [w.lower() for w in cleaned_redaction_list]:
                    redacted_timestamps.append((word_info["start"], word_info["end"]))
    return redacted_timestamps


""" {generate_segments} it makes list of segments with label 'keep' and 'redact' of the given list of redacted timestamps """

def generate_segments(redacted_segments, total_duration):
    segments = []
    last_end = 0.0

    for start, end in redacted_segments:
        if last_end < start:
            segments.append(('keep', last_end, start))
        segments.append(('redact', start, end))
        last_end = end

    if last_end < total_duration:
        segments.append(('keep', last_end, total_duration))
    return segments


""" {create_video_segment} it finally generates segments(clips) of the origional video using ffmpeg """

def create_video_segment(input_video, start, end, output_path):
    try:
        (
            ffmpeg
            .input(input_video, ss=start, to=end)
            .output(output_path, vcodec='libx264', pix_fmt='yuv420p', acodec='aac', audio_bitrate='192k', r=30,
                    ar=44100)
            .run(overwrite_output=True)
        )
        print(f"Segment created: {output_path}")
    except ffmpeg.Error as e:
        stderr = e.stderr.decode('utf-8') if e.stderr else 'No stderr available'
        print("ffmpeg error:", stderr)


""" {insert_redacted_segment} it puts the redacted clip provided by the user on the places of the sensitive part """

def insert_redacted_segment(output_path, duration, redacted_clip_path="assets/redacted_clip.mp4"):
    try:
        (
            ffmpeg
            .input(redacted_clip_path)
            .output(output_path, t=duration, vcodec='libx264', pix_fmt='yuv420p', acodec='aac', audio_bitrate='192k',
                    r=30, ar=44100)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        print("Redacted segment created at:", output_path)
    except ffmpeg.Error as e:
        print("FFmpeg error (insert_redacted_segment):", e.stderr.decode() if e.stderr else "unknown error")


""" {clean_temp_segments} it will clean(remove) the temporary generated mp4 segments after final merged video is generated """

def clean_temp_segments(TEMP_SEGMENT_FOLDER, extentions=[".ts", ".mp4", ".txt"]):
    for ext in extentions:
        for file in glob.glob(os.path.join(TEMP_SEGMENT_FOLDER, f"*{ext}")):
            try:
                os.remove(file)
                print(f"deleted temp file: {file}")
            except Exception as e:
                print(f"Error deleting file {file}: {e}")


""" {concatenate_segments} it will handle the generated video segments and merge them to produce the final video """

import os
import subprocess

def concatenate_segments(segment_files, output_path):
    concat_list_path = os.path.join(TEMP_SEGMENT_FOLDER, "concat_list.txt")

    # Validate all segments exist
    missing_files = []
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for file in segment_files:
            if not os.path.exists(file):
                print(f"[ERROR] Missing segment: {file}")
                missing_files.append(file)
                continue  # Skip writing it to the list

            abs_path = os.path.abspath(file).replace("\\", "/")
            f.write(f"file '{abs_path}'\n")

    # Abort if any segment was missing
    if missing_files:
        print(f"[FATAL] {len(missing_files)} segment(s) missing. Aborting concatenation.")
        return

    # Run FFmpeg concat
    command = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_path,
        "-c", "copy",
        output_path
    ]

    print("[INFO] Running FFmpeg concat subprocess...")
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if result.returncode != 0:
        print("[ERROR] FFmpeg concat failed.")
        print(result.stderr.decode())
    else:
        print("[SUCCESS] Concatenation complete:", output_path)
        clean_temp_segments(TEMP_SEGMENT_FOLDER)  # Clean segments after success

""" {video_redaction_pipeline} it will call all the sub process of video redaction one by one sequentially """

def video_redaction_pipeline(video_path, json_path, redaction_list, output_path, speaker_to_redact):
    print(datetime.datetime.now())
    redaction_times = get_redacted_timestamps(json_path, speaker_to_redact, redaction_list)
    print("Redacted times:", redaction_times)

    cap = cv2.VideoCapture(video_path)
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    segments = generate_segments(redaction_times, duration)

    segment_files = []
    for i, (segment_type, start, end) in enumerate(segments):
        print(f"processing segment {i} - Type: {segment_type} | {start:.2f} to {end:.2f}")
        filename = os.path.join(TEMP_SEGMENT_FOLDER, f"01_segment_{i}.mp4")
        if segment_type == "keep":
            create_video_segment(video_path, start, end, filename)
        else:
            insert_redacted_segment(filename, duration=(end - start), redacted_clip_path="assets/redacted_clip.mp4")
        segment_files.append(filename)
    # print(segment_files)
    concatenate_segments(segment_files, output_path)
    print(datetime.datetime.now())
    # return output_path
    print("Redacted Video saved at : ", output_path)


""" {get_redacted_audio_timestamps} it will generate the list of segments(start and end) time of the sensitive words """

def get_redacted_audio_timestamps(json_path, redaction_list):
    with open(json_path, "r", encoding="utf-8") as file:
        data = json.load(file)

    redacted_segments = []
    cleaned_redaction_list = [r.strip(string.punctuation).lower() for r in redaction_list]

    for segment in data:
        for word_info in segment.get("words", []):
            word = word_info["word"].strip().strip(string.punctuation).lower()
            if word in [w.lower() for w in cleaned_redaction_list]:
                redacted_segments.append((word_info["start"], word_info["end"]))
    return redacted_segments


""" {audio_redaction_pipeline} it will generate final redacted audio using redacted timestamps form the list """

def audio_redaction_pipeline(input_path, json_path, redaction_list, output_path):
    print("Start:", datetime.datetime.now())
    audio = AudioSegment.from_file(input_path)
    duration_ms = len(audio)
    redacted_timestamps = get_redacted_audio_timestamps(json_path, redaction_list)
    print(redacted_timestamps)

    output_audio = AudioSegment.empty()
    last_end_ms = 0

    for start, end in redacted_timestamps:
        print("redacting segment : ", {start}, " | ", {end})
        start_ms = int(start * 1000)
        end_ms = int(end * 1000)

        if last_end_ms < start_ms:
            output_audio += audio[last_end_ms:start_ms]

        duration = end_ms - start_ms
        if duration > 0:
            beep = Sine(1000).to_audio_segment(duration=duration).apply_gain(-3)
            output_audio += beep

        last_end_ms = end_ms
        if last_end_ms < duration_ms:
            output_audio += audio[last_end_ms:]

        output_audio.export(output_path, format="mp3")
    print("Redacted Audio saved at : ", output_path)
    print(datetime.datetime.now())


""" {handle_redaction} it will run process of audio and video based on extension(.mp3, .mp4, .wav, .avi, .mov) of file provided by the user """

def handle_redaction(input_path, json_path, redaction_list, output_path, speaker_to_redact):
    ext = os.path.splitext(input_path)[1].lower()
    if ext in [".mp3", ".wav"]:
        print("processing audio redaction.")
        audio_redaction_pipeline(input_path, json_path, redaction_list, output_path)
        print("process ended.")

    elif ext in [".mp4", ".ts", ".mov"]:
        print("processing video redaction.")
        video_redaction_pipeline(input_path, json_path, redaction_list, output_path, speaker_to_redact)
        print("process ended.")
    else:
        print("unsupported file format.")
    return output_path

# json_path = "D:/TJAVA03/final_input/mandela_elon_steve.json"
# redaction_list = ["sport", "inspire.", "breakthrough"]

# redacted_times = get_redacted_timestamps(json_path, redaction_list)
# print(redacted_times)

# input_path = "D:/Study/Knovos_Company/Audio_Video_Redaction/segment_based_redaction/input/2_video_input.mp4"
# json_path = "D:/Study/Knovos_Company/Audio_Video_Redaction/segment_based_redaction/input/updated_PII_transcription.json"
# redaction_list=["Anderson","joeanderson","verification"]
output_paths="D:/Study/Knovos_Company/Audio_Video_Redaction/segment_based_redaction/output/14_redacted_video.mp4"
# speaker_to_redact=""

# concatenate_segments(['temp/segments/022_segment_0.mp4', 'temp/segments/022_segment_1.mp4', 'temp/segments/022_segment_2.mp4', 'temp/segments/022_segment_3.mp4', 'temp/segments/022_segment_4.mp4', 'temp/segments/022_segment_5.mp4', 'temp/segments/022_segment_6.mp4'],output_path=output_path)

path = handle_redaction(input_path = "D:/Study/Knovos_Company/Audio_Video_Redaction/segment_based_redaction/input/PII_video_input.mp4", json_path = "D:/Study/Knovos_Company/Audio_Video_Redaction/segment_based_redaction/input/updated_PII_transcription.json", redaction_list=["Anderson","joeanderson","verification"], output_path=output_paths, speaker_to_redact="")
print("process completed successfully...",path)