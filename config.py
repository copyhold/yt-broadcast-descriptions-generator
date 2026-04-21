import re

HEBREW_RE = re.compile(r'[\u0590-\u05FF\uFB1D-\uFB4F]')
CYRILLIC_RE = re.compile(r'[\u0400-\u04FF]')

LANG_NAMES = {
    'he': 'Hebrew',
    'ru': 'Russian',
    'en': 'English',
}

SERVICE_SECTIONS = {
    'he': [
        'שבח והלל', 'תפילה', 'תפילה לילדים', 'ברכות', 'דרשה', 'הודעות', 'ברכה'
    ],
    'ru': [
        'Прославление', 'Молитва', 'Молитва за детей', 'Приветствие',
        'Проповедь', 'Объявления', 'Благословение',
    ],
    'en': [
        'Worship', 'Prayer', "Children's Prayer", 'Greeting',
        'Sermon', 'Announcements', 'Blessing',
    ],
}

CHURCH_NAME = {
    'he': 'כוכב השחר',
    'ru': 'Утренняя Звезда',
    'en': 'Morning Star',
}

GROUPING_WINDOW_HOURS = 48
DEFAULT_LIMIT = 10
OUTLINES_DIR = 'outlines'
AUDIO_DIR = 'audio'
HISTORY_FILE = 'history.json'
TOKEN_FILE = 'token.json'

YOUTUBE_SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']


def detect_language(title: str) -> str:
    if HEBREW_RE.search(title):
        return 'he'
    if CYRILLIC_RE.search(title):
        return 'ru'
    return 'en'
