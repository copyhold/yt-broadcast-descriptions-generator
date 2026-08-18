import json
import logging
import time

from google import genai

from config import CHURCH_NAME

# We don't use function calling/tools, so the SDK's automatic-function-calling
# warning ("use AFC in Chat.send_message") is not applicable and just noise.
logging.getLogger('google_genai.models').setLevel(logging.ERROR)

MODEL = 'gemini-3-flash-preview'

SECTION_NAMES_FOR_PROMPT = {
    'he': 'שבח והלל, תפילה, תפילה לילדים, ברכות, דרשה, הודעות, ברכה',
    'ru': 'Прославление, Молитва, Молитва за детей, Приветствие, Проповедь, Объявления, Благословение',
    'en': "Worship, Prayer, Children's Prayer, Greeting, Sermon, Announcements, Blessing",
}

OUTLINE_PROMPT_TEMPLATE = """You are analyzing a weekly service recording from the "{church_name}" Messianic congregation. The audio is in {lang_name}.

Listen carefully to the entire audio and produce a structured service outline.

IMPORTANT RULES for the formatted outline:
- Include ONLY spiritually meaningful content (worship, prayer, sermon, blessing).
- Do NOT mention or include: house rules, phone/photography reminders, offering logistics, technical announcements, or any administrative instructions to the congregation.
- The outline will be published as a YouTube video description — it must be clean, inspiring, and useful for navigation.

Requirements:
1. Identify each distinct section of the service from this list (use the exact names in {lang_name}):
   {section_names}
   Add any other meaningful sections you detect.

2. For each section provide:
   - name: section name in {lang_name}
   - start_time: HH:MM:SS timestamp when it begins
   - brief_description: 1-2 sentences summarizing spiritual content only

3. For the SERMON section, provide a detailed breakdown:
   - title: sermon title if mentioned
   - summary: 3-5 sentences briefly describing the main message, key spiritual insight, and practical application of the sermon
   - scripture_references: all Bible verses cited
   - parts: 5–8 logical sub-sections of the sermon, each with:
     * start_time: HH:MM:SS
     * heading: short descriptive title for this part
     * summary: 2-3 sentences on content, key points, illustrations used

4. After the JSON, write the formatted outline in {lang_name}:
   - START with the sermon title (if available) format it with ## (second level) heading
   - then write a 3-5 sentence summary of the sermon's main message — this is the most prominent part of the description
   - Then list each service section on its own line with [HH:MM:SS] timecode
   - Sermon broken into its 5–8 sub-parts, each with its own [HH:MM:SS] timecode, a short heading and a summary
     the format for each sub part should be: [HH:MM:SS] *{{heading}}* - {{summary}}
   - Scripture references listed under the sermon
   - No administrative or logistical content
   - Suitable as a YouTube video description. bold is single asterisk, italic is a single underline _

Return your response in this exact format:
```json
{{
  "sections": [
    {{
      "name": "...",
      "start_time": "HH:MM:SS",
      "brief_description": "..."
    }}
  ],
  "sermon": {{
    "title": "...",
    "summary": "...",
    "scripture_references": ["..."],
    "parts": [
      {{
        "start_time": "HH:MM:SS",
        "heading": "...",
        "summary": "..."
      }}
    ]
  }}
}}
```
FORMATTED_OUTLINE_START
[Write the full formatted outline here in {lang_name}]
FORMATTED_OUTLINE_END
"""

TRANSLATE_PROMPT_TEMPLATE = """Translate the following church service outline from {source_lang} to {target_lang}.

Rules:
- Preserve all [HH:MM:SS] timecodes exactly as they are
- Preserve all markdown formatting (**, *, -, #)
- Translate naturally and fluently for a native speaker
- Keep Bible verse references in standard form for the target language

OUTLINE:
{outline_text}
"""

_client: genai.Client | None = None
_token_stats = {'input': 0, 'output': 0, 'total': 0}


def configure(api_key: str) -> None:
    global _client
    _client = genai.Client(api_key=api_key)


def get_token_stats() -> dict:
    return dict(_token_stats)


def _record_usage(response) -> None:
    usage = getattr(response, 'usage_metadata', None)
    if usage is None:
        return
    _token_stats['input'] += getattr(usage, 'prompt_token_count', 0) or 0
    _token_stats['output'] += getattr(usage, 'candidates_token_count', 0) or 0
    _token_stats['total'] += getattr(usage, 'total_token_count', 0) or 0


def _get_client() -> genai.Client:
    if _client is None:
        raise RuntimeError('Call gemini_client.configure(api_key) first')
    return _client


def upload_audio(audio_path: str):
    client = _get_client()
    print(f'  Uploading audio to Gemini: {audio_path}')
    audio_file = client.files.upload(file=audio_path)
    while audio_file.state.name == 'PROCESSING':
        time.sleep(5)
        audio_file = client.files.get(name=audio_file.name)
    if audio_file.state.name != 'ACTIVE':
        raise RuntimeError(f'Gemini file upload failed: {audio_file.state.name}')
    print(f'  Audio uploaded: {audio_file.name}')
    return audio_file


def generate_outline(audio_file, lang: str) -> tuple[dict, str]:
    client = _get_client()
    lang_name = {'he': 'Hebrew', 'ru': 'Russian', 'en': 'English'}[lang]
    prompt = OUTLINE_PROMPT_TEMPLATE.format(
        church_name=CHURCH_NAME[lang],
        lang_name=lang_name,
        section_names=SECTION_NAMES_FOR_PROMPT[lang],
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=[audio_file, prompt],
    )
    _record_usage(response)
    text = response.text
    json_data = _extract_json(text)
    outline_text = _extract_outline(text)
    return json_data, outline_text


def translate_outline(outline_text: str, source_lang: str, target_lang: str) -> str:
    client = _get_client()
    lang_names = {'he': 'Hebrew', 'ru': 'Russian', 'en': 'English'}
    prompt = TRANSLATE_PROMPT_TEMPLATE.format(
        source_lang=lang_names[source_lang],
        target_lang=lang_names[target_lang],
        outline_text=outline_text,
    )
    response = client.models.generate_content(model=MODEL, contents=prompt)
    _record_usage(response)
    return response.text.strip()


def delete_uploaded_file(audio_file) -> None:
    try:
        _get_client().files.delete(name=audio_file.name)
    except Exception:
        pass


def _extract_json(text: str) -> dict:
    start = text.find('```json')
    end = text.find('```', start + 6)
    if start == -1 or end == -1:
        return {}
    json_str = text[start + 7:end].strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {}


def _extract_outline(text: str) -> str:
    start = text.find('FORMATTED_OUTLINE_START')
    end = text.find('FORMATTED_OUTLINE_END')
    if start == -1 or end == -1:
        json_end = text.rfind('```')
        return text[json_end + 3:].strip() if json_end != -1 else text.strip()
    return text[start + len('FORMATTED_OUTLINE_START'):end].strip()
