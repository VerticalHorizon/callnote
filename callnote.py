#!/usr/bin/env python3
"""callnote: auto-record browser calls, transcribe with Whisper, write session notes with an LLM.

Usage:
  callnote.py watch          # wait for calls, record and summarize automatically
  callnote.py record         # record manually until Ctrl+C, then summarize
  callnote.py process DIR    # (re)run transcription and summary for a recording
"""
import json, os, re, shutil, signal, subprocess, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

OUT_DIR = Path(os.getenv("CALLNOTE_DIR", "~/calls")).expanduser()
APPS = re.compile(os.getenv("CALLNOTE_APPS", "chrom|firefox|brave"), re.I)
ME, THEM = os.getenv("CALLNOTE_ME", "Me"), os.getenv("CALLNOTE_THEM", "Them")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3-turbo")
WHISPER_LANG = os.getenv("WHISPER_LANG") or None  # None = auto-detect
WHISPER_HOTWORDS = os.getenv("WHISPER_HOTWORDS") or None  # book titles, program terms
SUMMARY_LANG = os.getenv("SUMMARY_LANG", "Russian")
LLM = os.getenv("CALLNOTE_LLM", "claude-code")  # claude-code (subscription) | api | ollama
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")  # for claude-code and api
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
MIN_SECONDS = 30  # shorter captures (e.g. voice messages) are discarded
GRACE = 5         # seconds the mic may be released before the call counts as over

PROMPT = """Below is a transcript of a video call. Write a concise summary in {lang}:
1. Main topics (1-2 sentences each).
2. Agreements and decisions.
3. Action items: who, what, by when.
4. Open questions.
Use only what is in the transcript. Fix obvious speech-recognition errors by context.

Rules: use only what is in the transcript; write "?" instead of guessing a page or a quote;
fix obvious speech-recognition errors from context; skip small talk.

Transcript:
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


def transcribe(d):
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, device="auto", compute_type="auto")
    lines = []
    for file, who in (("me.wav", ME), ("them.wav", THEM)):
        segs, _ = model.transcribe(str(d / file), language=WHISPER_LANG,
                                   hotwords=WHISPER_HOTWORDS, vad_filter=True,
                                   condition_on_previous_text=False)
        lines += [(s.start, who, s.text.strip()) for s in segs]
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
             "--system-prompt", "You write structured notes from call transcripts."],
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


def process(d):
    d = Path(d)
    notify(f"Transcribing {d.name}...")
    transcript = transcribe(d)
    if not transcript:
        return notify(f"No speech found in {d.name}")
    (d / "transcript.txt").write_text(transcript + "\n")
    summary = llm(PROMPT.format(lang=SUMMARY_LANG, transcript=transcript)).strip()
    note = d / "summary.md"
    note.write_text(f"{summary}\n\n---\n{d.name} · [transcript](transcript.txt)\n")
    add_to_index(d, summary)
    notify(f"Summary ready: {note}")


def add_to_index(d, summary):
    """Append the session to index.md: the table of contents, in call order."""
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
    cmd = sys.argv[1] if len(sys.argv) > 1 else "watch"
    if cmd == "watch":
        watch()
    elif cmd == "record":
        print("Recording, press Ctrl+C to stop")
        d, _ = record(lambda: False)
        process(d)
    elif cmd == "process" and len(sys.argv) > 2:
        try:
            process(sys.argv[2])
        except Exception as e:  # runs unattended: surface the failure on the desktop
            notify(f"Failed on {Path(sys.argv[2]).name}: {e}")
            raise
    else:
        sys.exit(__doc__)
