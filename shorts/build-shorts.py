#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def load_json_safely(json_path: Path) -> dict:
    # utf-8-sig автоматически удаляет невидимый BOM-символ в начале файла, если он есть
    raw_text = json_path.read_text(encoding="utf-8-sig").strip()

    # Убираем случайные markdown-обертки ```json ... ```
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        lines = raw_text.splitlines()
        err_line = lines[e.lineno - 1] if e.lineno <= len(lines) else ""
        print(f"[Ошибка JSON] Строка {e.lineno}, позиция {e.colno}: {e.msg}", file=sys.stderr)
        print(f"Проблемная строка: {err_line}", file=sys.stderr)
        sys.exit(1)

def parse_timestamp(ts: str) -> float:
    """Переводит таймкод формата H:MM:SS.mmm или MM:SS.mmm в секунды (float)."""
    parts = ts.strip().split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    elif len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    return float(ts)


def format_timestamp(sec: float) -> str:
    """Переводит секунды обратно в формат HH:MM:SS.mmm."""
    hours = int(sec // 3600)
    minutes = int((sec % 3600) // 60)
    seconds = sec % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


def sanitize_filename(name: str) -> str:
    """Очищает название файла от недопустимых символов."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    return clean.strip().replace(" ", "_")


def remap_callouts(segments: list, callouts: list) -> list:
    """
    Пересчитывает таймкоды акцентных плашек из глобального времени стрима
    в локальное время смонтированного клипа.
    """
    remapped = []
    timeline_offset = 0.0

    # Считаем смещение для каждого сегмента в итоговом клипе
    segment_windows = []
    for seg in segments:
        s_start = parse_timestamp(seg["start"])
        s_end = parse_timestamp(seg["end"])
        duration = s_end - s_start
        segment_windows.append((s_start, s_end, timeline_offset))
        timeline_offset += duration

    for item in callouts:
        c_time = parse_timestamp(item["timestamp"])
        for s_start, s_end, offset in segment_windows:
            if s_start <= c_time <= s_end:
                local_time = offset + (c_time - s_start)
                new_item = item.copy()
                new_item["clip_timestamp"] = format_timestamp(local_time)
                new_item["clip_timestamp_sec"] = round(local_time, 3)
                remapped.append(new_item)
                break

    return remapped


def build_clip(video_path: Path, clip_data: dict, output_dir: Path, use_mac_gpu: bool = False):
    clip_id = clip_data.get("clip_id", 0)
    title_ru = clip_data.get("title_ru", f"clip_{clip_id}")
    safe_title = sanitize_filename(title_ru)[:40]
    output_video = output_dir / f"clip_{clip_id:02d}_{safe_title}.mp4"
    output_meta = output_dir / f"clip_{clip_id:02d}_meta.json"

    segments = sorted(clip_data.get("segments", []), key=lambda x: x.get("order", 0))
    if not segments:
        return

    video_codec = ["-c:v", "h264_videotoolbox", "-b:v", "8M"] if use_mac_gpu else [
        "-c:v", "libx264", "-preset", "fast", "-crf", "18"
    ]

    temp_files = []
    concat_list_path = output_dir / f"temp_concat_{clip_id}.txt"

    print(f"[*] Сборка клипа #{clip_id}: {title_ru} ({len(segments)} склеек)...")

    try:
        for idx, seg in enumerate(segments):
            start_sec = parse_timestamp(seg["start"])
            end_sec = parse_timestamp(seg["end"])
            duration = end_sec - start_sec
            if duration <= 0:
                continue

            seg_file = output_dir / f"temp_c{clip_id}_s{idx}.mp4"
            temp_files.append(seg_file)

            # Fast input seek (-ss before -i) avoids PTS offset silence bugs
            cut_cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{start_sec:.3f}",
                "-i", str(video_path),
                "-t", f"{duration:.3f}",
                *video_codec,
                "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
                "-avoid_negative_ts", "make_zero",
                str(seg_file),
            ]
            subprocess.run(cut_cmd, check=True)

        if not temp_files:
            return

        # Write concat demuxer list
        concat_lines = [f"file '{f.resolve()}'" for f in temp_files]
        concat_list_path.write_text("\n".join(concat_lines), encoding="utf-8")

        # Merge segments losslessly
        merge_cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list_path),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_video),
        ]
        subprocess.run(merge_cmd, check=True)

    finally:
        # Clean up temp segment files
        for f in temp_files:
            f.unlink(missing_ok=True)
        concat_list_path.unlink(missing_ok=True)

    remapped_callouts = remap_callouts(segments, clip_data.get("accent_callouts", []))
    clip_meta = {
        "clip_id": clip_id,
        "title_ru": title_ru,
        "hook_title_he": clip_data.get("hook_title_he"),
        "hook_title_ru": clip_data.get("hook_title_ru"),
        "video_file": output_video.name,
        "accent_callouts": remapped_callouts,
    }
    output_meta.write_text(json.dumps(clip_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[+] Готово: {output_video}")



def main():
    parser = argparse.ArgumentParser(description="Нарезка и склейка клипов из проповеди по JSON.")
    parser.add_argument("video", type=Path, help="Путь к исходному видеофайлу (.mp4/.mkv)")
    parser.add_argument("json_file", type=Path, help="Путь к JSON-файлу с разметкой клипов")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("output_clips"), help="Папка для сохранения")
    parser.add_argument("--mac-gpu", action="store_true", help="Использовать аппаратное ускорение macOS (VideoToolbox)")

    args = parser.parse_args()

    if not args.video.exists():
        print(f"Файл видео не найден: {args.video}", file=sys.stderr)
        sys.exit(1)
    if not args.json_file.exists():
        print(f"JSON-файл не найден: {args.json_file}", file=sys.stderr)
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    data = load_json_safely(args.json_file)
    clips = data.get("clips", [])

    if not clips:
        print("В JSON не найден список 'clips'.", file=sys.stderr)
        sys.exit(1)

    for clip in clips:
        build_clip(args.video, clip, args.output_dir, use_mac_gpu=args.mac_gpu)

    print("\nВсе клипы собраны!")


if __name__ == "__main__":
    main()
