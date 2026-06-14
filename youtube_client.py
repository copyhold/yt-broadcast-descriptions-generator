import os
from datetime import datetime, timezone

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import YOUTUBE_SCOPES, TOKEN_FILE


def get_authenticated_service(credentials_file: str):
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, YOUTUBE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                os.remove(TOKEN_FILE)
                creds = None
        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, YOUTUBE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
    return build('youtube', 'v3', credentials=creds)


def fetch_videos_from_playlists(service, playlist_ids: list[str], limit: int) -> list[dict]:
    seen_ids: set[str] = set()
    videos: list[dict] = []

    for playlist_id in playlist_ids:
        next_page_token = None
        while True:
            params: dict = {
                'part': 'snippet',
                'playlistId': playlist_id,
                'maxResults': 50,
            }
            if next_page_token:
                params['pageToken'] = next_page_token

            response = service.playlistItems().list(**params).execute()
            items = response.get('items', [])
            if not items:
                break

            new_video_ids = [
                item['snippet']['resourceId']['videoId']
                for item in items
                if item['snippet']['resourceId'].get('kind') == 'youtube#video'
                and item['snippet']['resourceId']['videoId'] not in seen_ids
            ]

            if new_video_ids:
                details = service.videos().list(
                    part='snippet',
                    id=','.join(new_video_ids),
                ).execute()

                for detail in details.get('items', []):
                    if detail['id'] in seen_ids:
                        continue
                    seen_ids.add(detail['id'])
                    snippet = detail['snippet']
                    videos.append({
                        'id': detail['id'],
                        'title': snippet['title'],
                        'description': snippet.get('description', ''),
                        'published_at': datetime.fromisoformat(
                            snippet['publishedAt'].replace('Z', '+00:00')
                        ),
                    })

            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break

    videos.sort(key=lambda v: v['published_at'], reverse=True)
    return videos[:limit]


def update_video_description(service, video_id: str, new_description: str) -> None:
    video = service.videos().list(part='snippet', id=video_id).execute()
    snippet = video['items'][0]['snippet']
    snippet['description'] = new_description
    service.videos().update(
        part='snippet',
        body={'id': video_id, 'snippet': snippet},
    ).execute()
