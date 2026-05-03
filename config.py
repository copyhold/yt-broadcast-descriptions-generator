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
    'he': 'קהילת כוכב השחר',
    'ru': 'Община Утренняя Звезда',
    'en': 'Morning Star Messianic Fellowship',
}

FOOTER = {
        'he': """
קהילת כוכב הבוקר היא קהילה משיחית יהודית הממוקמת בטבריה. בחסדי האל אנו מעבירים את האמת הגדולה של הברית הישנה והחדשה כדבר אלוהים שנגלה לעולם על ידי ישוע המשיח שלנו. אלוהים שם אהבה לישראל בליבנו ואחת ממטרותינו העיקריות היא לשרת את הקהילה שלנו בדרכים שונות לא רק בטבריה אלא גם בגליל.

https://morningstar.org.il/
""",

        'ru': """
Шаббатнее собрание из Израиля общины Утренняя Звезда (Прославление и проповедь)
Община "Утренняя Звезда" — это еврейская мессианская община, расположенная в Израиле в городе Тверия, нижняя Галилея. По благодати Божией мы передаем великую истину Ветхого и Нового Завета как слово Божие, открытое миру Иешуа (Иисусом), нашим Мессией. Бог вложил в наши сердца любовь к Израилю, и одна из наших главных целей — по-разному служить нашему сообществу не только в Тверии, но и в Галилее.

https://morningstar.org.il/
""",
        'en': """
Morning Star Fellowship is a Jewish Messianic congregation located in Tiberias. In God’s grace we convey the great truth of the Old and the New testament as the word of God revealed to the world by Yeshua (Jesus) our Messiah. God has put a love for Israel in our hearts and one of our main goals is to serve our community in different ways not only in Tiberias but in the Galilee.

https://morningstar.org.il/
"""
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
