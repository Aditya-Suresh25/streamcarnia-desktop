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
    if not transcript or not api_key:
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
            return fallback
        tags = [str(tag).strip() for tag in hashtags if str(tag).strip()]
        if not any(tag.casefold() == "#shorts" for tag in tags):
            tags.append("#Shorts")
        return {"title": title, "description": description, "hashtags": tags, "fallback": False}
    except Exception:
        return fallback
