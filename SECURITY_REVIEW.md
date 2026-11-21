# Desktop static security review

Scope: static review of the desktop Python application and the new Studio path. This is not a penetration test or a deployment security assessment. No real Google API calls or uploads were made.

## Findings and controls

- **Credentials:** YouTube OAuth tokens and Gemini keys use the existing `CredentialVault` backed by the operating system credential store. The new catalog stores clip metadata and publishing state only; it does not store OAuth tokens or Gemini keys. The desktop OAuth flow uses PKCE for the installed public client. Settings keep the OAuth client-file path, not its secret contents.
- **Local database:** The new SQLite catalog lives in `<Studio workspace>/.streamcarnia/studio_library.sqlite3`, separate from download history and the Live queue. SQL values are parameterized. Dynamic update column names are restricted to a fixed allowlist.
- **Media paths and subprocesses:** Imported sources are referenced in place. FFmpeg and ffprobe are invoked with argument lists, timeouts, and hidden Windows process windows; no shell command interpolation is used in the new media helpers. Studio renders, thumbnails, database files, and processing caches use the selected Studio workspace/media root.
- **Uploads:** Videos are uploaded privately with `publishAt`. Uploads use the existing scheduler and its six-per-hour and daily quota safeguards. An uncertain network result is recorded as `unknown` to avoid silent duplicate uploads; manual retry presents a duplicate-risk confirmation. Tests use local fixtures and mocks only.
- **Logs and UI errors:** New errors are shown with bounded exception text. They may include local filenames from an underlying library. Tokens and API keys are not intentionally included in Studio status text.

## Limits / follow-up before release

- Review third-party dependency vulnerabilities and licenses against the exact release lock/build environment. The repository uses version ranges for several dependencies and does not currently contain a generated lockfile or an installed `pip-audit` tool.
- Verify Qt Multimedia platform plugins and playback on a clean Windows machine after packaging; a successful build alone cannot verify codecs available on every Windows installation.
- OAuth account/channel identity is the identity Google authorized for the token. The YouTube Data API does not accept a `channelId` in `videos.insert`; channel switching must happen through the Google/YouTube account authorization flow.
- No live credentials, external endpoints, or real uploads were exercised as part of this review.
