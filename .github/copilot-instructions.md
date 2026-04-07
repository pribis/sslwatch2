# SSLWatch2 Copilot Instructions

## Running the App

```bash
~/.venv/bin/python sslwatch2.py
```

The project uses the shared virtual environment at `~/.venv`. Requires the `certifi` package (`~/.venv/bin/pip install certifi`). All other dependencies are standard library plus the system `whois` binary (pre-installed on macOS).

## Architecture

The app is split into two files with a clean separation of concerns:

- **`sslwatch2.py`** — Entry point and network logic. Defines `check_ssl_status` and `get_whois_info` as standalone functions, each designed to run in a background thread and deposit results into a `queue.Queue`.
- **`gui.py`** — The `GUI` class that owns the curses TUI. It receives checker functions as a dict (`{'ssl': ..., 'whois': ...}`) in its constructor, keeping it decoupled from network logic.

### Threading model

Each domain check spawns a `threading.Thread`. Results are deposited into `self.result_queue`; the main loop polls the queue each iteration (100ms timeout via `input_win.timeout(100)`). The `active_threads` counter tracks batch completion.

### Two input modes

`app_mode` toggles between `'DOMAIN_INPUT'` (single domain) and `'FILE_INPUT'` (path to a newline-delimited domain file). Ctrl-F switches modes.

### Result statuses

SSL check results use these status values: `OK`, `WARNING` (≤30 days), `ALERT` (≤10 days), `EXPIRED`, `ERROR`. WHOIS results use `WHOIS_SUCCESS` / `WHOIS_ERROR`. The output window and color map key off these strings.

### Display modes

`self.detailed_view` toggles between compact (1 line/result) and detailed (7 lines/result). Ctrl-D switches; `scroll_pos` resets on toggle.

### Popups

Both the WHOIS popup (`_display_whois_popup`) and help popup (`_display_help_popup`) run their own blocking `while True` input loops, bypassing the main loop until closed. The WHOIS popup continues polling `self.result_queue` while waiting for the whois thread to finish.

## Key Conventions

- `curses.noutrefresh()` is used on sub-windows; `curses.doupdate()` is called once per main loop iteration for flicker-free rendering.
- Mouse clicks on result rows trigger WHOIS lookup only for results with a non-error status.
- The `domains` file in the repo root is a sample domain list for testing file-input mode.
