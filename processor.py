import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import gemini_client
import youtube_client
from config import (
    AUDIO_DIR,
    FOOTER,
    GROUPING_WINDOW_HOURS,
    HISTORY_FILE,
    OUTLINES_DIR,
    detect_language,
)



def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {}


def save_history(history: dict) -> None:
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2, default=str)


def group_videos_into_services(videos: list[dict]) -> list[list[dict]]:
    sorted_videos = sorted(videos, key=lambda v: v['published_at'], reverse=True)
    groups: list[list[dict]] = []
    for video in sorted_videos:
        placed = False
        for group in groups:
            anchor = group[0]['published_at']
            if abs((video['published_at'] - anchor).total_seconds()) <= GROUPING_WINDOW_HOURS * 3600:
                group.append(video)
                placed = True
                break
        if not placed:
            groups.append([video])
    return groups


def get_audio_path(video_id: str) -> str:
    Path(AUDIO_DIR).mkdir(exist_ok=True)
    return os.path.join(AUDIO_DIR, f'{video_id}.mp3')


def download_audio(video_id: str, output_path: str) -> None:
    if os.path.exists(output_path):
        print(f'  Audio already exists, skipping download: {output_path}')
        return
    url = f'https://www.youtube.com/watch?v={video_id}'
    cmd = [
        'yt-dlp',
        '--cookies-from-browser', 'firefox',
        '-f', 'bestaudio/best',
        '-x',
        '--audio-format', 'mp3',
        '--audio-quality', '5',
        '-o', output_path,
        '--no-playlist',
        url,
    ]
    print(f'  Downloading audio for {video_id}...')
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f'yt-dlp failed: {result.stderr}')


def save_outline(video_id: str, lang: str, outline_text: str) -> None:
    Path(OUTLINES_DIR).mkdir(exist_ok=True)
    path = os.path.join(OUTLINES_DIR, f'{video_id}_{lang}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(outline_text)
    print(f'  Outline saved: {path}')


_YT_DESC_LIMIT = 5000


def build_description(outline_text: str, original_description: str, lang: str) -> str:
    footer = FOOTER.get(lang, '')
    body = f'{outline_text}\n\n{footer}' if footer else outline_text
    return body[:_YT_DESC_LIMIT]


def run(
    playlist_ids: list[str],
    primary_lang: str,
    limit: int,
    credentials_file: str,
    gemini_api_key: str,
    dry_run: bool,
) -> None:
    gemini_client.configure(gemini_api_key)

    print('Authenticating with YouTube...')
    yt = youtube_client.get_authenticated_service(credentials_file)

    print(f'Fetching last {limit} videos from playlists: {", ".join(playlist_ids)}...')
    videos = youtube_client.fetch_videos_from_playlists(yt, playlist_ids, limit)
    print(videos)
    print(f'Found {len(videos)} videos.')

    for v in videos:
        v['lang'] = detect_language(v['title'])

    groups = group_videos_into_services(videos)
    print(f'Grouped into {len(groups)} service(s).')

    history = load_history()

    for i, group in enumerate(groups, 1):
        primary_videos = [v for v in group if v['lang'] == primary_lang]
        if not primary_videos:
            print(f'Service {i}: no {primary_lang} video found, skipping.')
            continue

        primary = primary_videos[0]
        if primary['id'] in history:
            print(f'Service {i} ({primary["title"]}): already processed, skipping.')
            continue

        print(f'\nProcessing service {i}: {primary["title"]}')

        audio_path = get_audio_path(primary['id'])
        download_audio(primary['id'], audio_path)

        print('  Uploading to Gemini and generating outline...')
        audio_file = gemini_client.upload_audio(audio_path)
        try:
            outline_data, outline_text = gemini_client.generate_outline(audio_file, primary_lang)
        finally:
            gemini_client.delete_uploaded_file(audio_file)

        save_outline(primary['id'], primary_lang, outline_text)

        outlines: dict[str, str] = {primary_lang: outline_text}

        other_videos = [v for v in group if v['lang'] != primary_lang]
        for v in other_videos:
            target_lang = v['lang']
            if target_lang not in outlines:
                print(f'  Translating outline to {target_lang}...')
                translated = gemini_client.translate_outline(outline_text, primary_lang, target_lang)
                outlines[target_lang] = translated
                save_outline(v['id'], target_lang, translated)

        if not dry_run:
            for v in group:
                lang = v['lang']
                if lang not in outlines:
                    continue
                new_desc = build_description(outlines[lang], v['description'], lang)
                print(f'  Updating description for {v["id"]} ({lang})...')
                youtube_client.update_video_description(yt, v['id'], new_desc)
        else:
            print('  [dry-run] Skipping YouTube description update.')

        history[primary['id']] = datetime.now(timezone.utc).isoformat()
        for v in other_videos:
            history[v['id']] = datetime.now(timezone.utc).isoformat()
        save_history(history)
        print(f'  Service {i} done.')

    print('\nAll done.')
