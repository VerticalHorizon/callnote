# callnote

Automatically records WhatsApp Web (or any browser) calls on Linux, transcribes them
with Whisper and writes a summary with an LLM.

## How it works

1. Polls PipeWire: when the browser starts capturing the microphone, a call has started.
2. Records two tracks with ffmpeg: your mic (`me.wav`) and speaker output (`them.wav`).
   Separate tracks give speaker labels for free.
3. When the browser releases the mic for 5+ seconds, recording stops.
4. faster-whisper transcribes both tracks; lines are merged by timestamp.
5. Claude API (if `ANTHROPIC_API_KEY` is set) or local Ollama writes the session notes.

## Output

```
~/calls/
├── index.md                 # table of contents: one line per session, in order
└── 2026-10-25_13-30/
    ├── summary.md           # session notes (shareable)
    ├── transcript.txt       # full transcript with timestamps (private)
    ├── me.wav
    └── them.wav
```

`summary.md` sections: overview (literature, pages, theme), session flow with timestamps,
underlined passages with page numbers, assignments, and a step-by-step plan for running
the same session with a sponsee (personal stories and identifying details left out).

Output: `~/calls/<date>_<time>/summary.md` (+ `transcript.txt`, wav files).

## Install (Arch Linux)

```sh
sudo pacman -S ffmpeg libpulse libnotify python
python -m venv ~/.local/share/callnote/venv
~/.local/share/callnote/venv/bin/pip install faster-whisper
install -Dm755 callnote.py ~/.local/bin/callnote.py
install -Dm644 callnote.service ~/.config/systemd/user/callnote.service
systemctl --user daemon-reload
systemctl --user enable --now callnote
```

NVIDIA GPU (much faster transcription): `sudo pacman -S cuda cudnn`.

## Config

Optional `~/.config/callnote.env`:

```sh
ANTHROPIC_API_KEY=sk-ant-...      # omit to use Ollama
OLLAMA_MODEL=qwen2.5:14b
WHISPER_MODEL=large-v3-turbo      # small/medium on weak CPUs
WHISPER_LANG=ru                   # omit for auto-detect
WHISPER_HOTWORDS=...              # book titles and terms, comma-separated
SUMMARY_LANG=Russian
CALLNOTE_DIR=~/calls              # e.g. a folder inside your Obsidian vault
CALLNOTE_ME=Me
CALLNOTE_THEM=Them
```

The note structure is defined by `PROMPT` in `callnote.py`; edit it to change sections.

## Notes

- Use headphones: with speakers the mic also picks up the other side and it gets transcribed twice.
- `@DEFAULT_MONITOR@` captures all system audio, so mute other sound sources during a call.
- Any browser mic capture (e.g. Google Meet) is recorded too; captures under 30 s are discarded.
- Manual mode: `callnote.py record` (Ctrl+C to stop). Reprocess: `callnote.py process ~/calls/<dir>`.
- Logs: `journalctl --user -u callnote -f`.
