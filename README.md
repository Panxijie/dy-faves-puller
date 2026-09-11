# DY Faves Puller

`dy-faves-puller` is a Codex skill for collecting a signed-in Douyin account's favorite or collection items into local source materials. It captures item URLs and detail data, downloads media when appropriate, produces local transcripts, and records each run in a manifest for later review.

The skill stops at local evidence. It does not generate review summaries or publish notes; use a separate summarization workflow after a verified pull if needed.

## Install

Place this repository in Codex's skills directory (typically `~/.codex/skills/dy-faves-puller`) so that Codex can discover `SKILL.md`. The workflow expects access to an authenticated Douyin browser session and local tools such as Python, `yt-dlp`, `ffmpeg`, and optionally `whisper-cli`.

## Privacy and Safety

This skill operates on the account session you explicitly authorize. Do not commit browser profiles, exported cookies, signed media URLs, downloaded media, transcripts, pull manifests, or API keys. The repository's `.gitignore` excludes these local artifacts by default.

The skill uses an isolated Chrome profile for CDP capture and asks for explicit approval before accessing browser cookies. Complete login, CAPTCHA, QR, SMS, and other verification prompts manually.

Only collect content from accounts and sources you are authorized to access, and comply with the applicable platform terms.

## License

[MIT](LICENSE)
