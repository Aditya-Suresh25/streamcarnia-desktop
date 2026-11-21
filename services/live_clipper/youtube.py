"""YouTube desktop OAuth, quota-aware upload, and live chat helpers."""
from __future__ import annotations

import json
import time

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
        # google-auth-oauthlib supports S256 PKCE; keep it explicit for the
        # installed desktop public client.
        flow.autogenerate_code_verifier = True
        credentials = flow.run_local_server(port=0, open_browser=True)
    vault.set("youtube.oauth", credentials.to_json())
    return service_builder("youtube", "v3", credentials=credentials, cache_discovery=False)


def revoke_youtube(vault, request_factory=None) -> None:
    """Revoke the connected grant, then remove its local refresh token."""
    raw = vault.get("youtube.oauth")
    if not raw:
        return
    token = json.loads(raw).get("refresh_token") or json.loads(raw).get("token")
    if token:
        if request_factory is None:
            import requests
            request_factory = requests.post
        response = request_factory("https://oauth2.googleapis.com/revoke",
                                   params={"token": token}, timeout=15)
        if response.status_code not in (200, 400):
            response.raise_for_status()
    vault.delete("youtube.oauth")


def connected_channel(service) -> dict | None:
    response = service.channels().list(part="snippet,contentDetails", mine=True, maxResults=50).execute()
    channels = response.get("items") or []
    if not channels:
        return None
    channel = channels[0]
    snippet = channel.get("snippet", {})
    return {"id": channel.get("id", ""), "title": snippet.get("title", "YouTube channel"),
            "custom_url": snippet.get("customUrl", ""),
            "avatar_url": (snippet.get("thumbnails", {}).get("default", {}).get("url", "")),
            "uploads_playlist_id": channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")}


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
        tags = [str(tag).strip().lstrip("#") for tag in metadata.get("tags", []) if str(tag).strip()]
        tags += [str(tag).lstrip("#") for tag in metadata.get("hashtags", [])]
        description = str(metadata.get("description", "")).strip()
        hashtags = [str(tag).strip() for tag in metadata.get("hashtags", []) if str(tag).strip()]
        hashtag_line = " ".join(tag if tag.startswith("#") else f"#{tag}" for tag in hashtags)
        if "#shorts" not in hashtag_line.casefold():
            hashtag_line = (hashtag_line + " #Shorts").strip()
        if hashtag_line and hashtag_line.casefold() not in description.casefold():
            description = f"{description}\n\n{hashtag_line}".strip()
        snippet = {"title": title, "description": description, "tags": list(dict.fromkeys(tags))}
        if metadata.get("category_id"):
            snippet["categoryId"] = str(metadata["category_id"])
        if metadata.get("language") and metadata["language"] != "auto":
            snippet["defaultLanguage"] = str(metadata["language"])
        body = {"snippet": snippet,
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

    def update_schedule(self, video_id: str, publish_at: str | None) -> None:
        response = self.service.videos().list(part="snippet,status", id=video_id).execute()
        items = response.get("items") or []
        if not items:
            raise RuntimeError("The scheduled YouTube video was not found.")
        video = items[0]
        status = dict(video.get("status", {}))
        if status.get("privacyStatus") != "private":
            raise RuntimeError("Only an unpublished private video can be rescheduled.")
        if publish_at is None:
            status.pop("publishAt", None)
        else:
            status["publishAt"] = publish_at
        self.service.videos().update(part="status", body={"id": video_id, "status": status}).execute()

    def status(self, video_id: str) -> dict | None:
        response = self.service.videos().list(part="status,processingDetails", id=video_id).execute()
        items = response.get("items") or []
        if not items:
            return None
        item = items[0]
        return {"status": item.get("status", {}), "processing": item.get("processingDetails", {})}

    def set_thumbnail_when_ready(self, video_id: str, thumbnail_path: str | Path,
                                 wait_seconds: int = 900, cancel_event=None) -> None:
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Thumbnail upload cancelled because StreamCarnia is closing.")
            state = self.status(video_id)
            if state is None:
                raise RuntimeError("Uploaded video disappeared before thumbnail processing completed.")
            processing_status = state["processing"].get("processingStatus")
            if processing_status == "succeeded":
                from googleapiclient.http import MediaFileUpload
                self.service.thumbnails().set(videoId=video_id,
                    media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")).execute()
                return
            if processing_status == "failed":
                raise RuntimeError("YouTube could not process the uploaded video for its thumbnail.")
            if cancel_event is not None:
                if cancel_event.wait(min(10, max(0, deadline - time.monotonic()))):
                    raise RuntimeError("Thumbnail upload cancelled because StreamCarnia is closing.")
            else:
                time.sleep(10)
        raise TimeoutError("YouTube is still processing the video; retry thumbnail upload later.")


def active_live_chat_id(service, broadcast_id: str | None = None) -> str | None:
    request = service.liveBroadcasts().list(part="snippet", id=broadcast_id) if broadcast_id else \
              service.liveBroadcasts().list(part="snippet", broadcastStatus="active", mine=True)
    response = request.execute()
    for item in response.get("items", []):
        chat_id = item.get("snippet", {}).get("liveChatId")
        if chat_id:
            return str(chat_id)
    return None
