# callnote

Hands-free call notes on Linux. Records calls made in WhatsApp Web (or any browser),
transcribes them locally with Whisper and turns each one into structured notes with Claude.
What the notes look like is set by switchable prompt templates: meeting minutes,
study sessions, a brain dump of ideas, or your own.

## How it works

1. Polls PipeWire: when the browser starts capturing the microphone, a call has started.
2. Records two tracks with ffmpeg: your mic (`me.wav`) and speaker output (`them.wav`).
   Separate tracks give speaker labels for free.
3. When the browser releases the mic for 5+ seconds, recording stops.
4. faster-whisper transcribes both tracks; lines are merged by timestamp.
5. Claude writes the notes using the current template: through the Claude Code CLI
   on your Claude subscription (default), through the Claude API, or with local Ollama.

## Templates

A template is a Markdown file in `~/.config/callnote/templates/` describing the sections
of the notes. Language, title line, accuracy rules and the transcript are appended automatically.

| Template  | For |
|-----------|-----|
| `meeting` | Calls with decisions and action items (default) |
| `study`   | Reading a book with a mentor: pages, marked passages, assignments, a plan to rerun the session |
| `ideas`   | Thinking out loud alone: ideas grouped by topic, decisions, open questions |

```sh
callnote.py use              # list templates, * marks the current one
callnote.py use ideas        # switch; applies to the next call, no service restart needed
callnote.py process ~/calls/<dir> study   # rewrite notes for a recording with another template
```

To add a template, drop a new `.md` file into the folder.

To record without a call (e.g. dictating ideas), open any page that uses the microphone,
such as an online mic test, or run `callnote.py record ideas`.

## Output

```
~/calls/
├── index.md              # table of contents: one line per recording, in order
└── 2026-10-25_13-30/
    ├── summary.md        # the notes
    ├── transcript.txt    # full transcript with timestamps
    ├── me.wav
    └── them.wav
```

The model only hears the call. Say out loud what it cannot see: "page 58", "mark this: ...".

## Install (Arch Linux)

```sh
sudo pacman -S ffmpeg libpulse libnotify python
curl -fsSL https://claude.ai/install.sh | bash   # Claude Code CLI
claude                                           # log in once with your Claude account, then /exit
python -m venv ~/.local/share/callnote/venv
~/.local/share/callnote/venv/bin/pip install faster-whisper
install -Dm755 callnote.py ~/.local/bin/callnote.py
install -Dm644 -t ~/.config/callnote/templates templates/*.md   # overwrites edited copies
install -Dm644 callnote.service ~/.config/systemd/user/callnote.service
systemctl --user daemon-reload
systemctl --user enable --now callnote
```

NVIDIA GPU (much faster transcription): `sudo pacman -S cuda cudnn`.

## Config

Optional `~/.config/callnote.env`:

```sh
CALLNOTE_LLM=claude-code          # claude-code (subscription) | api | ollama
CLAUDE_MODEL=claude-sonnet-5-5    # used by claude-code and api
ANTHROPIC_API_KEY=sk-ant-...      # only for CALLNOTE_LLM=api; claude-code ignores it
OLLAMA_MODEL=qwen2.5:14b
WHISPER_MODEL=large-v3-turbo      # small/medium on weak CPUs
WHISPER_LANG=ru                   # omit for auto-detect
WHISPER_HOTWORDS=...              # names and terms to recognize, comma-separated
SUMMARY_LANG=Russian
CALLNOTE_DIR=~/calls              # e.g. a folder inside your Obsidian vault
CALLNOTE_TEMPLATES=~/.config/callnote/templates
CALLNOTE_ME=Me                    # speaker labels in transcripts
CALLNOTE_THEM=Them
```

## Notes

- With `claude-code`, notes count toward the subscription usage limits shared with claude.ai.
  If a run fails (limit reached, logged out), you get a desktop notification; reprocess later.
- Use headphones: with speakers the mic also picks up the other side and it gets transcribed twice.
  PipeWire's echo-cancel module removes what remains.
- `@DEFAULT_MONITOR@` captures all system audio, so mute other sound sources during a call.
- Any browser mic capture is recorded; captures under 30 s are discarded.
- `process` reuses an existing `transcript.txt`, so rerunning it after a failed LLM step
  or with another template is quick. Delete the file to transcribe again.
- Logs, including transcription progress: `journalctl --user -u callnote -f`.
