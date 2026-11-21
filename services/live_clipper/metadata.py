"""Transcript-grounded Gemini titles and descriptions with a safe fallback."""
from __future__ import annotations

import json
from datetime import datetime

MODEL = "gemini-3.8-flash"
SCHEMA = {
    "type": "OBJECT", "properties": {
        "title": {"type": "STRING", "description": "A concise title under 60 characters"},
        "description": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    }, "required": ["title", "description", "hashtags"],
}
STUDIO_VARIATION_SCHEMA = {
    "type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "title": {"type": "STRING"}, "description": {"type": "STRING"},
        "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "category": {"type": "STRING"}, "language": {"type": "STRING"},
    }, "required": ["title", "description", "tags", "hashtags", "category", "language"]}
}


def generate_metadata_variations(transcript: str, source_title: str, api_key: str | None,
                                 tone: str = "casual", language: str = "auto", count: int = 3,
                                 client_factory=None) -> list[dict]:
    """Create editable transcript-grounded metadata variants in a natural voice."""
    transcript = (transcript or "").strip()
    if not transcript:
        raise ValueError("This clip has no transcript to use for metadata generation.")
    if not api_key:
        raise ValueError("Add a Gemini API key in Settings to generate metadata.")
    if tone not in {"casual", "energetic", "humorous", "informative"}:
        raise ValueError("Choose a supported metadata tone.")
    count = max(1, min(5, int(count)))
    if client_factory is None:
        from google import genai
        client_factory = genai.Client
    prompt = (
        "Create editable YouTube Shorts metadata variants based only on the transcript. "
        "Never invent events, game actions, names, or claims. Preserve the speaker's meaning, "
        "humour, gaming terms, slang, and Indian conversational style. Preserve English words. "
        "For Hindi or Hinglish, write Hindi words in Roman script; do not translate the dialogue "
        "into formal Hindi or pure English. Keep descriptions factual. Each title must be under "
        "60 characters. Include #Shorts in every hashtags list. Return exactly the requested number "
        f"of distinct variants. Tone: {tone}. Language preference: {language}. "
        f"Source title: {source_title}\nNumber of variants: {count}\nTranscript:\n{transcript[:12000]}"
    )
    client = client_factory(api_key=api_key)
    response = client.models.generate_content(model=MODEL, contents=prompt,
        config={"response_mime_type": "application/json", "response_schema": STUDIO_VARIATION_SCHEMA})
    values = json.loads(getattr(response, "text", "") or "[]")
    if not isinstance(values, list) or len(values) != count:
        raise ValueError("Gemini did not return the requested number of metadata variants.")
    normalized = []
    for value in values:
        title = str(value.get("title", "")).strip()
        if not title or len(title) >= 60:
            raise ValueError("Gemini returned a title that is empty or 60 characters or longer.")
        tags = [str(item).strip().lstrip("#") for item in value.get("tags", []) if str(item).strip()]
        hashtags = [str(item).strip() for item in value.get("hashtags", []) if str(item).strip()]
        if not any(item.casefold() == "#shorts" for item in hashtags):
            hashtags.append("#Shorts")
        normalized.append({"title": title, "description": str(value.get("description", "")).strip(),
            "tags": tags, "hashtags": hashtags, "category": str(value.get("category", "")).strip(),
            "language": str(value.get("language", "")).strip(), "tone": tone})
    return normalized


def fallback_title(stream_name: str, timestamp: datetime | None = None) -> str:
    timestamp = timestamp or datetime.now().astimezone()
    suffix = timestamp.strftime("%Y-%m-%d %H:%M")
    prefix = (stream_name or "Live stream").strip() or "Live stream"
    return f"{prefix[:max(1, 58 - len(suffix))].rstrip()} {suffix}"[:59]


def generate_metadata(transcript: str, stream_name: str, api_key: str | None,
                      timestamp: datetime | None = None, client_factory=None) -> dict:
    fallback = {"title": fallback_title(stream_name, timestamp), "description": "",
                "hashtags": ["#Shorts"], "fallback": True}
    transcript = (transcript or "").strip()
    if not transcript:
        fallback["fallback_reason"] = "The VOD pipeline did not provide a transcript for this clip."
        return fallback
    if not api_key:
        fallback["fallback_reason"] = "Gemini API key is not configured in Settings."
        return fallback
    try:
        if client_factory is None:
            from google import genai
            client_factory = genai.Client
        client = client_factory(api_key=api_key)
        prompt = ("Create YouTube Shorts metadata using only facts stated in this transcript. "
                  "Do not infer or invent events. Keep title under 60 characters. "
                  "Return only JSON matching the schema. Include #Shorts in hashtags.\n\n"
                  f"Stream: {stream_name}\nTranscript:\n{transcript[:12000]}")
        response = client.models.generate_content(model=MODEL, contents=prompt,
            config={"response_mime_type": "application/json", "response_schema": SCHEMA})
        raw = getattr(response, "text", "")
        result = json.loads(raw)
        title = str(result.get("title", "")).strip()
        description = str(result.get("description", "")).strip()
        hashtags = result.get("hashtags", [])
        if not title or len(title) >= 60 or not isinstance(hashtags, list):
            fallback["fallback_reason"] = "Gemini returned metadata that did not pass validation."
            return fallback
        tags = [str(tag).strip() for tag in hashtags if str(tag).strip()]
        if not any(tag.casefold() == "#shorts" for tag in tags):
            tags.append("#Shorts")
        return {"title": title, "description": description, "hashtags": tags, "fallback": False}
    except Exception as exc:
        fallback["fallback_reason"] = f"Gemini request failed: {type(exc).__name__}: {str(exc)[:240]}"
        return fallback
