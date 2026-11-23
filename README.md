# 24/7 Drama Bots

*Created by **John Wayne Maquinta**.*

Your own AI micro-drama studio. Type an idea, press one button, and a crew of bots writes a whole serialized drama season for TikTok, Reels or Shorts. Every episode opens with a 3-second hook, escalates scene by scene, and ends on a cliffhanger. Then the bots hand you the AI video prompts, captions and a release schedule, and let you watch each episode as a voiced animatic.

It runs only on your computer.

## What you need
- **Python 3** (python.org/downloads). On Windows, tick "Add python.exe to PATH" when you install it.
- A free **Groq key** (console.groq.com/keys). OpenRouter, OpenAI or any OpenAI-compatible model (even a local one) also work.
- **ChatGPT models:** use an OpenAI API key from platform.openai.com/api-keys with billing turned on. A ChatGPT Plus subscription does not include API use. In ⚙ AI key pick *OpenAI (ChatGPT API)*, paste the key, press **Load models**, pick one, then **Save & test**. Models that reject some settings (temperature, reasoning effort, token limits) are handled automatically.

## Start it
- **Windows:** double-click `start.bat`. If you see "Windows protected your PC", click More info, then Run anyway.
- **Mac:** double-click `start.command` (if macOS blocks it: System Settings → Privacy & Security → Open Anyway).
- Your browser opens **http://localhost:4247**. Click **⚙ AI key** and paste your key. Close the black window to stop the studio.

No key yet? Open the project menu (top left) → **🎞 Demo season** to see a finished example ("The Last Text") and watch its animatic.

## The crew

| Station | Bot | What it does |
|---|---|---|
| 💡 Premise | **You** | Your idea, tropes, language (English, Taglish, Tagalog…), platform, episode count and length, visual style. Or press **Pitch me 5 ideas**. |
| 🎬 Showrunner Bot | **DIREK** | Builds the series bible: title, cast with fixed looks, the central secret, and the season arc (first reveal, midpoint twist, dark moment, finale twist, season-2 hook). Plans the episode map 10 episodes at a time. |
| 🪝 Hook Bot | **HOOKY** | Writes the first 3 seconds of every episode, plus alternates. No intros: start at the slap. |
| ✍️ Script Bot | **PEN** | Writes the scenes: timing, location, visuals, dialogue with emotions, on-screen text, sound cues. Each episode picks up right on the last cliffhanger. |
| 💣 Cliffhanger Bot | **BITIN** | Writes 3 different endings, picks the most addictive one, rewrites the final scene to cut on it. Never the same cliffhanger type twice in a row. |
| 🩺 Script Doctor | **DOC** | Scores hook, tension, twist, cliffhanger, dialogue and binge (1–10). Below your quality bar, the hook and lines get rewritten. |
| 🎥 Shot Bot | **LENS** | Writes an image prompt (first frame) and a video prompt (motion) for every shot, restating each character's look so faces stay consistent. |
| 📣 Release Bot | **HYPE** | Caption, hashtags, Shorts title, thumbnail text + prompt, pinned comment that baits replies, next-episode teaser, and the drop time for every episode. |
| 🎙 Voice Bot | **ECHO** | Plays any episode as a vertical animatic with a voice per character, ending on a freeze-frame cliffhanger and a countdown into the next episode. |

### Office view
The studio floor opens in **Office view**: an isometric drama studio drawn in code, with DIREK's office and season board, the writers' room, the Script ER with DOC's live scorecard, the sound stage with a green screen, the voice booth with its ON AIR light, HYPE's phone wall, a lounge with a TV, sofa, beanbags and coffee bar, and a game corner. Between jobs the bots wander, get coffee, sit on the sofa, play arcade games and chat with each other. When you press ▶ Produce season, DIREK shouts "Places, everyone!" and they all run to their desks, and their monitors light up while they work. Click a bot, or a board on the wall, to open its desk. Use the + / − / ⟲ buttons (or Ctrl + mouse wheel) to zoom, and drag to move around. **🗺 Canvas view** switches back to the flowchart.

Talk to the writers in the **Writers' room** box ("make it darker", "more slaps", "the mother is the villain"): every next episode follows your notes. Open any episode to **rewrite it with notes**, **punch it up again**, or **redo its storyboard and caption**.

## The formula every episode follows
1. **Hook in 3 seconds.** Open at the peak of an emotion or in the middle of an action. The first line plants a question the viewer needs answered.
2. **Open loops.** Answer one question, open a bigger one. Never answer everything.
3. **Escalate every scene.** 2–4 reversals. Something always gets worse, a secret gets closer, or the power flips.
4. **Dramatic irony.** The viewer knows a secret a character doesn't.
5. **Cliffhanger on the last frame.** Cut mid-reveal, mid-decision, mid-danger. The last line is a bomb or an unbearable question.
6. **Vary the cliffhangers.** Shock reveal, identity reveal, betrayal, danger, arrival, overheard secret, impossible choice, ticking clock, evidence found, the phone call… never the same type twice in a row.
7. **Plant and pay off.** Twists feel shocking but inevitable.

All of it lives in `drama_prompts.py`, so you can tune the rules yourself.

## From script to video (inside the studio)
Add a **Gemini API key** (Google AI Studio → Get API key) in **⚙ AI key → Images, voices & video**. One key does all three:

| Button (episode → 🎬 Images & voices tab) | What it makes | Model | Rough cost |
|---|---|---|---|
| 🎨 **Make images** | A character reference image per character, then one vertical image per storyboard shot that reuses those faces | `gemini-nano-banana-2.1` (Fast / Standard / Best on ECHO's desk) | cents per episode |
| 🎙 **Make voices** | A real voice for every line, one fixed voice per character (Filipino/Taglish supported), with the line's emotion | `gemini-3.8-flash-tts` | cents per episode |
| 🎬 **Hero clips** | Real moving video for the hook and the cliffhanger shots, starting from their images (it asks before spending) | `gemini-omni-1.2-flash`, 720p | about $0.07 per second, about $1 per episode |
| ⬇ **Export video** | Records the whole episode as a 720×1280 MP4 (WebM on browsers without MP4) with voices, subtitles, on-screen text and the cliffhanger end card | in your browser | free |

**▶ Watch** then plays the real thing: shot images with slow camera moves, the Omni clips, every character's voice, and the freeze on the cliffhanger. Change each character's voice (with ▶ preview), image quality, clip size, and whether Omni speaks the line itself (English works best) on **ECHO's desk**. Everything is saved in `projects/<project>_media/`. Keep the player window open and visible while exporting.

### Prefer Google Flow, Gemini, Veo, CapCut…? Use the 🎞 Prompts tab
Every episode has a **🎞 Prompts** tab with, for each shot:
- **🖼 Image prompt**, for the first frame.
- **🎥 Video prompt with dialogue**: the camera move, the scene, every visible character's fixed look, the lines written in for lip-sync (in your series' language, with emotions), the sound, and "vertical 9:16, about N seconds".
- **🗣 Voice lines**, for dubbing or text-to-speech tools.

The character reference prompts are at the top. **Copy all 3** copies one shot; **Copy all prompts** or **⬇ Download .txt** takes the whole episode. The same prompts are in the **⬇ Production pack**.

Then post at HYPE's drop time with the caption, and pin HYPE's comment right after posting.

**⬇ Production pack** exports everything (bible, cast, episode map, every script, storyboard and caption) as one Markdown file. **⬇ Backup** saves the project as JSON, which you can import from the project menu.

## Free plan limits
Free AI plans limit how much you can generate per minute and per day. When the AI says "slow down", the bots take a ☕ coffee break and continue by themselves. When the daily limit is reached, they stop and tell you; everything is saved after every step, so press **▶ Continue** later and they pick up where they left off. To use less: shorter episodes, fewer episodes, or turn off storyboard prompts on the Shot Bot desk.

## Settings (`.env`)
| Setting | Default | |
|---|---|---|
| `GROQ_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `CUSTOM_API_KEY` | | One key per provider, set with the ⚙ AI key button. Each key is only ever sent to its own provider. |
| `AI_BASE_URL` | `https://api.groq.com/openai/v1` | The provider in use. Any OpenAI-compatible `/chat/completions` endpoint works. |
| `AI_MODEL` | `openai/gpt-oss-120b` | The model in use. |
| `AI_REASONING` | `low` | `low`, `medium` or `high` for gpt-oss and OpenAI reasoning models. |
| `PORT` | `4247` | |
| `DRAMA_MOCK` | `0` | `1` = fake answers, to try the whole pipeline with no key or internet. |

## Privacy and files
- Your key is saved only in `.env` next to the tool and sent only to the AI provider you picked. Never share `.env`.
- Projects are saved in `projects/` as JSON. Deleting a project moves it to `projects/.trash/`.
- The server listens only on this computer (127.0.0.1) and only answers its own page: other websites cannot call it.
