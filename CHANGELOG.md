# Changelog

## StreamCarnia Studio 1.0.1 — 2026-11-18

### Added

- Added an opt-in **Auto Clipper (Live)** workflow with a separate monitor
  process, rolling stream segments, reconnect handling, and a persistent live
  clip queue.
- Added incremental live highlight detection using audio energy, with optional
  YouTube live chat velocity when the authorized channel provides chat access.
- Added configurable 20–60 second highlight windows, portrait layouts, animated
  captions, channel branding, progress/ETA, and handoff to the existing VOD
  editing pipeline.
- Added transcript-grounded Gemini metadata with a fallback title, approval
  gating, private YouTube uploads, scheduled publishing, and a six-upload daily
  cap.
- Added secure credential storage, `.env.example`, and a `live_clipper.enabled`
  feature flag that remains off by default.
- Added split audio/video HLS capture support for YouTube livestreams and
  Hindi-to-Hinglish captions in the live workflow. The original Devanagari
  transcript remains stored alongside rendered Hinglish captions.
- Added Live transcription model choices: Small, Medium (default), and
  Large-v3.

### Fixed

- Fixed Hindi transcript file encoding on Windows by using UTF-8.
- Fixed live capture failures when yt-dlp returns separate video and audio
  formats, including forwarding the formats' HTTP headers to FFmpeg.
- Improved per-clip failure recovery and preservation of successful partial
  results.
- Improved live clip progress reporting and ETA during long VOD-pipeline
  stages.
- Fixed a time-dependent live-chat test fixture so it remains valid after the
  fixture timestamp is more than one hour old.

### Compatibility

- The Live Auto Clipper remains disabled by default.
- Existing VOD clipping and regular stream downloads retain their existing
  workflow and settings.
