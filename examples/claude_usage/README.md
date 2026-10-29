# Example: Claude usage on a Divoom screen

A small background app with no window. It keeps one Divoom screen connected and shows your Claude Code usage limits.

![Clawd with the usage bars](clawd-usage.gif)

- **Top bar: the 5-hour limit.** It fills from the left with the percentage used. The 4 dots under it mark the hours.
- **Bottom bar: the weekly limit.** The 6 dots under it mark the days.
- **Faint grey pixel on each bar:** how much of that window's time has passed. Orange past it means you're using the limit faster than time passes.
- **Clawd shows how fresh the numbers are:**
  - Awake, bobbing, glancing and waving: the numbers are current.
  - Waving non-stop with every star lit, for 2 seconds: new numbers just arrived.
  - Asleep (eyes shut, still, a little "z" floating up): nothing new for 10 minutes.
  - Squinting: more than 85% of the 5-hour limit is used. A bar also turns red and pulses above 85%.

Clawd is the Claude Code mascot by Anthropic. This is a fan-made example, not affiliated with Anthropic or Divoom.

## How the numbers get here

Claude Code passes `rate_limits` (the 5-hour and weekly `used_percentage` and `resets_at`) to its [status line command](https://code.claude.com/docs/en/statusline). It does this for Pro and Max subscribers, after the first response in a session. `statusline_hook.py` saves those values to `~/.claude/divoom-usage.json`, and `run.py` shows them on the screen.

## Setup

1. Install the main project (see the [main README](../../README.md)), and find your screen's address with `divoom-ble --scan`.

2. Make `statusline_hook.py` your Claude Code status line, in `~/.claude/settings.json`:

   ```json
   "statusLine": {
     "type": "command",
     "command": "python C:/path/to/divoom-ble-web/examples/claude_usage/statusline_hook.py"
   }
   ```

   It prints a short status line, e.g. `Opus | 5h 24% | 7d 41%`. If you already have your own status line, keep it and pipe the same input into this script as well.

3. Run the app:

   ```sh
   python examples/claude_usage/run.py --device 11:22:33:44:55:66
   ```

   Run it from the repository folder with the project's virtual environment active. A second copy refuses to start.

### Run it in the background on Windows

Use `pythonw.exe`, which opens no window, and log to a file:

```sh
.venv\Scripts\pythonw.exe examples\claude_usage\run.py --device 11:22:33:44:55:66 --log usage.log
```

To start it at login, put a shortcut with that command in `shell:startup`, with "Start in" set to the repository folder.

## Options

| Option | Meaning |
|---|---|
| `--device MAC` | The screen's Bluetooth address (required). |
| `--usage-file PATH` | Where to read the numbers (default `~/.claude/divoom-usage.json`). |
| `--refresh-cmd "COMMAND"` | Optional. A command that refreshes the usage file, run when the file is older than `--refresh-after` seconds (default 150). It lets the screen keep updating while Claude Code is closed, if you have a tool that can fetch the numbers. |
| `--brightness 0-100` | Sets the brightness every time the screen connects. |
| `--log FILE` | Also log to a file, kept under 512 KB. |

## Notes

- **Claude Code closed:** the status line only runs while Claude Code is open. Without `--refresh-cmd`, the numbers stop changing when it closes, and Clawd falls asleep after 10 minutes. The grey time markers keep moving, because they come from the clock.
- **Failed refresh:** if a refresh writes empty numbers, the app keeps the last good ones.
- **Buttons:** pressing a button on the screen gives it back its own mode for 60 seconds, then Clawd returns.
- **Why it doesn't flicker:** the screen is redrawn as whole still images, about 3 per second in 4 colours. It doesn't use the device's pixel-by-pixel drawing mode, which flickers (see [docs/protocol.md](../../docs/protocol.md)).
