#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont


def find_hebrew_font(size: int) -> ImageFont.FreeTypeFont:
    """Ищет установленный на macOS шрифт с поддержкой иврита."""
    candidates = [
        "/Library/Fonts/Heebo-Bold.ttf",
        "/Library/Fonts/Rubik-Bold.ttf",
        str(Path.home() / "Library/Fonts/Heebo-Bold.ttf"),
        str(Path.home() / "Library/Fonts/Rubik-Bold.ttf"),
        "/System/Library/Fonts/Supplemental/ArialHB.ttc",
        "/System/Library/Fonts/SFHebrew.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    raise RuntimeError(
        "Не найден шрифт с поддержкой иврита. Скачайте Heebo-Bold.ttf в ~/Library/Fonts/"
    )


def create_badge_png(
    text_he: str,
    highlight_word: str,
    output_png: Path,
    canvas_w: int = 1080,
    font_size: int = 58,
    bg_color=(15, 15, 20, 215),
    text_color=(255, 255, 255, 255),
    accent_color=(255, 215, 0, 255),  # Золотисто-желтый акцент
):
    """
    Рендерит прозрачный PNG с темной скругленной плашкой и RTL-текстом на иврите,
    выделяя акцентное слово цветом.
    """
    font = find_hebrew_font(font_size)
    padding_x = 44
    padding_y = 26
    max_text_w = canvas_w - 140  # Отступы по бокам для Safe Zone Instagram

    # Разбиваем на строки, если фраза длинная
    words = text_he.strip().split()
    lines = []
    current_line = []

    dummy_img = Image.new("RGBA", (10, 10))
    dummy_draw = ImageDraw.Draw(dummy_img)

    for word in words:
        test_line = " ".join(current_line + [word])
        visual_test = get_display(test_line)
        bbox = dummy_draw.textbbox((0, 0), visual_test, font=font)
        if (bbox[2] - bbox[0]) <= max_text_w or not current_line:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    # Считаем размеры итоговой плашки
    line_heights = []
    line_widths = []
    for line in lines:
        visual_line = get_display(line)
        bbox = dummy_draw.textbbox((0, 0), visual_line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    line_spacing = 14
    box_w = max(line_widths) + padding_x * 2
    box_h = sum(line_heights) + line_spacing * (len(lines) - 1) + padding_y * 2

    # Создаем холст ровно по размеру плашки (легче и быстрее для FFmpeg overlay)
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Рисуем скругленный прямоугольник + тонкую рамку
    draw.rounded_rectangle(
        [(0, 0), (box_w - 1, box_h - 1)],
        radius=24,
        fill=bg_color,
        outline=(255, 255, 255, 60),
        width=2,
    )

    # Очищаем highlight_word для сравнения
    clean_highlight = highlight_word.strip('"\'.,!?') if highlight_word else ""

    y_cursor = padding_y
    for idx, line in enumerate(lines):
        visual_line = get_display(line)
        # Позиционируем строку по центру плашки
        line_w = line_widths[idx]
        x_cursor = (box_w - line_w) // 2

        # Рисуем пословно в визуальном (слева-направо после get_display) порядке,
        # чтобы подсветить нужное слово
        visual_words = visual_line.split(" ")
        space_w = dummy_draw.textbbox((0, 0), " ", font=font)[2]

        for v_word in visual_words:
            # Сравниваем как в визуальном, так и в логическом виде
            raw_v = v_word.strip('"\'.,!?')
            is_accent = bool(
                clean_highlight
                and (
                    raw_v == get_display(clean_highlight)
                    or raw_v == clean_highlight
                    or get_display(clean_highlight) in raw_v
                )
            )
            color = accent_color if is_accent else text_color
            draw.text((x_cursor, y_cursor), v_word, font=font, fill=color)
            w_bbox = dummy_draw.textbbox((0, 0), v_word, font=font)
            x_cursor += (w_bbox[2] - w_bbox[0]) + space_w

        y_cursor += line_heights[idx] + line_spacing

    img.save(output_png, "PNG")


def apply_callouts_to_video(
    video_path: Path,
    meta_path: Path,
    output_path: Path,
    use_mac_gpu: bool = False,
):
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    temp_dir = output_path.parent / f"temp_badges_{meta['clip_id']}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    overlays = []  # Список кортежей: (png_path, start_sec, end_sec, y_pos)

    # 1. Заголовок-крючок (Hook) в начале ролика (0.2с -> 3.8с) в верхней трети экрана
    hook_he = meta.get("hook_title_he")
    if hook_he:
        hook_png = temp_dir / "hook.png"
        create_badge_png(
            text_he=hook_he,
            highlight_word="",
            output_png=hook_png,
            font_size=62,
            bg_color=(200, 35, 50, 230),  # Акцентный темно-красный/бордовый фон для хука
            text_color=(255, 255, 255, 255),
        )
        overlays.append((hook_png, 0.2, 3.8, "240"))

    # 2. Акцентные плашки по ходу речи в нижней Safe Zone (y = 1380 из 1920)
    callouts = meta.get("accent_callouts", [])
    for idx, item in enumerate(callouts):
        start_sec = float(item.get("clip_timestamp_sec", 0))
        duration = float(item.get("duration_sec", 3.5))
        end_sec = start_sec + duration
        text_he = item.get("text_he", "")
        highlight = item.get("highlight_word_he", "")

        if not text_he:
            continue

        badge_png = temp_dir / f"badge_{idx}.png"
        create_badge_png(
            text_he=text_he,
            highlight_word=highlight,
            output_png=badge_png,
            font_size=56,
        )
        overlays.append((badge_png, start_sec, end_sec, "1380"))

    if not overlays:
        print(f"[!] Нет плашек для {video_path.name}, просто копируем.")
        subprocess.run(["cp", str(video_path), str(output_path)], check=True)
        return

    # Собираем команду FFmpeg с цепочкой overlay
    inputs = ["-i", str(video_path)]
    filter_chains = []
    last_stream = "[0:v]"

    for idx, (png_path, start_s, end_s, y_pos) in enumerate(overlays):
        inputs.extend(["-i", str(png_path)])
        input_idx = idx + 1
        out_stream = f"[v{idx}]"
        # Центрируем плашку по горизонтали: x=(W-w)/2
        filter_chains.append(
            f"{last_stream}[{input_idx}:v]overlay=x=(W-w)/2:y={y_pos}:enable='between(t,{start_s:.2f},{end_s:.2f})'{out_stream}"
        )
        last_stream = out_stream

    video_codec = (
        ["-c:v", "h264_videotoolbox", "-b:v", "8M"]
        if use_mac_gpu
        else ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *inputs,
        "-filter_complex",
        ";".join(filter_chains),
        "-map",
        last_stream,
        "-map",
        "0:a:0",
        *video_codec,
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    print(f"[*] Наложение {len(overlays)} плашек на {video_path.name}...")
    try:
        subprocess.run(cmd, check=True)
        print(f"[+] Финальный ролик готов: {output_path}")
    finally:
        # Удаляем временные PNG
        for png_path, _, _, _ in overlays:
            png_path.unlink(missing_ok=True)
        temp_dir.rmdir()


def main():
    parser = argparse.ArgumentParser(
        description="Автоматическое наложение ивритских плашек по meta.json."
    )
    parser.add_argument(
        "--vertical-dir",
        type=Path,
        default=Path("vertical_clips"),
        help="Папка с вертикальными видео (*_9x16.mp4)",
    )
    parser.add_argument(
        "--meta-dir",
        type=Path,
        default=Path("output_clips"),
        help="Папка с файлами clip_XX_meta.json",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("final_reels"),
        help="Папка для готовых роликов",
    )
    parser.add_argument(
        "--mac-gpu",
        action="store_true",
        help="Использовать VideoToolbox на macOS",
    )

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    meta_files = sorted(args.meta_dir.glob("clip_*_meta.json"))
    if not meta_files:
        print(f"Не найдены файлы clip_*_meta.json в {args.meta_dir}", file=sys.stderr)
        sys.exit(1)

    for meta_path in meta_files:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        base_stem = Path(meta["video_file"]).stem  # например, clip_01_Молитва...
        vertical_video = args.vertical_dir / f"{base_stem}_9x16.mp4"

        if not vertical_video.exists():
            print(f"[!] Пропуск: не найдено вертикальное видео {vertical_video}")
            continue

        final_out = args.output_dir / f"{base_stem}_FINAL.mp4"
        apply_callouts_to_video(
            vertical_video, meta_path, final_out, use_mac_gpu=args.mac_gpu
        )

    print("\nВсе ролики оформлены и готовы к публикации в Instagram!")


if __name__ == "__main__":
    main()