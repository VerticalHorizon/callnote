# callnote

Automatically records WhatsApp Web (or any browser) calls on Linux, transcribes them
with Whisper and writes a summary with an LLM.

## How it works

1. Polls PipeWire: when the browser starts capturing the microphone, a call has started.
2. Records two tracks with ffmpeg: your mic (`me.wav`) and speaker output (`them.wav`).
   Separate tracks give speaker labels for free.
3. When the browser releases the mic for 5+ seconds, recording stops.
4. faster-whisper transcribes both tracks; lines are merged by timestamp.
5. The transcript is summarized by Claude API (if `ANTHROPIC_API_KEY` is set) or local Ollama.

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
SUMMARY_LANG=Russian
CALLNOTE_DIR=~/calls              # e.g. a folder inside your Obsidian vault
CALLNOTE_ME=Me
CALLNOTE_THEM=Them
```

## Notes

- Use headphones: with speakers the mic also picks up the other side and it gets transcribed twice.
- `@DEFAULT_MONITOR@` captures all system audio, so mute other sound sources during a call.
- Any browser mic capture (e.g. Google Meet) is recorded too; captures under 30 s are discarded.
- Manual mode: `callnote.py record` (Ctrl+C to stop). Reprocess: `callnote.py process ~/calls/<dir>`.
- Logs: `journalctl --user -u callnote -f`.
