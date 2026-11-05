#!/usr/bin/env python3
"""callnote: auto-record calls, transcribe with Whisper, write notes with an LLM.

Usage:
  callnote.py watch                   # wait for calls, record and write notes automatically
  callnote.py record [TEMPLATE]       # record until Ctrl+C, then write notes
  callnote.py process DIR [TEMPLATE]  # (re)write notes; reuses DIR/transcript.txt if present
  callnote.py use [TEMPLATE]          # list templates / switch the current one
"""
import json, os, re, shutil, signal, subprocess, sys, time, urllib.request, wave
from datetime import datetime
from pathlib import Path

OUT_DIR = Path(os.getenv("CALLNOTE_DIR", "~/calls")).expanduser()
APPS = re.compile(os.getenv("CALLNOTE_APPS", "chrom|firefox|brave"), re.I)
TEMPLATES = Path(os.getenv("CALLNOTE_TEMPLATES", "~/.config/callnote/templates")).expanduser()
CURRENT = TEMPLATES.parent / "current"  # name of the active template
ME, THEM = os.getenv("CALLNOTE_ME", "Me"), os.getenv("CALLNOTE_THEM", "Them")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3-turbo")
WHISPER_LANG = os.getenv("WHISPER_LANG") or None  # None = auto-detect
WHISPER_HOTWORDS = os.getenv("WHISPER_HOTWORDS") or None  # names and terms to recognize
SUMMARY_LANG = os.getenv("SUMMARY_LANG", "Russian")
LLM = os.getenv("CALLNOTE_LLM", "claude-code")  # claude-code (subscription) | api | ollama
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")  # for claude-code and api
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
MIN_SECONDS = 30  # shorter captures (e.g. voice messages) are discarded
GRACE = 5         # seconds the mic may be released before the call counts as over

# Appended to every template, so templates only describe the structure of the notes
RULES = """Write in {lang}, in Markdown, starting with a "# " title line.
Use only what is in the transcript; write "?" instead of guessing.
Fix obvious speech-recognition errors from context. Skip small talk.

Transcript, one line per phrase: [mm:ss] speaker: text.
"{me}" is the person keeping these notes, "{them}" is the other side of the call.

{transcript}"""


def notify(msg):
    print(msg, flush=True)
    try:
        subprocess.run(["notify-send", "callnote", msg], check=False)
    except FileNotFoundError:
        pass


def call_active():
    """True if a browser is currently capturing the microphone."""
    out = subprocess.run(["pactl", "-f", "json", "list", "source-outputs"],
                         capture_output=True, text=True).stdout
    return any(APPS.search(s["properties"].get("application.name", ""))
               for s in json.loads(out or "[]"))


def record(stop):
    """Record mic and speaker output as separate tracks until stop() or Ctrl+C."""
    d = OUT_DIR / datetime.now().strftime("%Y-%m-%d_%H-%M")
    d.mkdir(parents=True, exist_ok=True)
    track = ["-ac", "1", "-ar", "16000"]
    ff = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-f", "pulse", "-i", "default", "-f", "pulse", "-i", "@DEFAULT_MONITOR@",
         "-map", "0:a", *track, str(d / "me.wav"),
         "-map", "1:a", *track, str(d / "them.wav")],
        stdin=subprocess.DEVNULL, start_new_session=True)
    start = time.time()
    try:
        while not stop():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    ff.send_signal(signal.SIGINT)  # lets ffmpeg finalize the WAV headers
    ff.wait()
    return d, time.time() - start


def load_wav(path):
    """Read our 16 kHz mono s16 WAV as float32.

    Bypasses faster-whisper's PyAV decoder, which breaks on newer PyAV releases."""
    import numpy as np
    with wave.open(str(path)) as w:
        pcm = w.readframes(w.getnframes())
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768


def transcribe(d):
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, device="auto", compute_type="auto")
    lines = []
    for file, who in (("me.wav", ME), ("them.wav", THEM)):
        segs, info = model.transcribe(load_wav(d / file), language=WHISPER_LANG,
                                      hotwords=WHISPER_HOTWORDS, vad_filter=True,
                                      condition_on_previous_text=False)
        step = 10  # next progress mark, %
        for s in segs:  # segments are decoded lazily, so this loop is the slow part
            lines.append((s.start, who, s.text.strip()))
            if (pct := s.end / max(info.duration, 1) * 100) >= step:
                print(f"{d.name}/{file}: {pct:.0f}%", flush=True)
                step = pct // 10 * 10 + 10
        print(f"{d.name}/{file}: done", flush=True)
    return "\n".join(f"[{int(t) // 60:02}:{int(t) % 60:02}] {who}: {text}"
                     for t, who, text in sorted(lines))


def post(url, body, headers=None):
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"content-type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def llm(prompt):
    if LLM == "claude-code":
        # Claude Code CLI bills the Claude subscription, but prefers an API key when one is set
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        r = subprocess.run(
            ["claude", "-p", "--model", CLAUDE_MODEL, "--tools", "", "--strict-mcp-config",
             "--no-session-persistence",
             "--system-prompt", "You write structured notes from transcripts."],
            input=prompt, capture_output=True, text=True, env=env)
        if r.returncode:
            raise RuntimeError(f"claude: {(r.stdout or r.stderr).strip()}")
        return r.stdout
    if LLM == "api":
        r = post("https://api.anthropic.com/v1/messages",
                 {"model": CLAUDE_MODEL, "max_tokens": 8000,
                  "messages": [{"role": "user", "content": prompt}]},
                 {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                  "anthropic-version": "2023-06-01"})
        return r["content"][0]["text"]
    r = post(f"{OLLAMA_URL}/api/generate",
             {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
              "options": {"num_ctx": 32768}})  # default context is too short for long calls
    return r["response"]


def template_path(name):
    path = TEMPLATES / f"{name}.md"
    if not path.exists():
        sys.exit(f"No template '{name}' in {TEMPLATES}")
    return path


def current_template():
    return CURRENT.read_text().strip() if CURRENT.exists() else "meeting"


def use(name=None):
    """Switch the template used for upcoming calls; list templates, marking the current one."""
    if name:
        template_path(name)
        CURRENT.write_text(name + "\n")
    for t in sorted(p.stem for p in TEMPLATES.glob("*.md")):
        print("*" if t == current_template() else " ", t)


def process(d, template=None):
    d, template = Path(d), template or current_template()
    instructions = template_path(template).read_text().strip()  # fail before transcribing
    cached = d / "transcript.txt"
    if cached.exists():  # transcription is the slow part; delete the file to redo it
        transcript = cached.read_text().strip()
    else:
        notify(f"Transcribing {d.name}...")
        transcript = transcribe(d)
        if not transcript:
            return notify(f"No speech found in {d.name}")
        cached.write_text(transcript + "\n")
    print(f"{d.name}: writing notes ({template})", flush=True)
    rules = RULES.format(lang=SUMMARY_LANG, me=ME, them=THEM, transcript=transcript)
    summary = llm(f"{instructions}\n\n{rules}").strip()
    note = d / "summary.md"
    note.write_text(f"{summary}\n\n---\n{d.name} · {template} · [transcript](transcript.txt)\n")
    add_to_index(d, summary)
    notify(f"Notes ready: {note}")


def add_to_index(d, summary):
    """Append the recording to index.md, a table of contents of all notes in call order."""
    index = d.parent / "index.md"
    if d.name in (index.read_text() if index.exists() else ""):
        return  # reprocessed session, already listed
    title = next((l[2:] for l in summary.splitlines() if l.startswith("# ")), "")
    with index.open("a") as f:
        f.write(f"- [{d.name}]({d.name}/summary.md) {title}\n")


def finish(d, duration):
    if duration < MIN_SECONDS:
        shutil.rmtree(d)
    else:  # process in background so the watcher can catch the next call
        subprocess.Popen([sys.executable, __file__, "process", str(d)])


def watch():
    notify("Waiting for calls")
    while True:
        if not call_active():
            time.sleep(2)
            continue
        notify("Call detected, recording")
        last_seen = time.time()

        def ended():
            nonlocal last_seen
            if call_active():
                last_seen = time.time()
            return time.time() - last_seen > GRACE

        finish(*record(ended))


if __name__ == "__main__":
    cmd, args = (sys.argv[1:] or ["watch"])[0], sys.argv[2:]
    if cmd == "watch":
        watch()
    elif cmd == "use" and len(args) <= 1:
        use(*args)
    elif cmd == "record" and len(args) <= 1:
        if args:
            template_path(args[0])  # check before recording, not after
        print("Recording, press Ctrl+C to stop")
        d, _ = record(lambda: False)
        process(d, *args)
    elif cmd == "process" and 1 <= len(args) <= 2:
        try:
            process(*args)
        except (Exception, SystemExit) as e:  # runs unattended: show the failure on the desktop
            notify(f"Failed on {Path(args[0]).name}: {e}")
            raise
    else:
        sys.exit(__doc__)
