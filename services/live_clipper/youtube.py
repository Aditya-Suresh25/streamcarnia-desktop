"""YouTube desktop OAuth, quota-aware upload, and live chat helpers."""
from __future__ import annotations

import json

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
                  "https://www.googleapis.com/auth/youtube.readonly"]


def youtube_service(client_secrets_file: str, vault, service_builder=None):
    """Load/refresh OAuth credentials from the OS credential store."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    if service_builder is None:
        from googleapiclient.discovery import build
        service_builder = build

    token_json = vault.get("youtube.oauth")
    credentials = Credentials.from_authorized_user_info(json.loads(token_json), YOUTUBE_SCOPES) if token_json else None
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, YOUTUBE_SCOPES)
        credentials = flow.run_local_server(port=0, open_browser=True)
    vault.set("youtube.oauth", credentials.to_json())
    return service_builder("youtube", "v3", credentials=credentials, cache_discovery=False)


class YouTubeUploader:
    def __init__(self, service, media_upload_factory=None):
        self.service = service
        self.media_upload_factory = media_upload_factory

    def upload(self, file_path: str | Path, metadata: dict, publish_at: str) -> str:
        if self.media_upload_factory is None:
            from googleapiclient.http import MediaFileUpload
            media_factory = MediaFileUpload
        else:
            media_factory = self.media_upload_factory
        title = str(metadata["title"]).strip()
        if not title or len(title) >= 60:
            raise ValueError("YouTube title must be under 60 characters")
        tags = [str(tag).lstrip("#") for tag in metadata.get("hashtags", [])]
        description = str(metadata.get("description", "")).strip()
        hashtags = [str(tag).strip() for tag in metadata.get("hashtags", []) if str(tag).strip()]
        hashtag_line = " ".join(tag if tag.startswith("#") else f"#{tag}" for tag in hashtags)
        if "#shorts" not in hashtag_line.casefold():
            hashtag_line = (hashtag_line + " #Shorts").strip()
        if hashtag_line and hashtag_line.casefold() not in description.casefold():
            description = f"{description}\n\n{hashtag_line}".strip()
        body = {"snippet": {"title": title, "description": description,
                            "tags": tags},
                "status": {"privacyStatus": "private", "publishAt": publish_at}}
        request = self.service.videos().insert(part="snippet,status", body=body,
            media_body=media_factory(str(file_path), mimetype="video/mp4", chunksize=-1, resumable=True))
        if hasattr(request, "next_chunk"):
            response = None
            while response is None:
                _status, response = request.next_chunk()
        else:
            response = request.execute()
        video_id = response.get("id") if isinstance(response, dict) else None
        if not video_id:
            raise RuntimeError("YouTube did not return an uploaded video ID")
        return str(video_id)


def active_live_chat_id(service, broadcast_id: str | None = None) -> str | None:
    request = service.liveBroadcasts().list(part="snippet", id=broadcast_id) if broadcast_id else \
              service.liveBroadcasts().list(part="snippet", broadcastStatus="active", mine=True)
    response = request.execute()
    for item in response.get("items", []):
        chat_id = item.get("snippet", {}).get("liveChatId")
        if chat_id:
            return str(chat_id)
    return None
