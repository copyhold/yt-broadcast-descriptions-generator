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


def fetch_recent_videos(service, channel_id: str, limit: int) -> list[dict]:
    videos = []
    next_page_token = None

    while len(videos) < limit:
        batch = min(50, limit - len(videos))
        params = {
            'part': 'snippet',
            'channelId': channel_id,
            'maxResults': batch,
            'order': 'date',
            'type': 'video',
        }
        if next_page_token:
            params['pageToken'] = next_page_token

        response = service.search().list(**params).execute()
        items = response.get('items', [])
        if not items:
            break

        video_ids = [item['id']['videoId'] for item in items]
        details = service.videos().list(
            part='snippet',
            id=','.join(video_ids),
        ).execute()

        for detail in details.get('items', []):
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

    return videos


def update_video_description(service, video_id: str, new_description: str) -> None:
    video = service.videos().list(part='snippet', id=video_id).execute()
    snippet = video['items'][0]['snippet']
    snippet['description'] = new_description
    service.videos().update(
        part='snippet',
        body={'id': video_id, 'snippet': snippet},
    ).execute()
