# Browser Extraction

Use this after the user has logged in to Douyin in the in-app browser and the current tab is on:

`https://www.douyin.com/user/self?showTab=favorite_collection`

Run a browser-side read-only extraction with the in-app browser's Playwright API. Save the returned array as:

`Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/favorites_urls.json`

```js
const favorites = await tab.playwright.evaluate(async (options) => {
  const limit = options?.limit ?? 50;
  const maxRounds = options?.maxRounds ?? Math.max(20, Math.ceil(limit / 8) + 8);
  const stopAfterStable = options?.stopAfterStable ?? 6;
  const delayMs = options?.delayMs ?? 900;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalize = (href) => {
    try {
      const url = new URL(href, location.href);
      url.search = "";
      url.hash = "";
      return url.toString();
    } catch {
      return "";
    }
  };
  const isFavoriteUrl = (href) => /douyin\.com\/(video|note)\//.test(normalize(href));
  const markerElement = () => Array.from(document.querySelectorAll("input, textarea, div, span"))
    .find((el) => ((el.getAttribute("placeholder") || el.textContent || "").trim()).includes("搜索你收藏的作品"));
  const inFooterOrHeader = (el) => Boolean(el.closest("footer, [role='contentinfo'], header, [role='banner']"));
  const afterMarkerBeforeFooter = (el, marker) => {
    if (!marker) return false;
    const position = marker.compareDocumentPosition(el);
    if (!(position & Node.DOCUMENT_POSITION_FOLLOWING)) return false;
    return !inFooterOrHeader(el);
  };
  const readLinks = () => {
    const marker = markerElement();
    if (!marker) return [];
    const anchors = Array.from(document.querySelectorAll("a[href]")).filter((a) => {
      if (!isFavoriteUrl(a.getAttribute("href") || a.href || "")) return false;
      if (!afterMarkerBeforeFooter(a, marker)) return false;
      // Favorite cards have visible card text or a thumbnail. This excludes footer/hot links
      // that can share the same video URL pattern outside the collection list.
      return (a.innerText || a.textContent || "").trim() || a.querySelector("img, video");
    });
    return anchors.map((a) => {
      const href = normalize(a.getAttribute("href") || a.href || "");
      const text = (a.innerText || a.textContent || "").trim().replace(/\s+/g, " ");
      const imgAlt = Array.from(a.querySelectorAll("img[alt]"))
        .map((img) => img.getAttribute("alt"))
        .filter(Boolean)
        .join(" ");
      return { url: href, title: text || imgAlt, source: location.href };
    });
  };
  const getScrollContainer = () => {
    const marker = markerElement();
    const candidates = Array.from(document.querySelectorAll("body, main, div, section"))
      .filter((el) => (el.scrollHeight || 0) > (el.clientHeight || 0) + 300)
      .filter((el) => !marker || el.contains(marker))
      .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
    return candidates[0] || document.scrollingElement || document.documentElement;
  };

  const seen = new Map();
  let stableRounds = 0;
  let previousCount = -1;
  for (let round = 0; round < maxRounds && seen.size < limit; round += 1) {
    for (const item of readLinks()) {
      if (!seen.has(item.url)) seen.set(item.url, item);
      if (seen.size >= limit) break;
    }
    stableRounds = seen.size === previousCount ? stableRounds + 1 : 0;
    if (stableRounds >= stopAfterStable) break;
    previousCount = seen.size;

    const scroller = getScrollContainer();
    const distance = Math.max(600, Math.floor((scroller.clientHeight || window.innerHeight) * 0.9));
    scroller.scrollBy(0, distance);
    await sleep(delayMs);
  }
  for (const item of readLinks()) {
    if (!seen.has(item.url)) seen.set(item.url, item);
    if (seen.size >= limit) break;
  }
  return Array.from(seen.values()).slice(0, limit);
}, { limit: 42, maxRounds: 40, stopAfterStable: 6, delayMs: 900 }, { timeoutMs: 60000 });
```

If the returned list is shorter than requested while the page visibly has more favorites, inspect whether Douyin changed the link pattern or the scroll container. Do not fall back to a whole-page `a[href]` sweep: footer, hot-topic, recommendation, and page-cache links can share `/video/` or `/note/` URL patterns and contaminate the pull. Prefer one focused extraction pass bounded by the favorite-list marker `搜索你收藏的作品`, then scroll the dominant internal list container and accumulate unique URLs.

## CDP Detail Capture

Use this as the preferred detail/media path after collecting favorite URLs. Skip `/note/` image-text items before detail capture; they should be recorded as `skipped_note`, not opened for media capture. Do not replace this with page-title or visible-text summaries; the CDP path is what turns browser-visible non-entertainment videos into local video resources. Entertainment items are still classified and skipped before media download.

The captured detail response is the canonical source for engagement metadata and hashtags. Preserve `aweme.statistics` as `likes`, `comments`, `favorites`, and `shares`; preserve structured `text_extra` hashtags and hashtags in `desc` as final note `tags`. Do this before final summary rewriting, not as a later repair step.

Use this only after the user explicitly approves launching a debuggable browser.

Preferred authentication path: start an isolated Chrome profile and let the user log in manually when needed. Do not read existing Chrome cookies unless the user separately and explicitly approves that cookie access.

Cookie export is optional fallback, not the default. If the isolated Chrome profile cannot be logged in and the user explicitly prefers existing Chrome cookie export, ask for permission to read existing Chrome Douyin cookies, then export them into the pull record:

```bash
yt-dlp \
  --cookies-from-browser chrome \
  --cookies "Douyin Favorites/拉取记录/<pull-id>/json/douyin-cookies.txt" \
  --skip-download \
  "https://www.douyin.com/"
```

`yt-dlp` may still end with `Unsupported URL` for the Douyin homepage after exporting cookies. Treat the export as usable only if the cookie file exists and is non-empty; do not treat a non-zero exit alone as proof that export failed.

Do not print this file. It should remain under `拉取记录/<pull-id>/json/` and be deleted only after user-approved cleanup.

Start an isolated Chrome profile with a loopback-only debugging port and an allowed loopback WebSocket origin:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --remote-allow-origins=http://127.0.0.1:9222 \
  --user-data-dir="${TMPDIR:-/tmp}/douyin-cdp-profile" \
  "https://www.douyin.com/"
```

Inject the exported Douyin cookies into the isolated Chrome session:

```bash
PYTHONPATH=".tmp/pydeps" PYTHONPYCACHEPREFIX=".tmp/pycache" python3 \
  "Codex Skills/dy-faves-puller/scripts/inject_cookies_cdp.py" \
  --cookies "Douyin Favorites/拉取记录/<pull-id>/json/douyin-cookies.txt" \
  --port 9222 \
  --url "https://www.douyin.com/"
```

If export/injection is unavailable, or the temporary Chrome is still logged out, show the browser and let the user log in manually. If Douyin shows a verification/challenge page after cookie injection or login, such as CAPTCHA, slider verification, QR confirmation, SMS/OTP prompt, or another risk-control check, stop and tell the user to complete verification in that visible Chrome window. Resume capture only after the user confirms verification is complete.

Capture detail responses for video favorites from the current pull record; `/note/` image-text items are skipped and recorded as `skipped_note`. If the script is blocked from connecting to `127.0.0.1:9222` by sandboxing, rerun the same command with escalated permission:

```bash
PYTHONPATH=".tmp/pydeps" PYTHONPYCACHEPREFIX=".tmp/pycache" python3 \
  "Codex Skills/dy-faves-puller/scripts/cdp_capture_details.py" \
  --favorites "Douyin Favorites/拉取记录/<pull-id>/json/favorites_urls.json" \
  --output-dir "Douyin Favorites/拉取记录/<pull-id>/json/cdp-details" \
  --port 9222 \
  --timeout 45 \
  --manifest "Douyin Favorites/拉取记录/<pull-id>/json/cdp-capture-manifest.json"
```

Process the captured response bodies. Once all detail JSON has been captured, prefer Codex sub-agents over local threads/processes for per-video work. Use a conservative cap such as 2 or 3 sub-agents, assign each worker disjoint `--indices`, and have each worker write its own shard manifest with `--defer-registry`. Each worker should run `process_signed_details.py` only: this skill stops after local media, transcripts, staging draft notes, and manifest records exist. The parent agent should merge shard manifests and update the global registry after verification. `--max-workers` remains available as a local fallback when sub-agents are unavailable.

`process_signed_details.py` requires a Netscape cookie-file argument; start with a non-sensitive empty file because captured signed media URLs often download without cookies:

```bash
printf '# Netscape HTTP Cookie File\n' \
  > "Douyin Favorites/拉取记录/<pull-id>/json/empty-cookies.txt"
PYTHONPYCACHEPREFIX=".tmp/pycache" python3 \
  "Codex Skills/dy-faves-puller/scripts/process_signed_details.py" \
  --signed-details "Douyin Favorites/拉取记录/<pull-id>/json/cdp-capture-manifest.json" \
  --cookies "Douyin Favorites/拉取记录/<pull-id>/json/empty-cookies.txt" \
  --output "Douyin Favorites" \
  --model "Douyin Favorites/models/ggml-base.bin" \
  --transcribe-max-ms 0 \
  --manifest "Douyin Favorites/拉取记录/<pull-id>/json/run_manifest.json" \
  --merge-manifest \
  --keep-success
```

If download fails with the empty file, ask before using an exported real cookie file and rerun with `--cookies "Douyin Favorites/douyin-cookies.txt"`.

Verify local videos and detail-derived metadata before handing the manifest to `review-summarizer`. Entertainment records should be `skipped_entertainment` and have no media assets. Non-entertainment video records must have local media. For every `ok` item whose detail JSON includes `aweme.statistics` or hashtags, the staging note frontmatter must already contain non-empty engagement fields and tags. Fix capture/processing before asking the summary skill to write review notes.

```bash
python3 - <<'PY'
import json, pathlib, subprocess
m = json.load(open("Douyin Favorites/拉取记录/<pull-id>/json/run_manifest.json", encoding="utf-8"))
for item in m:
    if item.get("status") == "skipped_entertainment":
        if item.get("video") or item.get("audio") or item.get("transcript"):
            raise SystemExit(f"Entertainment item has media assets: {item.get('index')}")
        continue
    if item.get("status") not in {"ok", "note_only", "already_processed"}:
        raise SystemExit(f"Unresolved item status: {item.get('index')} {item.get('status')}")
    if item.get("content_type") == "note" and not item.get("video"):
        continue
    video = pathlib.Path(item["video"])
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-of", "default=nw=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    print(item["index"], video.name)
    print(result.stdout.strip())
PY
```

Close Chrome after capture and processing. Delete the temporary profile and exported cookie file after successful completion only when the user has approved that cleanup.
