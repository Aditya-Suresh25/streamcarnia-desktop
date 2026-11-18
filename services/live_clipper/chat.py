"""Optional live chat velocity. Any unavailable/disabled chat falls back to audio."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import RLock

import numpy as np


class LiveChatVelocity:
    def __init__(self, service, chat_id: str, max_age_seconds: int = 3600):
        self.service = service
        self.chat_id = chat_id
        self.max_age_seconds = max_age_seconds
        self._messages = deque()
        self._lock = RLock()
        self._page_token = None
        self.polling_interval_ms = 5000

    def poll(self):
        request = self.service.liveChatMessages().list(liveChatId=self.chat_id, part="snippet",
                pageToken=self._page_token) if self._page_token else self.service.liveChatMessages().list(
                liveChatId=self.chat_id, part="snippet")
        result = request.execute()
        self._page_token = result.get("nextPageToken")
        self.polling_interval_ms = int(result.get("pollingIntervalMillis", self.polling_interval_ms))
        with self._lock:
            for message in result.get("items", []):
                raw_time = message.get("snippet", {}).get("publishedAt")
                if raw_time:
                    published = datetime.fromisoformat(raw_time.replace("Z", "+00:00")).timestamp()
                    self._messages.append(published)
            cutoff = datetime.now(timezone.utc).timestamp() - self.max_age_seconds
            while self._messages and self._messages[0] < cutoff:
                self._messages.popleft()
        return self.polling_interval_ms / 1000.0

    def counts_for(self, wall_start: float, duration: float) -> np.ndarray:
        counts = np.zeros(int(np.ceil(duration)), dtype=np.float32)
        with self._lock:
            for timestamp in self._messages:
                offset = int(timestamp - wall_start)
                if 0 <= offset < len(counts):
                    counts[offset] += 1
        return counts
