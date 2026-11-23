"""The story engine of 24/7 Drama Bots.

Every prompt the bots use lives here. Each task has:
  build(inp)  -> (system_prompt, user_prompt, max_tokens, temperature)
  clean(data, inp) -> a normalized dict the browser can trust
"""
import json
import random
import re

# --------------------------------------------------------------------------------------------
# The rules of the room: shared by every writing task
# --------------------------------------------------------------------------------------------
CRAFT = """You are the writers' room of a hit vertical micro-drama studio. Episodes are short, watched on phones, and binged one after another. Your only job: make it impossible to swipe away, and impossible not to watch the next episode.

THE RULES OF THE ROOM
1. HOOK IN 3 SECONDS. Open at the peak of an emotion or in the middle of an action: a slap, a confession, a betrayal caught in the act, a slammed door, a scream, a shocking line. No establishing shots, no waking up, no introductions, no weather. The first line or on-screen text plants a question the viewer NEEDS answered.
2. OPEN LOOPS. Each episode answers at most one old question and opens at least one new, bigger one. Never answer everything.
3. ESCALATE EVERY SCENE. Every scene turns: something gets worse, a secret gets closer to exploding, or the power flips. 2 to 4 reversals per episode. No scene where nothing changes.
4. DRAMATIC IRONY. Let the viewer know something a character does not, so every conversation is charged.
5. CHARACTERS WITH SECRETS. The hero wants something badly and is hiding something. The villain is smart, petty and believable. Every main character has a secret that will detonate later.
6. DIALOGUE THAT HITS. Short, quotable lines (mostly under 12 words). Subtext over exposition. People never explain what they both already know. Each character has a distinct voice.
7. CLIFFHANGER ON THE LAST FRAME. Cut at the exact moment of maximum tension: mid-reveal, mid-decision, mid-danger, the door opening, the name about to be said, the test result unfolding. The last line is a bomb or an unbearable question. Never end on a resolution, a hug, a summary, or a character explaining their feelings.
8. VARY THE CLIFFHANGERS. Rotate types: shock reveal, identity reveal, betrayal, danger, arrival, overheard secret, impossible choice, ticking clock, evidence found, misunderstanding, power reversal, the phone call, the almost-kiss, someone collapses. Never the same type twice in a row.
9. PLANT AND PAY OFF. Plant clues early and pay them off later. Twists feel shocking but inevitable.
10. BUILT FOR PHONES AND AI VIDEO. Vertical 9:16. Mostly close-ups and two-shots, few locations, few characters per scene, strong facial emotion, short scenes.
11. PLATFORM-SAFE. Big emotions, but no explicit sex, no graphic gore, no hate. The drama comes from stakes, secrets and emotion.
12. LINES ARE SPOKEN. Every "line" in your JSON is words a character (or the VO narrator) says out loud, including the hook line and the cliffhanger line. Never put actions, sounds or stage directions in a line (no "*door slams*", no "(she gasps)"): actions go in "visual", sounds go in "sfx"."""

CLIFF_TYPES = ["shock reveal", "identity reveal", "betrayal", "danger", "arrival", "overheard secret",
               "impossible choice", "ticking clock", "evidence found", "misunderstanding", "power reversal",
               "the phone call", "almost-kiss", "someone collapses"]

PLATFORM_RULES = {
    "TikTok": "TikTok: caption 80 to 150 characters before the hashtags, punchy, one emoji at most.",
    "Facebook Reels": "Facebook Reels: 1 to 3 short emotional lines that make people take sides, then the hashtags.",
    "YouTube Shorts": "YouTube Shorts: the title matters most; the caption is a 1 to 2 line description.",
    "Instagram Reels": "Instagram Reels: 1 to 2 lines, then the hashtags.",
}


def clip(v, n):
    s = " ".join(str(v if v is not None else "").split())
    return s[:n]


def as_list(v):
    return v if isinstance(v, list) else ([] if v in (None, "") else [v])


def to_int(v, lo, hi, dflt):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return dflt


def lang_rule(lang):
    lang = clip(lang, 40) or "English"
    if lang == "English":
        t = "LANGUAGE: write all dialogue, voice-over, on-screen text, titles and captions in natural, modern English."
    elif lang == "Taglish":
        t = ("LANGUAGE: write all dialogue, voice-over, on-screen text, titles and captions in natural Taglish: casual Filipino "
             "mixed with English, the way people really talk in Metro Manila. Never Cebuano or Bisaya. "
             "Scene descriptions stay in English.")
    elif lang == "Tagalog":
        t = ("LANGUAGE: write all dialogue, voice-over, on-screen text, titles and captions in everyday conversational "
             "Tagalog/Filipino (not deep or formal Tagalog). Scene descriptions stay in English.")
    else:
        t = ("LANGUAGE: write all dialogue, voice-over, on-screen text, titles and captions in natural, everyday %s. "
             "Scene descriptions stay in English." % lang)
    return t + " AI image and video prompts are ALWAYS in English."


def premise_of(inp):
    p = inp.get("premise") or {}
    eps = to_int(p.get("episodes"), 3, 30, 10)
    length = to_int(p.get("length"), 30, 300, 60)
    return {
        "idea": clip(p.get("idea"), 1500),
        "genres": [clip(g, 40) for g in as_list(p.get("genres"))[:10]],
        "language": clip(p.get("language"), 40) or "English",
        "episodes": eps,
        "length": length,
        "platform": clip(p.get("platform"), 40) or "TikTok",
        "tone": clip(p.get("tone"), 80),
        "style": clip(p.get("style"), 80) or "Cinematic photoreal",
        "audience": clip(p.get("audience"), 120),
        "rules": clip(p.get("rules"), 900),
    }


def owner_rules(p, notes=None):
    out = ""
    if p.get("rules"):
        out += ("\n\nTHE CREATOR'S OWN RULES. These come from the creator and win over every rule above. Follow them exactly. "
                "If they name a person, place or word, use their spelling:\n" + p["rules"])
    notes = [clip(n, 300) for n in as_list(notes) if clip(n, 300)]
    if notes:
        out += "\n\nDIRECTOR'S NOTES (follow these from now on):\n- " + "\n- ".join(notes[-12:])
    return out


def setup_line(p):
    return ("FORMAT: %d episodes, about %d seconds each, posted on %s. Visual style: %s.%s%s%s"
            % (p["episodes"], p["length"], p["platform"], p["style"],
               (" Tone: " + p["tone"] + ".") if p["tone"] else "",
               (" Audience: " + p["audience"] + ".") if p["audience"] else "",
               (" Genres and tropes: " + ", ".join(p["genres"]) + ".") if p["genres"] else ""))


def scene_budget(length):
    words = int(round(length * 2.3))
    if length <= 45:
        sc = (3, 4)
    elif length <= 60:
        sc = (4, 5)
    elif length <= 90:
        sc = (5, 7)
    elif length <= 120:
        sc = (6, 8)
    else:
        sc = (7, 10)
    return words, sc


def bible_brief(b, looks=False):
    if not isinstance(b, dict):
        return {}
    chars = []
    for c in as_list(b.get("characters"))[:8]:
        if not isinstance(c, dict):
            continue
        d = {k: clip(c.get(k), 220) for k in ("name", "role", "gender", "age", "want", "secret", "voice")}
        if looks:
            d["look"] = clip(c.get("look"), 450)
        chars.append(d)
    arc = b.get("season_arc") if isinstance(b.get("season_arc"), dict) else {}
    return {"title": clip(b.get("title"), 100), "logline": clip(b.get("logline"), 400),
            "central_secret": clip(b.get("central_secret"), 400), "theme": clip(b.get("theme"), 200),
            "world": clip(b.get("world"), 300), "characters": chars,
            "season_arc": {k: clip(v, 300) for k, v in arc.items()}}


def j(o):
    return json.dumps(o, ensure_ascii=False)


# --------------------------------------------------------------------------------------------
# PITCH: 5 bingeable series ideas
# --------------------------------------------------------------------------------------------
def b_pitch(inp):
    p = premise_of(inp)
    sysm = CRAFT + "\n\n" + lang_rule(p["language"]) + """

TASK: Pitch 5 DIFFERENT micro-drama series. Each must be instantly bingeable: a killer premise with irony built in, a central secret that can carry a whole season, and an opening that hooks in 3 seconds. Make the 5 pitches different from each other in setting, trope and tone. Titles are short and punchy (2 to 5 words).
Answer ONLY with JSON in exactly this shape:
{"pitches":[{"title":"","logline":"one sentence with the irony or secret in it","opening_hook":"what happens in the first 3 seconds of episode 1","secret":"the central secret that drives the season","why_bingeable":"one line","genres":["",""]}]}"""
    user = ("Creator's seed idea (if empty, surprise me): %s\n%s" % (p["idea"] or "(empty)", setup_line(p))) + owner_rules(p)
    return sysm, user, 3000, 1.0


def c_pitch(d, inp):
    out = []
    for x in as_list(d.get("pitches"))[:6]:
        if isinstance(x, dict) and clip(x.get("title"), 90):
            out.append({"title": clip(x.get("title"), 90), "logline": clip(x.get("logline"), 400),
                        "opening_hook": clip(x.get("opening_hook"), 400), "secret": clip(x.get("secret"), 400),
                        "why_bingeable": clip(x.get("why_bingeable"), 200),
                        "genres": [clip(g, 30) for g in as_list(x.get("genres"))[:4]]})
    if not out:
        raise ValueError("no pitches")
    return {"pitches": out}


# --------------------------------------------------------------------------------------------
# BIBLE: title, characters, central secret, season arc
# --------------------------------------------------------------------------------------------
def b_bible(inp):
    p = premise_of(inp)
    sysm = CRAFT + "\n\n" + lang_rule(p["language"]) + """

TASK: You are DIREK, the showrunner. Build the SERIES BIBLE for a %d-episode season.
Season shape:
- Episode 1: cold open in the middle of the inciting betrayal or shock; it ends with a cliffhanger that makes the premise explode.
- Around 25%%: the first big reveal, which changes how we see a character.
- Around 50%%: the MIDPOINT TWIST that flips everything (an ally is an enemy, the victim is the villain, the secret is bigger than we thought).
- Around 75%%: the darkest moment. The hero loses almost everything.
- Final episode: the central secret pays off in the most satisfying way, then one last twist that hooks a season 2.
Characters: 3 to 6 main characters. "look" is a FIXED visual description reused in every AI image: age, ethnicity, face, hair, build, signature outfit and one distinctive detail. Make it specific enough that an AI image tool draws the same person every time.
The central secret must be something the viewer can feel coming but cannot fully guess.
Answer ONLY with JSON in exactly this shape:
{"title":"","alt_titles":["",""],"logline":"","tagline":"","central_secret":"","theme":"","world":"setting in 1 or 2 sentences","characters":[{"name":"","role":"hero | villain | love interest | ally | wildcard","gender":"female | male","age":"","look":"","want":"","wound":"","secret":"","voice":"how they talk"}],"season_arc":{"setup":"","first_reveal":"","midpoint_twist":"","dark_moment":"","finale_twist":"","season2_hook":""}}""" % p["episodes"]
    user = ("THE IDEA: %s\n%s" % (p["idea"] or "(no idea given: invent the most bingeable premise you can for these genres)", setup_line(p))
            + (("\nNOTES FOR THIS VERSION OF THE BIBLE: " + clip(inp.get("notes"), 600)) if inp.get("notes") else "")
            + owner_rules(p, inp.get("director_notes")))
    return sysm, user, 4000, 0.9


def c_bible(d, inp):
    chars = []
    for c in as_list(d.get("characters"))[:8]:
        if isinstance(c, dict) and clip(c.get("name"), 60):
            g = clip(c.get("gender"), 20).lower()
            chars.append({"name": clip(c.get("name"), 60), "role": clip(c.get("role"), 40),
                          "gender": "male" if g.startswith("m") else ("female" if g.startswith("f") else "other"),
                          "age": clip(c.get("age"), 20), "look": clip(c.get("look"), 600), "want": clip(c.get("want"), 300),
                          "wound": clip(c.get("wound"), 300), "secret": clip(c.get("secret"), 300), "voice": clip(c.get("voice"), 200)})
    if not chars or not clip(d.get("title"), 100):
        raise ValueError("bible incomplete")
    arc = d.get("season_arc") if isinstance(d.get("season_arc"), dict) else {}
    keys = ["setup", "first_reveal", "midpoint_twist", "dark_moment", "finale_twist", "season2_hook"]
    return {"title": clip(d.get("title"), 100), "alt_titles": [clip(t, 100) for t in as_list(d.get("alt_titles"))[:4]],
            "logline": clip(d.get("logline"), 500), "tagline": clip(d.get("tagline"), 200),
            "central_secret": clip(d.get("central_secret"), 600), "theme": clip(d.get("theme"), 300),
            "world": clip(d.get("world"), 500), "characters": chars, "season_arc": {k: clip(arc.get(k), 500) for k in keys}}


# --------------------------------------------------------------------------------------------
# MAP: plan a range of episodes (chunked so long seasons fit small rate limits)
# --------------------------------------------------------------------------------------------
def b_map(inp):
    p = premise_of(inp)
    a = to_int(inp.get("from"), 1, 30, 1)
    b = to_int(inp.get("to"), a, 30, a)
    sysm = CRAFT + "\n\n" + lang_rule(p["language"]) + """

TASK: You are DIREK, the showrunner. Plan episodes %d to %d of a %d-episode season, following the bible and its season arc. Every episode follows the rules of the room: a hook in 3 seconds, 2 to 4 reversals, a cliffhanger on the last frame, and a different cliffhanger type from the episode before it. Each episode picks up from the previous cliffhanger.
Answer ONLY with JSON in exactly this shape (one entry per episode, n from %d to %d):
{"episodes":[{"n":%d,"title":"short punchy title","hook":"the first 3 seconds","beats":["beat","beat","beat"],"twist":"the reversal of this episode","cliffhanger":"the last frame and last line","cliffhanger_type":"","opens":["new question the viewer now has"],"closes":["old question answered, or leave empty"]}]}""" % (a, b, p["episodes"], a, b, a)
    prev = [x for x in as_list(inp.get("planned")) if isinstance(x, dict)][-12:]
    user = ("SERIES BIBLE:\n" + j(bible_brief(inp.get("bible"))) + "\n\n" + setup_line(p)
            + ("\n\nEPISODES ALREADY PLANNED (continue from these):\n" + "\n".join(
                "%s. %s | cliffhanger (%s): %s" % (x.get("n"), clip(x.get("title"), 80), clip(x.get("cliffhanger_type"), 30),
                                                   clip(x.get("cliffhanger"), 200)) for x in prev) if prev else "")
            + owner_rules(p, inp.get("director_notes")))
    return sysm, user, 900 + 420 * (b - a + 1), 0.9


def clean_plan(x, n):
    return {"n": n, "title": clip(x.get("title"), 100) or "Episode %d" % n, "hook": clip(x.get("hook"), 400),
            "beats": [clip(s, 300) for s in as_list(x.get("beats"))[:6]], "twist": clip(x.get("twist"), 400),
            "cliffhanger": clip(x.get("cliffhanger"), 400), "cliffhanger_type": clip(x.get("cliffhanger_type"), 40).lower(),
            "opens": [clip(s, 200) for s in as_list(x.get("opens"))[:4]],
            "closes": [clip(s, 200) for s in as_list(x.get("closes"))[:4]]}


def c_map(d, inp):
    a = to_int(inp.get("from"), 1, 30, 1)
    b = to_int(inp.get("to"), a, 30, a)
    got = [x for x in as_list(d.get("episodes")) if isinstance(x, dict)]
    out = []
    for i, n in enumerate(range(a, b + 1)):
        x = next((e for e in got if to_int(e.get("n"), 0, 99, -1) == n), None) or (got[i] if i < len(got) else None)
        if x is None:
            break
        out.append(clean_plan(x, n))
    if not out:
        raise ValueError("no episodes planned")
    return {"episodes": out}


# --------------------------------------------------------------------------------------------
# WRITE: Hook Bot + Script Bot write one episode
# --------------------------------------------------------------------------------------------
SCENE_SHAPE = '{"n":1,"time":"0:00-0:03","location":"INT. PLACE - NIGHT","visual":"what the camera sees, with the emotion on faces","lines":[{"speaker":"Name, or VO for narration","line":"","emotion":"one word"}],"onscreen_text":"","sfx":"sound or music cue"}'


DIRECTION_RE = re.compile(r"^\s*[\*\(\[](.+?)[\*\)\]]\s*$")
PAREN_RE = re.compile(r"\s*[\*\(\[][^\*\)\]]{0,80}[\*\)\]]\s*")


def is_direction(s):
    """True when a 'line' is really a stage direction or sound, like *door slams* or (she gasps)."""
    return bool(DIRECTION_RE.match(str(s or "")))


QUOTE_RE = re.compile(r"[“\"]([^”\"]{3,200})[”\"]")


def spoken(s):
    """Remove inline stage directions and wrapping quotes: '"Sino ka?" *slaps him*' -> 'Sino ka?'."""
    s = " ".join(PAREN_RE.sub(" ", str(s or "")).split())
    return s[1:-1].strip() if len(s) > 1 and s[0] in "\"“" and s[-1] in "\"”" else s


def split_spoken(s):
    """'Rosa gasps, "Marco lied," as the gun clicks.' -> ('Marco lied', 'Rosa gasps, as the gun clicks.'). None if plain dialogue."""
    s = str(s or "")
    m = QUOTE_RE.search(s)
    if not m:
        return None
    rest = " ".join((s[:m.start()] + " " + s[m.end():]).split())
    if len(rest.split()) < 2:
        return None
    return m.group(1).strip(" ,"), rest


def norm(s):
    return " ".join(re.sub(r"[^\w]+", " ", str(s or "").lower()).split())


def same_line(a, b):
    na, nb = norm(a), norm(b)
    return bool(na and nb) and (na == nb or (min(len(na), len(nb)) >= 8 and (na in nb or nb in na)))


def end_on(scene, cliff):
    """Make the final scene cut exactly on the cliffhanger line. Returns the line the episode really ends on."""
    for i, l in enumerate(scene["lines"]):
        if same_line(l["line"], cliff.get("line")):
            scene["lines"] = scene["lines"][:i + 1]  # the AI kept writing after the cliffhanger: cut there
            return l["line"]
    if cliff.get("line") and cliff.get("speaker"):
        scene["lines"].append({"speaker": cliff["speaker"], "line": cliff["line"], "emotion": "shocked"})
        return cliff["line"]
    return scene["lines"][-1]["line"] if scene["lines"] else cliff.get("line", "")


def clean_cliff(c, extra_visual=""):
    """Normalize a cliffhanger/option: speaker + spoken line + visual, splitting narration from dialogue."""
    c = c if isinstance(c, dict) else {"line": c}
    line, visual = clip(c.get("line"), 300), clip(c.get("visual"), 400) or extra_visual
    sp = split_spoken(line)
    if sp:
        line, visual = sp[0], clip(sp[1] + " " + visual, 400)
    return {"type": clip(c.get("type"), 40).lower().replace("_", " "), "speaker": clip(c.get("speaker"), 40),
            "line": spoken(line) or line, "visual": visual}


def clean_line(x):
    if not isinstance(x, dict):
        return None
    line = clip(x.get("line") or x.get("text"), 400)
    if not line:
        return None
    return {"speaker": clip(x.get("speaker") or x.get("character") or "VO", 40), "line": line, "emotion": clip(x.get("emotion"), 24).lower()}


def clean_scene(x, n):
    if not isinstance(x, dict):
        return None
    visual, lines = clip(x.get("visual"), 600), []
    for l in (clean_line(y) for y in as_list(x.get("lines") or x.get("dialogue"))[:14]):
        if not l:
            continue
        if is_direction(l["line"]):  # an action or sound slipped into the dialogue: move it to the visual
            visual = clip((visual + " " + DIRECTION_RE.match(l["line"]).group(1).strip(" .") + ".").strip(), 700)
            continue
        l["line"] = spoken(l["line"]) or l["line"]
        if not re.search(r"\w", l["line"]):  # just "…": nothing to say
            continue
        lines.append(l)
    return {"n": n, "time": clip(x.get("time"), 20), "location": clip(x.get("location"), 120), "visual": visual,
            "lines": lines, "onscreen_text": clip(x.get("onscreen_text"), 80), "sfx": clip(x.get("sfx"), 160)}


def b_write(inp):
    p = premise_of(inp)
    n = to_int(inp.get("n"), 1, 30, 1)
    words, (s1, s2) = scene_budget(p["length"])
    cont = ("This is EPISODE 1: open cold in the middle of the most shocking moment, then let the viewer catch up through action and dialogue, never through narration that explains everything."
            if n == 1 else
            "Pick up DIRECTLY from the previous cliffhanger below. Open on that moment at its most intense, then twist it or only partly resolve it. Never ignore it, never fully defuse it.")
    sysm = CRAFT + "\n\n" + lang_rule(p["language"]) + """

TASK: You are HOOKY (hooks) and PEN (script). Write EPISODE %d of %d as a shooting script.
Runtime about %d seconds, about %d spoken words in total (dialogue plus voice-over). %d to %d short scenes.
%s
Scene 1 IS the hook and lasts about 3 seconds. Use timing marks like "0:00-0:03".
End on the planned cliffhanger (sharpen it if you can). The final scene cuts on the cliffhanger frame: its last line is the cliffhanger line.
Use "VO" as the speaker for narration, and use narration sparingly.
Answer ONLY with JSON in exactly this shape:
{"title":"","hook":{"visual":"what we see in the first 3 seconds","line":"the first spoken line: words someone says","onscreen_text":"max 6 words of big text on screen","alternates":["another spoken hook line","another spoken hook line"]},"scenes":[%s],"cliffhanger":{"type":"","speaker":"who says it","line":"the last spoken line, exactly as it appears as the final line of the last scene","visual":"the final frame"},"summary":"2 sentences: what happened and what the viewer is now desperate to know","runtime_sec":%d}""" % (
        n, p["episodes"], p["length"], words, s1, s2, cont, SCENE_SHAPE, p["length"])
    plan = inp.get("plan") if isinstance(inp.get("plan"), dict) else {}
    nxt = inp.get("next_plan") if isinstance(inp.get("next_plan"), dict) else None
    prev = inp.get("prev") if isinstance(inp.get("prev"), dict) else None
    sofar = [clip(s, 260) for s in as_list(inp.get("so_far"))][-14:]
    user = "SERIES BIBLE:\n" + j(bible_brief(inp.get("bible"))) + "\n\n" + setup_line(p)
    user += "\n\nPLAN FOR EPISODE %d:\n%s" % (n, j(plan))
    if nxt:
        user += "\n\nNEXT EPISODE (do not write it; just make sure this cliffhanger leads into it): %s. %s" % (
            clip(nxt.get("title"), 80), clip(nxt.get("hook"), 240))
    if sofar:
        user += "\n\nSTORY SO FAR:\n" + "\n".join("EP %d: %s" % (i + 1 + max(0, n - 1 - len(sofar)), s) for i, s in enumerate(sofar))
    if prev:
        user += "\n\nPREVIOUS EPISODE ENDED ON (%s): %s\nFinal frame: %s" % (
            clip(prev.get("type"), 30), clip(prev.get("line"), 300), clip(prev.get("visual"), 300))
    if inp.get("used_types"):
        user += "\n\nCliffhanger types used recently (do not repeat the last one): " + ", ".join(clip(t, 30) for t in as_list(inp.get("used_types"))[-4:])
    if inp.get("notes"):
        user += "\n\nNOTES FOR THIS EPISODE (must follow): " + clip(inp.get("notes"), 700)
    user += owner_rules(p, inp.get("director_notes"))
    return sysm, user, 3800, 0.9


def c_write(d, inp):
    n = to_int(inp.get("n"), 1, 30, 1)
    scenes = [s for s in (clean_scene(x, i + 1) for i, x in enumerate(as_list(d.get("scenes"))[:14])) if s]
    if len(scenes) < 2:
        raise ValueError("script too short")
    h = d.get("hook") if isinstance(d.get("hook"), dict) else {"line": d.get("hook")}
    first = scenes[0]["lines"][0]["line"] if scenes[0]["lines"] else ""
    hl = clip(h.get("line"), 300)
    hl = first if (not hl or is_direction(hl)) and first else (spoken(hl) or hl)
    hook = {"visual": clip(h.get("visual"), 400) or scenes[0]["visual"], "line": hl,
            "onscreen_text": clip(h.get("onscreen_text"), 80) or scenes[0]["onscreen_text"],
            "alternates": [spoken(a) for a in as_list(h.get("alternates"))[:3] if clip(a, 300) and not is_direction(a)]}
    cliff = clean_cliff(d.get("cliffhanger"), scenes[-1]["visual"])
    if not cliff["line"] or is_direction(cliff["line"]):
        cliff["line"] = ""
    cliff["line"] = end_on(scenes[-1], cliff) or cliff["line"]
    cliff["type"] = cliff["type"] or "shock reveal"
    plan = inp.get("plan") if isinstance(inp.get("plan"), dict) else {}
    return {"n": n, "title": clip(d.get("title"), 100) or clip(plan.get("title"), 100) or "Episode %d" % n,
            "hook": hook, "scenes": scenes, "cliffhanger": cliff, "summary": clip(d.get("summary"), 500),
            "runtime_sec": to_int(d.get("runtime_sec"), 10, 600, premise_of(inp)["length"])}


# --------------------------------------------------------------------------------------------
# PUNCH: Script Doctor scores it, Cliffhanger Bot sharpens the ending
# --------------------------------------------------------------------------------------------
SCORE_KEYS = ["hook", "tension", "twist", "cliffhanger", "dialogue", "binge"]


def b_punch(inp):
    p = premise_of(inp)
    t = to_int(inp.get("threshold"), 5, 10, 7)
    used = [clip(x, 30) for x in as_list(inp.get("used_types"))[-3:] if clip(x, 30)]
    avoid = (" and none of these recently used types: " + ", ".join(used)) if used else ""
    sysm = CRAFT + "\n\n" + lang_rule(p["language"]) + """

TASK: You are DOC, the harshest script doctor in the business, working with BITIN, the cliffhanger specialist.
Score this episode honestly from 1 to 10, where 7 = good enough to post and 9 = people will binge the whole season tonight. Most first drafts score 5 to 7. Do not be generous.
- hook: do the first 3 seconds stop the scroll?
- tension: does every scene turn?
- twist: is there a reversal we did not see coming?
- cliffhanger: is NOT watching the next episode unbearable?
- dialogue: short, sharp, quotable?
- binge: overall, would you tap the next episode?
Then:
1. Write 3 cliffhanger options of DIFFERENT types%s. Each cuts on the last frame at peak tension. Pick the most addictive one ("best" is its index 0, 1 or 2).
2. Rewrite the FINAL scene so it builds to and cuts exactly on the chosen cliffhanger. Its LAST line is the cliffhanger line, word for word: nothing comes after it. Keep its "n" and timing.
3. If hook scores below %d, rewrite the hook in new_hook (visual, line, onscreen_text). Otherwise new_hook is null.
4. If dialogue scores below %d, give up to 4 punched-up replacements in line_fixes ("old" must be copied exactly from the script). Otherwise [].
5. scores_after: your honest estimate after these fixes.
Answer ONLY with JSON in exactly this shape:
{"scores":{"hook":0,"tension":0,"twist":0,"cliffhanger":0,"dialogue":0,"binge":0},"verdict":"one blunt sentence","fixes":["short note"],"cliffhanger_options":[{"type":"","speaker":"who says it","line":"the spoken line","visual":"the final frame"}],"best":0,"final_scene":%s,"new_hook":null,"line_fixes":[{"old":"","new":""}],"scores_after":{"hook":0,"tension":0,"twist":0,"cliffhanger":0,"dialogue":0,"binge":0},"summary":"updated 2 sentences, ending on the new cliffhanger"}""" % (avoid, t, t, SCENE_SHAPE)
    ep = inp.get("episode") if isinstance(inp.get("episode"), dict) else {}
    script = {"title": ep.get("title"), "hook": ep.get("hook"), "scenes": ep.get("scenes"), "cliffhanger": ep.get("cliffhanger")}
    nxt = inp.get("next_plan") if isinstance(inp.get("next_plan"), dict) else None
    locked = inp.get("next_written") if isinstance(inp.get("next_written"), dict) else None
    if locked:
        follow = ("\n\nIMPORTANT: the next episode is ALREADY WRITTEN and opens like this: %s First line: \"%s\". "
                  "Your cliffhanger must lead exactly into that opening. All 3 options keep the same event; only sharpen it "
                  "and make the last line a spoken line." % (clip(locked.get("visual"), 300), clip(locked.get("line"), 200)))
    elif nxt:
        follow = "\n\nThe next episode is planned as: %s. %s" % (clip(nxt.get("title"), 80), clip(nxt.get("hook"), 240))
    else:
        follow = "\n\nThis is the LAST episode of the season: the cliffhanger is the season-2 hook."
    user = ("SERIES BIBLE:\n" + j(bible_brief(inp.get("bible"))) + "\n\n" + setup_line(p)
            + "\n\nEPISODE %d OF %d:\n%s" % (to_int(inp.get("n"), 1, 30, 1), p["episodes"], j(script))
            + follow + owner_rules(p, inp.get("director_notes")))
    return sysm, user, 3200, 0.7


def clean_scores(s):
    s = s if isinstance(s, dict) else {}
    return {k: to_int(s.get(k), 1, 10, 6) for k in SCORE_KEYS}


def c_punch(d, inp):
    ep = inp.get("episode") if isinstance(inp.get("episode"), dict) else {}
    nsc = len(as_list(ep.get("scenes"))) or 1
    opts = []
    for o in as_list(d.get("cliffhanger_options"))[:3]:
        if isinstance(o, dict) and clip(o.get("line"), 300):
            if is_direction(o.get("line")):  # an action, not a line: keep it as the visual
                o = dict(o, visual=clip(DIRECTION_RE.match(o["line"]).group(1), 400) or o.get("visual"), line="")
            opts.append(clean_cliff(o))
    best = to_int(d.get("best"), 0, max(0, len(opts) - 1), 0)
    fs = clean_scene(d.get("final_scene"), nsc) if isinstance(d.get("final_scene"), dict) else None
    if fs and not fs["lines"]:
        fs = None
    if opts and fs:
        opts[best]["line"] = end_on(fs, opts[best])  # the final scene cuts exactly on the chosen ending
    if opts and not opts[best]["line"]:
        alt = [i for i, x in enumerate(opts) if x["line"]]
        best = alt[0] if alt else best
    nh = d.get("new_hook") if isinstance(d.get("new_hook"), dict) and clip(d["new_hook"].get("line"), 300) else None
    if nh and is_direction(nh.get("line")):
        nh = None  # a sound or action is not a hook line: keep the original hook
    if nh:
        nh = {"visual": clip(nh.get("visual"), 400), "line": spoken(clip(nh.get("line"), 300)) or clip(nh.get("line"), 300), "onscreen_text": clip(nh.get("onscreen_text"), 80)}
    fixes = []
    for f in as_list(d.get("line_fixes"))[:4]:
        if isinstance(f, dict) and clip(f.get("old"), 400) and clip(f.get("new"), 400):
            fixes.append({"old": clip(f.get("old"), 400), "new": clip(f.get("new"), 400)})
    scores = clean_scores(d.get("scores"))
    after = clean_scores(d.get("scores_after")) if isinstance(d.get("scores_after"), dict) else dict(scores)
    for k in SCORE_KEYS:
        after[k] = max(after[k], scores[k])
    return {"scores": scores, "scores_after": after, "verdict": clip(d.get("verdict"), 300),
            "fixes": [clip(f, 200) for f in as_list(d.get("fixes"))[:6] if clip(f, 200)],
            "cliffhanger_options": opts, "best": best, "final_scene": fs, "new_hook": nh, "line_fixes": fixes,
            "summary": clip(d.get("summary"), 500)}


# --------------------------------------------------------------------------------------------
# PRODUCE: Shot Bot (AI video prompts) + Release Bot (captions)
# --------------------------------------------------------------------------------------------
def b_produce(inp):
    p = premise_of(inp)
    n = to_int(inp.get("n"), 1, 30, 1)
    shots = bool(inp.get("shots", True))
    last = n >= p["episodes"]
    part1 = ("""PART 1, STORYBOARD (you are LENS): for every scene write 1 to 3 shots. Each shot has:
- image_prompt: an English prompt for an AI image tool that makes the FIRST FRAME. Start with "Vertical 9:16, %s,". Fully restate the look of every visible character from the character sheet (never rely on names alone), then the action, the emotion on faces, the setting, lighting, camera angle and lens. No text or captions inside the image.
- video_prompt: an English prompt for image-to-video: the motion in this shot, the camera move, and the duration (3 to 6 seconds).
- line: the dialogue or VO spoken during this shot, or "".
""" % p["style"]) if shots else "PART 1, STORYBOARD: skipped. Return \"shots\": [].\n"
    sysm = CRAFT + "\n\n" + lang_rule(p["language"]) + """

TASK: You are LENS (storyboard artist for AI video) and HYPE (release marketer).
%s
PART 2, RELEASE PACKAGE for %s (you are HYPE):
- caption: stops the scroll. Lead with the tension of this episode (never spoil the cliffhanger), include "Part %d", and end with a question or a reason to follow. %s
- hashtags: 5 to 8, a mix of niche drama tags and broad tags, each starting with #.
- title: a YouTube-Shorts-style title, max 70 characters, with a curiosity gap.
- thumbnail: "text" is at most 5 shocking words; "prompt" is an English AI image prompt for the thumbnail (vertical, close-up face with an intense emotion, no text in the image).
- pinned_comment: a comment that baits replies (a question that makes people take sides).
- next_teaser: one line teasing %s without spoiling it.
Answer ONLY with JSON in exactly this shape:
{"shots":[{"scene":1,"shot":1,"type":"close-up","image_prompt":"","video_prompt":"","line":""}],"release":{"caption":"","hashtags":["#"],"title":"","thumbnail":{"text":"","prompt":""},"pinned_comment":"","next_teaser":""}}""" % (
        part1, p["platform"], n, PLATFORM_RULES.get(p["platform"], ""), "season 2" if last else "the next episode")
    ep = inp.get("episode") if isinstance(inp.get("episode"), dict) else {}
    script = {"title": ep.get("title"), "scenes": ep.get("scenes"), "cliffhanger": ep.get("cliffhanger")}
    b = bible_brief(inp.get("bible"), looks=True)
    user = ("CHARACTER SHEET (reuse these looks word for word in prompts):\n" + j(b.get("characters", []))
            + "\n\nSERIES: %s. %s\n%s" % (b.get("title", ""), b.get("logline", ""), setup_line(p))
            + "\n\nEPISODE %d OF %d:\n%s" % (n, p["episodes"], j(script))
            + owner_rules(p, inp.get("director_notes")))
    return sysm, user, 4200 if shots else 1600, 0.8


def c_produce(d, inp):
    shots = []
    for i, s in enumerate(as_list(d.get("shots"))[:40]):
        if isinstance(s, dict) and clip(s.get("image_prompt"), 1200):
            shots.append({"scene": to_int(s.get("scene"), 1, 30, 1), "shot": to_int(s.get("shot"), 1, 9, 1),
                          "type": clip(s.get("type"), 40), "image_prompt": clip(s.get("image_prompt"), 1200),
                          "video_prompt": clip(s.get("video_prompt"), 700), "line": clip(s.get("line"), 300)})
    r = d.get("release") if isinstance(d.get("release"), dict) else d
    th = r.get("thumbnail") if isinstance(r.get("thumbnail"), dict) else {"text": r.get("thumbnail")}
    tags = []
    for t in as_list(r.get("hashtags"))[:10]:
        t = clip(t, 40).replace(" ", "")
        if t:
            tags.append(t if t.startswith("#") else "#" + t)
    rel = {"caption": clip(r.get("caption"), 1500), "hashtags": tags, "title": clip(r.get("title"), 100),
           "thumbnail": {"text": clip(th.get("text"), 60), "prompt": clip(th.get("prompt"), 900)},
           "pinned_comment": clip(r.get("pinned_comment"), 300), "next_teaser": clip(r.get("next_teaser"), 300)}
    if not rel["caption"]:
        raise ValueError("no caption")
    return {"shots": shots, "release": rel}


TASKS = {
    "pitch": (b_pitch, c_pitch),
    "bible": (b_bible, c_bible),
    "map": (b_map, c_map),
    "write": (b_write, c_write),
    "punch": (b_punch, c_punch),
    "produce": (b_produce, c_produce),
}


# --------------------------------------------------------------------------------------------
# MOCK MODE (DRAMA_MOCK=1): fake answers so the whole pipeline can be tested without a key
# --------------------------------------------------------------------------------------------
def mock(task, inp):
    p = premise_of(inp)
    rnd = random.Random(json.dumps(inp, sort_keys=True)[:400])
    names = ["Lia", "Rafael", "Mika", "Celia"]
    if task == "pitch":
        return {"pitches": [{"title": "Mock Pitch %d" % i, "logline": "A test logline with a secret.", "opening_hook": "A slap at a wedding.",
                             "secret": "The groom is her brother.", "why_bingeable": "Every episode ends on a bomb.", "genres": ["Revenge"]} for i in range(1, 6)]}
    if task == "bible":
        return {"title": "Mock Season", "alt_titles": ["Alt One", "Alt Two"], "logline": "A widow gets a text from her dead husband.",
                "tagline": "Some messages should never be delivered.", "central_secret": "He is alive and hiding from his brother.",
                "theme": "Trust", "world": "A rich family in Manila.",
                "characters": [{"name": n, "role": r, "gender": g, "age": "30", "look": "test look for " + n, "want": "the truth",
                                "wound": "loss", "secret": "a secret", "voice": "short"} for n, r, g in
                               zip(names, ["hero", "villain", "ally", "wildcard"], ["female", "male", "female", "female"])],
                "season_arc": {"setup": "s", "first_reveal": "r", "midpoint_twist": "m", "dark_moment": "d", "finale_twist": "f", "season2_hook": "h"}}
    if task == "map":
        a, b = to_int(inp.get("from"), 1, 30, 1), to_int(inp.get("to"), 1, 30, 1)
        return {"episodes": [{"n": n, "title": "Mock Episode %d" % n, "hook": "Hook %d" % n, "beats": ["a", "b", "c"], "twist": "twist",
                              "cliffhanger": "Cliff %d" % n, "cliffhanger_type": CLIFF_TYPES[n % len(CLIFF_TYPES)], "opens": ["Who?"], "closes": []}
                             for n in range(a, b + 1)]}
    if task == "write":
        n = to_int(inp.get("n"), 1, 30, 1)
        sc = []
        for i in range(1, 6):
            sc.append({"n": i, "time": "0:%02d-0:%02d" % ((i - 1) * 12, i * 12), "location": "INT. MANSION - NIGHT",
                       "visual": "Close-up on a trembling hand, scene %d." % i,
                       "lines": [{"speaker": rnd.choice(names), "line": "Line %d of scene %d. You lied to me!" % (k, i), "emotion": rnd.choice(["angry", "shocked", "cold", "whisper"])} for k in (1, 2)],
                       "onscreen_text": "SHE KNOWS" if i == 1 else "", "sfx": "low drone"})
        return {"title": "Mock Episode %d" % n, "hook": {"visual": "A slap.", "line": "You were never my husband.", "onscreen_text": "HE'S ALIVE?", "alternates": ["Alt hook A", "Alt hook B"]},
                "scenes": sc, "cliffhanger": {"type": "the phone call", "line": "The phone rings. It's him.", "visual": "Phone screen glowing."},
                "summary": "Mock summary for episode %d." % n, "runtime_sec": p["length"]}
    if task == "punch":
        ep = inp.get("episode") or {}
        last = (ep.get("scenes") or [{}])[-1]
        fs = dict(last)
        fs["lines"] = (last.get("lines") or [])[:1] + [{"speaker": "Lia", "line": "Then who is in the coffin?", "emotion": "shocked"}]
        return {"scores": {k: rnd.randint(5, 8) for k in SCORE_KEYS}, "verdict": "Solid, but the hook is late.", "fixes": ["Start on the slap."],
                "cliffhanger_options": [{"type": "identity reveal", "line": "Then who is in the coffin?", "visual": "Lid opening."},
                                        {"type": "danger", "line": "Lock the doors.", "visual": "Shadow."},
                                        {"type": "arrival", "line": "He's here.", "visual": "Headlights."}],
                "best": 0, "final_scene": fs, "new_hook": {"visual": "Slap in slow motion.", "line": "Sino ka?!", "onscreen_text": "WHO ARE YOU?"},
                "line_fixes": [], "scores_after": {k: rnd.randint(8, 9) for k in SCORE_KEYS}, "summary": "Mock punched summary."}
    if task == "produce":
        ep = inp.get("episode") or {}
        shots = [{"scene": s.get("n", 1), "shot": 1, "type": "close-up", "image_prompt": "Vertical 9:16, %s, test frame %s" % (p["style"], s.get("n")),
                  "video_prompt": "Slow push-in, 4s", "line": ""} for s in (ep.get("scenes") or [])] if inp.get("shots", True) else []
        return {"shots": shots, "release": {"caption": "She buried him. He texted her. Part %d" % to_int(inp.get("n"), 1, 30, 1),
                                            "hashtags": ["#aidrama", "#minidrama", "#fyp"], "title": "Her dead husband just texted her",
                                            "thumbnail": {"text": "HE'S ALIVE?!", "prompt": "close-up shocked face"},
                                            "pinned_comment": "Would you open the casket?", "next_teaser": "Next: the casket opens."}}
    return {}
