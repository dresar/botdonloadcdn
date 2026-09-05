import os
import sys
import csv
import json
import shutil
import subprocess
from time import time
from PIL import Image, ImageDraw
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

INPUT_DIR = "downloads_kucing_hd"
OUTPUT_DIR = "kucing"
MAX_WORKERS = 8

LOGO_TOP_RIGHT_SRC = "ChatGPT Image 5 Agu 2026, 13.33.24.png"

# Resolve bottom banner logo dynamically
LOGO_BOTTOM_SRC = "ChatGPT Image 5 Agu 2026, 13.35.25 copy.png"
if not os.path.exists(LOGO_BOTTOM_SRC):
    LOGO_BOTTOM_SRC = "ChatGPT Image 5 Agu 2026, 13.35.25.png"

# Fixed 9:16 Canvas Standard for TikTok & Meta Reels
CANVAS_W = 1080
CANVAS_H = 1920
MAX_VIDEO_W = 920
MAX_VIDEO_H = 1420

def prepare_logo(image_path, target_width=None, target_height=None):
    im = Image.open(image_path).convert("RGBA")
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
        
    orig_w, orig_h = im.size
    if target_width and not target_height:
        target_height = int(orig_h * (target_width / orig_w))
    elif target_height and not target_width:
        target_width = int(orig_w * (target_height / orig_h))
        
    im = im.resize((target_width, target_height), Image.LANCZOS)
    return im

def get_or_create_mask(width, height, radius, masks_dir="temp_assets"):
    os.makedirs(masks_dir, exist_ok=True)
    mask_path = os.path.join(masks_dir, f"mask_{width}x{height}_r{radius}.png")
    
    if not os.path.exists(mask_path):
        mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle([0, 0, width, height], radius=radius, fill=255)
        mask.save(mask_path)
        
    return mask_path

def inspect_media(filepath):
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        filepath
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        try:
            return json.loads(res.stdout)
        except Exception:
            pass
    return {}

def check_faststart(filepath):
    try:
        with open(filepath, "rb") as f:
            header = f.read(2 * 1024 * 1024)
            moov_pos = header.find(b"moov")
            mdat_pos = header.find(b"mdat")
            if moov_pos != -1 and mdat_pos != -1:
                return moov_pos < mdat_pos
            elif moov_pos != -1:
                return True
    except Exception:
        pass
    return False

def encode_kucing_super_hd(input_path, output_path, logo2_path, logo1_path):
    meta_info = inspect_media(input_path)
    streams = meta_info.get("streams", [])
    
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    orig_w = int(v_stream.get("width", 720))
    orig_h = int(v_stream.get("height", 1280))

    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    scale = min(MAX_VIDEO_W / orig_w, MAX_VIDEO_H / orig_h)
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)
    if new_w % 2 != 0: new_w -= 1
    if new_h % 2 != 0: new_h -= 1

    v_x = (CANVAS_W - new_w) // 2
    v_y = 180 + ((MAX_VIDEO_H - new_h) // 2)

    mask_path = get_or_create_mask(new_w, new_h, 50)

    logo2_img = Image.open(logo2_path)
    logo1_img = Image.open(logo1_path)

    logo2_x = CANVAS_W - logo2_img.width - 30
    logo2_y = 25
    
    logo1_x = (CANVAS_W - logo1_img.width) // 2
    logo1_y = CANVAS_H - logo1_img.height - 35

    filter_complex = (
        f"[0:v]scale={new_w}:{new_h}[vid_scaled];"
        f"[vid_scaled][1:v]alphamerge[vid_rounded];"
        f"color=c=white:s={CANVAS_W}x{CANVAS_H}[canvas0];"
        f"[canvas0][vid_rounded]overlay={v_x}:{v_y}[canvas1];"
        f"[canvas1][2:v]overlay={logo2_x}:{logo2_y}[canvas2];"
        f"[canvas2][3:v]overlay={logo1_x}:{logo1_y}[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-i", mask_path,
        "-i", logo2_path,
        "-i", logo1_path
    ]

    if not has_audio:
        cmd.extend([
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"
        ])
        audio_map = ["-map", "4:a"]
    else:
        audio_map = ["-map", "0:a"]

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[out]",
    ])
    cmd.extend(audio_map)

    cmd.extend([
        "-shortest",
        # Video encoding parameters (Super HD Quality, Strict TikTok & Meta Spec)
        "-c:v", "libx264",
        "-profile:v", "high",
        "-level:v", "4.1",
        "-pix_fmt", "yuv420p",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-r", "30",
        "-fps_mode", "cfr",
        "-preset", "medium",
        "-crf", "17",  # Ultra High Definition Quality
        # Audio encoding parameters (High Quality 192kbps)
        "-c:a", "aac",
        "-profile:a", "aac_low",
        "-ar", "48000",
        "-ac", "2",
        "-b:a", "192k",
        # Faststart & Clean Metadata
        "-movflags", "+faststart",
        "-map_metadata", "-1",
        "-fflags", "+bitexact",
        output_path
    ])

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode == 0:
        now_ts = time()
        os.utime(output_path, (now_ts, now_ts))
        return True, ""
    else:
        return False, res.stderr

def validate_kucing_compliance(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return False, {"error": "File does not exist or 0 bytes"}

    info = inspect_media(filepath)
    format_info = info.get("format", {})
    streams = info.get("streams", [])

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not v_stream:
        return False, {"error": "Missing video stream"}

    errors = []

    width = int(v_stream.get("width", 0))
    height = int(v_stream.get("height", 0))

    if width != 1080 or height != 1920:
        errors.append(f"Invalid resolution: {width}x{height} (expected 1080x1920)")

    v_codec = v_stream.get("codec_name", "")
    if v_codec.lower() != "h264":
        errors.append(f"Invalid video codec: {v_codec}")

    profile = v_stream.get("profile", "")
    pix_fmt = v_stream.get("pix_fmt", "")

    if "High" not in profile:
        errors.append(f"Invalid profile: {profile}")

    if pix_fmt != "yuv420p":
        errors.append(f"Invalid pixel format: {pix_fmt}")

    r_frame_rate = v_stream.get("r_frame_rate", "0/1")
    try:
        num, den = map(int, r_frame_rate.split("/"))
        fps = num / den if den > 0 else 0
        if fps > 30.5:
            errors.append(f"Frame rate too high: {fps:.2f} fps")
    except Exception:
        fps = 30.0

    if not a_stream:
        errors.append("Missing audio stream")
        a_codec = "None"
        a_sample_rate = 0
    else:
        a_codec = a_stream.get("codec_name", "")
        a_sample_rate = int(a_stream.get("sample_rate", 0))

        if a_codec.lower() != "aac":
            errors.append(f"Invalid audio codec: {a_codec}")
        if a_sample_rate != 48000:
            errors.append(f"Invalid audio sample rate: {a_sample_rate} Hz")

    is_faststart = check_faststart(filepath)
    if not is_faststart:
        errors.append("Faststart inactive")

    duration = float(format_info.get("duration", 0))
    file_size = int(format_info.get("size", 0))

    is_valid = len(errors) == 0
    error_msg = "; ".join(errors) if errors else "None"

    details = {
        "Codec Video": v_codec,
        "Codec Audio": a_codec,
        "Resolution": f"{width}x{height}",
        "Frame Rate": f"{fps:.2f}",
        "Pixel Format": pix_fmt,
        "Profile": profile,
        "Audio Sample Rate": f"{a_sample_rate} Hz",
        "File Size": f"{file_size / (1024*1024):.2f} MB",
        "Duration": f"{duration:.2f}s",
        "Faststart": "Ya" if is_faststart else "Tidak",
        "Valid Meta & TikTok": "Ya" if is_valid else "Tidak",
        "Error": error_msg
    }

    return is_valid, details

def process_single_task(task):
    input_path = task["input_path"]
    output_path = task["output_path"]
    logo2_path = task["logo2_path"]
    logo1_path = task["logo1_path"]
    filename = os.path.basename(output_path)

    success, err_msg = encode_kucing_super_hd(input_path, output_path, logo2_path, logo1_path)
    
    if not success:
        return {
            "Nama File": filename,
            "Status Encoding": "Gagal",
            "Codec Video": "N/A",
            "Codec Audio": "N/A",
            "Resolution": "N/A",
            "Frame Rate": "N/A",
            "Pixel Format": "N/A",
            "Profile": "N/A",
            "Audio Sample Rate": "N/A",
            "File Size": "0 MB",
            "Duration": "0s",
            "Faststart": "Tidak",
            "Valid Meta & TikTok (Ya/Tidak)": "Tidak",
            "Catatan Error bila ada": f"FFmpeg error: {err_msg[:100]}"
        }

    is_valid, val_details = validate_kucing_compliance(output_path)

    return {
        "Nama File": filename,
        "Status Encoding": "Berhasil" if is_valid else "Gagal Validasi",
        "Codec Video": val_details["Codec Video"],
        "Codec Audio": val_details["Codec Audio"],
        "Resolution": val_details["Resolution"],
        "Frame Rate": val_details["Frame Rate"],
        "Pixel Format": val_details["Pixel Format"],
        "Profile": val_details["Profile"],
        "Audio Sample Rate": val_details["Audio Sample Rate"],
        "File Size": val_details["File Size"],
        "Duration": val_details["Duration"],
        "Faststart": val_details["Faststart"],
        "Valid Meta & TikTok (Ya/Tidak)": val_details["Valid Meta & TikTok"],
        "Catatan Error bila ada": val_details["Error"]
    }

def main():
    print("[+] Preparing Kucing Super HD production environment...")
    print(f"[+] Using Top Right Logo : {LOGO_TOP_RIGHT_SRC}")
    print(f"[+] Using Bottom Banner  : {LOGO_BOTTOM_SRC}")

    os.makedirs("temp_assets", exist_ok=True)

    logo_top_right = prepare_logo(LOGO_TOP_RIGHT_SRC, target_width=210)
    logo2_path = "temp_assets/logo_top_right.png"
    logo_top_right.save(logo2_path)

    logo_bottom = prepare_logo(LOGO_BOTTOM_SRC, target_width=750)
    logo1_path = "temp_assets/logo_bottom.png"
    logo_bottom.save(logo1_path)

    if not os.path.exists(INPUT_DIR):
        print(f"[ERROR] Input directory '{INPUT_DIR}' not found!")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    v_files = sorted([f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".mp4")])
    tasks = []

    for idx, filename in enumerate(v_files, 1):
        out_name = f"Kucing_HD_{idx:03d}.mp4"
        tasks.append({
            "input_path": os.path.join(INPUT_DIR, filename),
            "output_path": os.path.join(OUTPUT_DIR, out_name),
            "logo2_path": logo2_path,
            "logo1_path": logo1_path
        })

    total_tasks = len(tasks)
    print(f"[+] Total Kucing HD videos queued for processing: {total_tasks}")
    print(f"[+] Output Directory: {OUTPUT_DIR}/")
    print(f"[+] Quality Setting : Super HD (CRF 17, 1080x1920)")
    print(f"[+] Starting batch processing with {MAX_WORKERS} parallel workers...\n")

    start_time = time()
    report_rows = []
    success_count = 0
    failed_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_single_task, t): t for t in tasks}

        for idx, future in enumerate(as_completed(futures), 1):
            row = future.result()
            report_rows.append(row)
            status = row["Status Encoding"]
            filename = row["Nama File"]
            valid_meta = row["Valid Meta & TikTok (Ya/Tidak)"]

            if status == "Berhasil" and valid_meta == "Ya":
                success_count += 1
                print(f"[{idx}/{total_tasks}] [OK] Encoded Super HD 1080x1920: {filename}")
            else:
                failed_count += 1
                err = row.get("Catatan Error bila ada", "Validation Failed")
                print(f"[{idx}/{total_tasks}] [FAIL] ({filename}): {err}")

    csv_file = "kucing_encoding_report.csv"
    headers = [
        "Nama File", "Status Encoding", "Codec Video", "Codec Audio", "Resolution",
        "Frame Rate", "Pixel Format", "Profile", "Audio Sample Rate",
        "File Size", "Duration", "Faststart", "Valid Meta & TikTok (Ya/Tidak)", "Catatan Error bila ada"
    ]

    report_rows.sort(key=lambda x: x["Nama File"])
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(report_rows)

    elapsed = time() - start_time
    print("\n" + "=" * 60)
    print("KUCING SUPER HD ALL-IN-ONE PROCESSING SUMMARY")
    print("=" * 60)
    print(f"Successfully Processed Super HD : {success_count}")
    print(f"Failed / Incompatible           : {failed_count}")
    print(f"Total time taken                : {elapsed:.2f} seconds")
    print(f"CSV Audit Report Saved          : {os.path.abspath(csv_file)}")
    print(f"Output Directory                : '{OUTPUT_DIR}/'")
    print("=" * 60)

    if os.path.exists("temp_assets"):
        shutil.rmtree("temp_assets", ignore_errors=True)

if __name__ == "__main__":
    main()
