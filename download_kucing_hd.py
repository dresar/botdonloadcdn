import json
import os
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure UTF-8 console output for Windows
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

DEFAULT_JSON_FILE = 'kucing2.json'
OUTPUT_DIR = 'downloads_kucing_hd'
MAX_WORKERS = 10
MAX_RETRIES = 3

FALLBACK_DOMAINS = [
    'scontent.cdninstagram.com',
    'scontent-iad3-1.cdninstagram.com',
    'scontent-iad3-2.cdninstagram.com',
    'scontent-iad6-1.cdninstagram.com',
    'instagram.fna.fbcdn.net'
]

def is_suitable_for_meta(item):
    """
    Checks if a video item is suitable for Meta (Instagram Reels / Facebook Reels):
    1. Must contain a valid video URL or video versions.
    2. Video duration must be within valid Reels range (0.5s to 900s / 15 minutes).
    3. Post type must be reel or video (not photo-only).
    """
    has_video = bool(item.get('video_url') or item.get('video_versions'))
    if not has_video:
        return False, "No video URL or versions found"

    duration = item.get('duration', 0)
    if duration and (duration < 0.5 or duration > 900):
        return False, f"Invalid duration for Reels ({duration:.1f}s)"

    post_type = item.get('post_type', 'reel').lower()
    if post_type not in ('reel', 'video', 'clips', 'clip'):
        return False, f"Unsupported post type for Meta ({post_type})"

    return True, "Valid Meta Reels Candidate"

def extract_dash_candidates(raw_data):
    dash_manifest = raw_data.get('video_dash_manifest') if isinstance(raw_data, dict) else None
    candidates = []
    if not dash_manifest:
        return candidates

    try:
        root = ET.fromstring(dash_manifest)
        for rep in root.iter('{urn:mpeg:dash:schema:mpd:2011}Representation'):
            w = rep.attrib.get('width')
            h = rep.attrib.get('height')
            bw = rep.attrib.get('bandwidth')
            base_url_elem = rep.find('{urn:mpeg:dash:schema:mpd:2011}BaseURL')
            if base_url_elem is not None and base_url_elem.text:
                candidates.append({
                    'url': base_url_elem.text,
                    'width': int(w) if w else 0,
                    'height': int(h) if h else 0,
                    'bandwidth': int(bw) if bw else 0
                })
    except Exception:
        pass
    return candidates

def get_hd_video_candidates(item):
    """
    Extracts all video URL candidates and sorts them by highest HD resolution (width*height) 
    and bandwidth descending.
    """
    candidates = []
    
    # 1. From video_versions (Primary source for HD video streams)
    versions = item.get('video_versions') or []
    for v in versions:
        if v.get('url'):
            candidates.append({
                'url': v['url'],
                'width': v.get('width', 0),
                'height': v.get('height', 0),
                'bandwidth': v.get('bandwidth', 0)
            })

    # 2. From raw_data -> video_dash_manifest
    raw_data = item.get('raw_data', {})
    dash_cands = extract_dash_candidates(raw_data)
    candidates.extend(dash_cands)

    # 3. From item video_url
    if item.get('video_url'):
        candidates.append({
            'url': item['video_url'],
            'width': 0,
            'height': 0,
            'bandwidth': 0
        })

    if not candidates:
        return []

    # Sort candidates by HD resolution (width*height) descending, then bandwidth descending
    candidates.sort(key=lambda c: (c['width'] * c['height'], c['bandwidth']), reverse=True)
    return candidates

def download_with_fallback(url, filepath):
    parsed = urllib.parse.urlparse(url)
    original_netloc = parsed.netloc

    urls_to_try = [url]
    for domain in FALLBACK_DOMAINS:
        if domain != original_netloc:
            alt_url = urllib.parse.urlunparse(parsed._replace(netloc=domain))
            urls_to_try.append(alt_url)

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    last_err = "Unknown connection error"

    for current_url in urls_to_try:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(current_url, headers=headers)
                with urllib.request.urlopen(req, timeout=25) as response, open(filepath, 'wb') as out_file:
                    buffer_size = 64 * 1024
                    while True:
                        chunk = response.read(buffer_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                
                filesize = os.path.getsize(filepath)
                if filesize > 0:
                    return True, filesize, "Success"
                else:
                    if os.path.exists(filepath):
                        os.remove(filepath)
            except Exception as e:
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                last_err = str(e)
            time.sleep(0.5 * attempt)

    return False, 0, f"Failed across all domains. Last error: {last_err}"

def download_video(item_info):
    idx, item = item_info
    code = item.get('code', f'unknown_{idx}')

    # Check Meta suitability before downloading
    suitable, reason = is_suitable_for_meta(item)
    if not suitable:
        return idx, code, False, 0, f"Rejected for Meta: {reason}", 0, 0, False

    candidates = get_hd_video_candidates(item)
    if not candidates:
        return idx, code, False, 0, "No valid HD video URL", 0, 0, True

    best_candidate = candidates[0]
    width = best_candidate['width']
    height = best_candidate['height']

    filename = f"{idx:03d}_{code}.mp4"
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    # Skip if already downloaded and non-empty
    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        return idx, code, True, os.path.getsize(filepath), "Already exists", width, height, True

    # Try downloading best HD candidate, or fallback to other candidates if fails
    for cand in candidates:
        success, filesize, msg = download_with_fallback(cand['url'], filepath)
        if success:
            return idx, code, True, filesize, "Success", cand['width'], cand['height'], True

    return idx, code, False, 0, msg, width, height, True

def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_JSON_FILE

    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found!")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total_items = len(data)
    print(f"==================================================")
    print(f"Starting HD Video Downloader for {total_items} Videos")
    print(f"Source JSON      : {json_path}")
    print(f"Output Directory : {OUTPUT_DIR}/")
    print(f"Meta Filter      : Active (Skipping unsuitable Meta videos)")
    print(f"Parallel Workers : {MAX_WORKERS}")
    print(f"==================================================")

    start_time = time.time()
    completed_count = 0
    failed_count = 0
    skipped_count = 0
    rejected_meta_count = 0
    total_bytes = 0
    results_log = []

    items = list(enumerate(data, start=1))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_video, item): item[0] for item in items}
        
        for future in as_completed(futures):
            idx, code, success, filesize, msg, w, h, suitable = future.result()
            res_str = f"{w}x{h}" if w and h else "HD/Original"
            
            if not suitable:
                rejected_meta_count += 1
                status_symbol = "REJECT_META"
            elif success:
                total_bytes += filesize
                if msg == "Already exists":
                    skipped_count += 1
                    status_symbol = "SKIP"
                else:
                    completed_count += 1
                    status_symbol = "OK"
            else:
                failed_count += 1
                status_symbol = "FAIL"
            
            processed = completed_count + skipped_count + failed_count + rejected_meta_count
            mb_size = filesize / (1024 * 1024)
            print(f"[{processed}/{total_items}] [{status_symbol}] #{idx:03d} ({code}) [{res_str}] - {mb_size:.2f} MB - {msg}")
            
            results_log.append({
                "index": idx,
                "code": code,
                "success": success,
                "meta_suitable": suitable,
                "resolution": res_str,
                "size_bytes": filesize,
                "message": msg
            })

    elapsed_time = time.time() - start_time
    total_mb = total_bytes / (1024 * 1024)
    speed_mbps = (total_mb / elapsed_time) if elapsed_time > 0 else 0

    print(f"\n==================================================")
    print(f"DOWNLOAD & META FILTERING COMPLETE!")
    print(f"Total Videos Processed     : {total_items}")
    print(f"Newly Downloaded (HD)     : {completed_count}")
    print(f"Skipped (Already Existed) : {skipped_count}")
    print(f"Rejected (Not Meta Valid)  : {rejected_meta_count}")
    print(f"Failed Downloads           : {failed_count}")
    print(f"Total Data Downloaded     : {total_mb:.2f} MB")
    print(f"Total Time Taken           : {elapsed_time:.2f} seconds")
    print(f"Average Download Speed     : {speed_mbps:.2f} MB/s")
    print(f"==================================================")

    summary_file = os.path.join(OUTPUT_DIR, 'download_summary.json')
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump({
            "total_items": total_items,
            "newly_downloaded": completed_count,
            "skipped": skipped_count,
            "rejected_meta": rejected_meta_count,
            "failed": failed_count,
            "total_mb": round(total_mb, 2),
            "elapsed_seconds": round(elapsed_time, 2),
            "details": results_log
        }, f, indent=2)

if __name__ == '__main__':
    main()
