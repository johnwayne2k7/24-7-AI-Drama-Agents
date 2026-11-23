# Analysis of the original: 24/7 Bots

This is a breakdown of `24-7-Bots.zip` (what it is, how each part works, what makes it good, and what I found worth fixing), followed by how **24/7 Drama Bots** reuses the idea.

## 1. What it is

A local, single-user tool for short-video creators (built for the Philippine market: Asia/Manila time, Taglish captions, TikTok Shop and Shopee affiliates). You drop finished videos, press **Run everything**, and a team of "bots" writes SEO captions, picks posting times and checks the work. Then the **Posting Bot** hands a step-by-step brief to the creator's own Claude (Claude Desktop + Claude in Chrome), which schedules the posts on TikTok Studio, Meta Business Suite (Facebook + Instagram) or YouTube Studio inside the creator's logged-in Chrome.

The "bots" are a presentation layer: the real work is a handful of AI calls plus Claude doing the clicking. The value is in packaging: one button, a cute pixel office, and very detailed platform instructions.

## 2. Files

| File | Size | Role |
|---|---|---|
| `server.py` | 464 lines | Python standard library only. HTTP server on `127.0.0.1:4181`, keeps the Groq key, calls Groq, validates affiliate links, saves files. |
| `static/index.html` | 1,543 lines, 274 KB | The entire app: CSS + HTML + vanilla JS in one file, very dense lines (up to 7,300 characters). No framework, no build step. |
| `static/assets/*.webp` | ~6 MB | Pixel-art sprite sheets: each bot head in 5 rotations × 4 expressions (idle, happy, working, worried), a grey cube "locked bot" sheet, the isometric office floor plate. |
| `start.bat` / `start.command` | | Finds a real Python (dodges the Microsoft Store fake `python.exe`), copies `.env.example` → `.env`, kills an old copy on the same port, opens Chrome, runs the server. |
| `.env.example` | | `GROQ_API_KEY`, `GROQ_CHAT_MODEL=openai/gpt-oss-120b`, `GROQ_STT_MODEL=whisper-large-v3-turbo`, `PORT`. |

## 3. The pipeline, bot by bot

| Bot | Input → output | How |
|---|---|---|
| **Drop videos** | Video files | Drag and drop; can also read an "outbox" folder where an editor saves videos (read-only, one folder). |
| **Thumbnail Bot** (YouTube) | Video → cover JPEG | The browser grabs frames, builds a numbered contact sheet, and a Groq vision model (`qwen…`) picks the frame with readable title text or a clear face. Saved next to the video. |
| **SEO Caption Bot** | Video → caption | `ffmpeg` extracts mono 16 kHz audio → Groq Whisper transcribes → `gpt-oss-120b` writes a caption. Three styles: *default* (10 search-phrase keywords, no hashtags, strict rules), *custom rules* (keyword/hashtag count, language, extra rules that override everything), *train on my captions* (few-shot from up to 15 past captions, can import PDF/DOCX/TXT). |
| **Scheduler Bot** | Videos → date/time slots | Manual times per day or auto-spacing between a start and end hour, day-of-week presets (every day, weekdays, Mon/Wed/Fri), Asia/Manila. |
| **Bot Manager** | All of the above → verdict | Runs the other bots and checks results (missing captions, bad slots) before you post. |
| **YB Bot** (affiliate) | TikTok Shop link → product ID + name | Follows redirects only on `tiktok.com` hosts and parses `/product/<id>` and `og_info`. |
| **SHP Bot** (affiliate) | Shopee link → affiliate check | Follows redirects only on Shopee hosts and checks for an `an_` affiliate ID; the Facebook caption gets a `Buy Here:` first line. |
| **Posting Bot** | Plan → brief for Claude | Builds a long plain-English brief (see section 4), serves it at `/brief`, copies a one-line prompt ("Open …/brief and do exactly what it says"), opens the first platform tab, then polls `/api/status` until the `/brief` hit counter goes up: that is how it knows Claude picked it up. |

Locked upsell nodes (Hook Writer, Affi Script, Reply Bot, Daily Report, Video Editor, RVS Revise) appear in the "lite"/"ccl" editions, controlled by one constant (`EDN`). The full edition also has an "Editing Suite" that hands editing jobs to Claude the same way.

## 4. The hand-off to Claude (the clever part)

- The brief contains **per-platform click-by-click rules**: e.g. on TikTok "the default is Now, which posts immediately, so you MUST select Schedule first… never click a button that says Post"; on Meta "set AM/PM first to avoid a red message that pushes the page down"; on YouTube "check both the Videos and Shorts tabs to verify".
- **Big-file trick:** Chrome's upload tool only takes 10 MB, so Claude is told to split the video into 9 MB pieces with a shell command, inject a hidden `<input type=file>` with JavaScript, upload each piece, rejoin them into a `File` in the page, and hand it to the platform's own input via `DataTransfer`.
- **Safety rules:** human pace, schedule only, never post now, stop on any login/captcha/unexpected dialog, verify against the scheduled list at the end.

## 5. The front end

- **Two views:** a node-graph canvas (stations wired together, wires animate orange while working and green when done, nodes pulse green/red) and an **isometric pixel office** drawn on `<canvas>`: bots walk between desks with path-finding, go for coffee and queue when the seats are full, play arcade games, chat in pairs with canned lines, rush back to their desks when a job starts. There is also a synthesized sound and music engine.
- **Bot log** chat feed that mirrors every action, speech bubbles over the bots, a first-run setup guide, an animated "How to use" with inline SVGs, toasts and a drag-and-drop overlay.
- State is kept in memory plus `localStorage`; the server only stores the key, the brief and the training text.

## 6. What makes it work (patterns worth keeping)

1. **One button.** All complexity hides behind "Run everything" → "Hand to Claude".
2. **Personified progress.** A spinner is boring; a bot that says "On it!" and walks to its desk is not. People keep the tab open.
3. **Visible state.** Every station shows working / waiting / done, so you always know what is blocking.
4. **Rules that win.** The user's own rules are injected last with "these win over every rule above", which makes the AI obey custom formats.
5. **Local and private.** The key never reaches the browser; only one port on 127.0.0.1.
6. **Defensive server code:** stdlib only, path checks on static files, host allow-lists on link checkers, upload size limits, a 30-calls-per-minute limit, the fake-Python check in the launcher.

## 7. Weak spots I found

- **Most API endpoints can be called by other websites.** Only the outbox endpoints check the `Host` header and a custom `X-SMM` header. `POST /api/brief`, `/api/key`, `/api/train` and `/api/thumb` accept a plain cross-site form-style POST (the server parses the body as JSON whatever its content type). A malicious page open in the same browser could therefore **replace the posting brief**, and the next time the creator presses Hand to Claude, Claude would read the attacker's instructions while logged in to their social accounts. It could also overwrite the Groq key, the training text, or write `.jpg` files into any existing folder. Newer Chrome versions ask before a public site can reach `localhost`, which reduces this but does not remove it. Fix: require a localhost `Host` and a custom header on every `/api/*` route (that is what my version does).
- One 274 KB HTML file with very long lines is hard to maintain or customize.
- No saved projects: closing the tab loses the plan (besides the brief).
- Hard-coded time zone (Asia/Manila) and Chrome-only posting.
- ~6 MB of sprite art, all of it custom to that product.

## 8. How 24/7 Drama Bots reuses the idea

| | 24/7 Bots | 24/7 Drama Bots |
|---|---|---|
| Job | Caption and schedule finished videos | **Write and pre-produce a whole serialized AI drama** |
| Input | Video files | An idea + tropes + format (or "Pitch me 5 ideas") |
| Bots | Thumbnail, SEO Caption, Scheduler, Manager, Posting, YB, SHP | Showrunner, Hook, Script, Cliffhanger, Script Doctor, Shot, Release, Voice |
| Quality gate | Manager checks fields | Script Doctor scores hook/tension/twist/cliffhanger/dialogue/binge and rewrites below your bar |
| Output | Captions, times, Claude brief | Series bible, episode map, scripts, AI image + video prompts with consistent characters, captions, pinned comments, drop schedule, Markdown production pack |
| "Wow" view | Pixel office | Studio floor + writers' room banter + **in-browser animatic** with voices and a binge countdown |
| AI | Groq only | Groq by default, or OpenRouter / OpenAI / any OpenAI-compatible model |
| Saving | Mostly in-memory | Every step saved to `projects/`; pause and continue any time |
| Security | Partial | Every API route requires localhost `Host` + custom header |
| Art | Licensed sprite sheets | Bots drawn in CSS: no image assets copied from the original |

Same architecture (stdlib Python server + vanilla JS, double-click launchers, key in `.env`), new purpose, new code.
