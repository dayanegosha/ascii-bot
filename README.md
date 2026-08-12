# ascii-bot

> **Project moved:** the Telegram renderer and its browser edition now live
> together in [ASCII Video Studio](https://github.com/dayanegosha/ascii-video-studio).
> This repository is preserved as a read-only historical snapshot.

Telegram bot that turns a video into **ASCII-art video**. Send a clip, pick a few
options, and the bot renders every frame as colored or monochrome ASCII and sends
the result back as an `.mp4`.

> Looking for the in-browser version? See the companion **[ascii-app](https://github.com/dayanegosha/ascii-app)** (VK Mini App).

## Features

- Frame-by-frame ASCII rendering with a tunable character ramp (` .:+-*#%`)
- **Colored** or **monochrome** output
- Three detail sizes (small / medium / large) and two quality tiers
  (`обычное` up to 1080p, `ультра` up to 4K)
- Multi-core rendering via `ProcessPoolExecutor` — uses all CPU cores
- Live progress with ETA, and a `/stop` command to cancel a running job
- Hard limit of 3 minutes per video to keep memory and time in check

## Requirements

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/) on `PATH` (used by MoviePy to write the video)
- A monospaced TTF font (the bot auto-detects common macOS/Linux fonts and
  falls back to PIL's default if none is found)

## Setup

```bash
git clone https://github.com/dayanegosha/ascii-bot.git
cd ascii-bot

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

The bot token is read from the `BOT_TOKEN` environment variable — nothing is
hardcoded. Get a token from [@BotFather](https://t.me/BotFather) and run:

```bash
export BOT_TOKEN="123456:your-token-here"   # Windows: set BOT_TOKEN=...
python bot.py
```

## Usage

1. Open a chat with the bot and send `/start`.
2. Choose **size** → **mode** (color/mono) → **quality**.
3. Send a video (up to 3 minutes) as a video or a file.
4. Wait for the progress bar; the bot replies with your ASCII `.mp4`.
5. Send `/stop` at any time to cancel the current render.

## How it works

Each frame is downscaled to a character grid, every pixel is mapped to an ASCII
glyph by brightness, and the glyphs are drawn back onto a blank canvas with PIL.
Frames are processed in parallel and stitched into a video with MoviePy.

## License

[MIT](LICENSE) © George Zhurik
