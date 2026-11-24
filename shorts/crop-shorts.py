#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path
import cv2
import numpy as np


def get_smoothed_crop_boxes(
    video_path: Path,
    target_aspect: float = 9 / 16,
    face_height_ratio: float = 0.20,
    min_zoom_scale: float = 0.55,
):
    """
    Вычисляет плавную рамку кропа (center_x, center_y, crop_h) для каждого кадра,
    масштабируя кадр так, чтобы спикер занимал весь экран (портретный план).

    :param face_height_ratio: Какую долю высоты кадра должно занимать лицо (0.18 - 0.24 оптимально).
    :param min_zoom_scale: Минимальная высота рамки относительно исходника (0.55 = макс. зум ~1.8x, защита от мыла).
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Не удалось открыть видео: {video_path}")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    model_path = Path(__file__).parent / "face_detection_yunet_2023mar.onnx"
    detector = cv2.FaceDetectorYN.create(
        str(model_path), "", (width // 2, height // 2), score_threshold=0.7
    )

    # Начальное состояние: полный кадр по высоте в центре
    curr_x = width / 2.0
    curr_y = height / 2.0
    curr_h = float(height)

    min_h = height * min_zoom_scale
    max_h = float(height)

    # Коэффициенты сглаживания (чем меньше, тем плавнее движение камеры и зума)
    alpha_pos = 0.05
    alpha_zoom = 0.03
    deadzone_x = width * 0.03
    deadzone_y = height * 0.03
    deadzone_h = height * 0.06

    boxes = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % 3 == 0:
            small = cv2.resize(frame, (width // 2, height // 2))
            _, faces = detector.detect(small)

            if faces is not None and len(faces) > 0:
                best_face = max(faces, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = [v * 2.0 for v in best_face[:4]]

                face_cx = fx + fw / 2.0
                face_cy = fy + fh / 2.0

                # 1. Вычисляем желаемую высоту рамки под размер лица
                desired_h = fh / face_height_ratio
                desired_h = max(min_h, min(max_h, desired_h))

                if abs(desired_h - curr_h) > deadzone_h:
                    curr_h = alpha_zoom * desired_h + (1.0 - alpha_zoom) * curr_h

                # 2. Смещаем центр рамки вниз от центра лица, чтобы лицо было в верхней трети кадра
                # (примерно на 32% от верхнего края рамки)
                desired_y = face_cy + (curr_h * 0.18)

                if abs(face_cx - curr_x) > deadzone_x:
                    curr_x = alpha_pos * face_cx + (1.0 - alpha_pos) * curr_x

                if abs(desired_y - curr_y) > deadzone_y:
                    curr_y = alpha_pos * desired_y + (1.0 - alpha_pos) * curr_y

        # Зажимаем рамку внутри границ исходного видео
        crop_h = curr_h
        crop_w = crop_h * target_aspect

        half_w = crop_w / 2.0
        half_h = crop_h / 2.0

        clamped_x = max(half_w, min(width - half_w, curr_x))
        clamped_y = max(half_h, min(height - half_h, curr_y))

        boxes.append((clamped_x, clamped_y, crop_w, crop_h))
        frame_idx += 1

    cap.release()
    return boxes, fps


def render_vertical_video(
    input_path: Path,
    output_path: Path,
    face_ratio: float = 0.20,
    max_zoom: float = 1.8,
    use_mac_gpu: bool = False,
):
    print(f"[*] Анализ и расчет авто-зума: {input_path.name}...")
    min_scale = 1.0 / max_zoom
    boxes, fps = get_smoothed_crop_boxes(
        input_path, face_height_ratio=face_ratio, min_zoom_scale=min_scale
    )

    if not boxes:
        print(f"[!] Не удалось прочитать кадры из {input_path}")
        return

    cap = cv2.VideoCapture(str(input_path))
    temp_video = output_path.with_name(f"temp_{output_path.name}")

    # Сразу пишем в целевое разрешение 1080x1920 с качественной интерполяцией
    target_w, target_h = 1080, 1920
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(temp_video), fourcc, fps, (target_w, target_h))

    print(f"[*] Рендер портретного кадра 1080x1920 (зум до {max_zoom}x)...")
    for cx, cy, cw, ch in boxes:
        ret, frame = cap.read()
        if not ret:
            break

        x1 = int(round(cx - cw / 2.0))
        y1 = int(round(cy - ch / 2.0))
        x2 = int(round(cx + cw / 2.0))
        y2 = int(round(cy + ch / 2.0))

        # Страховка от выхода за границы на 1 пиксель из-за округления
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(frame.shape[1], x2)
        y2 = min(frame.shape[0], y2)

        cropped = frame[y1:y2, x1:x2]
        resized = cv2.resize(cropped, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
        out.write(resized)

    cap.release()
    out.release()

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
        "-i",
        str(temp_video),
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        *video_codec,
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    subprocess.run(cmd, check=True)
    temp_video.unlink(missing_ok=True)
    print(f"[+] Готово: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Авто-кадрирование 16:9 -> 9:16 с авто-зумом на спикера."
    )
    parser.add_argument("input_path", type=Path, help="MP4-файл или папка с клипами")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("vertical_clips"))
    parser.add_argument(
        "--face-ratio",
        type=float,
        default=0.20,
        help="Размер лица относительно высоты экрана (0.16 = по пояс, 0.22 = крупно по грудь, по умолчанию 0.20)",
    )
    parser.add_argument(
        "--max-zoom",
        type=float,
        default=2.0,
        help="Максимальное приближение (по умолчанию 2.0x)",
    )
    parser.add_argument("--mac-gpu", action="store_true", help="Использовать VideoToolbox на macOS")

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(args.input_path.glob("*.mp4")) if args.input_path.is_dir() else [args.input_path]
    if not files:
        print("MP4-файлы не найдены.", file=sys.stderr)
        sys.exit(1)

    for f in files:
        out_file = args.output_dir / f"{f.stem}_9x16.mp4"
        render_vertical_video(
            f,
            out_file,
            face_ratio=args.face_ratio,
            max_zoom=args.max_zoom,
            use_mac_gpu=args.mac_gpu,
        )

    print("\nКадрирование завершено!")


if __name__ == "__main__":
    main()

