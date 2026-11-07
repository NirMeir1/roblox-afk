# Roblox treadmill AFK experiment

Windows proof of concept. After a 5-second startup delay, immediately attempts
Space for 0.15 seconds, releases it, waits 1.85 seconds, then holds A for 0.10
seconds and releases it. A is pressed about 2 seconds after Space is pressed.
Keyboard events use standard Windows `SendInput`
scan codes (Space 0x39, A 0x1E), through Python's built-in `ctypes`.
PyAutoGUI provides the mouse-corner failsafe; it does not send keyboard input.
The script waits 5 minutes (300 seconds) after each completed, skipped, or
cancelled attempt before trying again (about 5 minutes 2.1 seconds between
the starts of completed sequences).

The GUI exposes the repeat interval and pause after releasing Space, both in
seconds. Defaults and all other timings are constants in `roblox_afk.py`.
Use `--gui` for the Tkinter window, or omit it for the original console mode.

For the standalone Windows application, double-click `dist\RobloxAFK.exe`.
It opens the same GUI without Python, installation, command-line arguments,
or a console. See [BUILD.md](BUILD.md) for reproducible build instructions,
packaged-application checks, and verification limitations.

| Constant | Default | Purpose |
| --- | --- | --- |
| `STARTUP_SECONDS` | `5` | Delay before the first attempt |
| `SPACE_SECONDS` | `0.15` | Space hold duration |
| `AFTER_SPACE_SECONDS` | `1.85` | Pause between releasing Space and pressing A |
| `MOVE_SECONDS` | `0.10` | A hold duration |
| `INTERVAL_SECONDS` | `300` | Wait after each attempt (5 minutes) |

Space followed by A does not guarantee returning to the treadmill: camera orientation,
speed, collisions, and game controls affect movement. This tool has no position
tracking or automatic treadmill re-entry. AFK prevention is unverified.

Only the foreground executable `RobloxPlayerBeta.exe` is eligible (case-insensitive).
Windows that cannot be identified are skipped. The script does not activate the
game, click, inject code into the game process, or modify game files. Held mouse
buttons, Space, or WASD keys skip the attempt.
Foreground focus is checked before each key-down and during each hold (roughly
every 0.02 seconds), including the pause between Space and A. Focus loss cancels
the remaining movement. Key-up cleanup is attempted after focus loss, Ctrl+C,
or a corner failsafe, to avoid stuck keys.
PyAutoGUI's mouse-corner failsafe stays enabled. Native key release bypasses that
failsafe so cleanup can still be attempted after a corner stop. Windows can
reject a release event, so successful cleanup is not guaranteed.
There is a small unavoidable race between checking focus and sending a key.

## Setup and run in PowerShell

Requires Windows and Python. The setup below uses Python 3.13 installed at its
usual per-user location. Adjust the interpreter path if your installation differs.
The only direct dependency is `PyAutoGUI==0.9.54` in `requirements.txt`;
the Windows keyboard backend and Tkinter GUI use the Python standard library.
Your Python installation must include Tcl/Tk (included in the standard Windows installer).

Create the virtual environment and install dependencies once:

```powershell
cd C:\Users\meirn\roblox-afk
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Launch the GUI:

```powershell
cd C:\Users\meirn\roblox-afk
.\.venv\Scripts\python.exe .\roblox_afk.py --gui
```

The window has large Start/Stop buttons and a status card: green **Running**
while active, or gray **Stopped** when idle. It also shows the current interval
and Space-to-A delay. The styling uses Tk's bundled theme and needs no assets
or additional packages.

Before Start, you can edit **Repeat interval (seconds)** (default `300`, must
be greater than zero) and **Pause after Space (seconds)** (default `1.85`, can
be zero). Decimals are accepted; invalid or non-finite values prevent starting
and show an inline error. The pause begins after Space is released, so the
total time from pressing Space to pressing A is `0.15 + pause` seconds.
Fields are disabled while running; Stop first to change them, then Start to
apply. Values remain for the current window session and reset to defaults
when you reopen the app. Console mode continues to use the code defaults.

Click **Start**, then bring Roblox to the foreground within 5 seconds. Status
shows **Running** during startup and automation. **Stop** signals cancellation
immediately, including during waits. Any held key is released through the
existing cleanup path; status changes to **Stopped** once the worker exits.
Start stays disabled until cleanup finishes. Closing the window also cancels
the worker and waits for it to finish before destroying the window.

The GUI uses one non-daemon worker thread and `threading.Event`; only the main
thread accesses Tk widgets. It does not spawn automation subprocesses. A Windows
named mutex prevents additional GUI or console launches in the same login
session and is released on exit. Opening a second instance displays an error.
No new dependencies are needed.

For the original console mode, start the script and bring Roblox to the
foreground during the startup delay:

```powershell
cd C:\Users\meirn\roblox-afk
.\.venv\Scripts\python.exe .\roblox_afk.py
```

Stop: switch to the console and press Ctrl+C, or move the mouse to any corner
of the primary screen. Keep the pointer away from corners when starting.
Timestamped console logs report each key hold and skipped/cancelled attempts.
The same logs are appended to `%LOCALAPPDATA%\RobloxAFK\roblox_afk.log`. Session PID,
foreground skip reasons, and key-down/key-up events are recorded. Each native
event checks the Windows return value; rejected events stop the tool with an
error. Normal Ctrl+C and corner-failsafe stops return exit code `0`; handled
errors return `1`. A successful event means Windows queued it, not that Roblox
acted on it.
To monitor from PowerShell:

```powershell
Get-Content "$env:LOCALAPPDATA\RobloxAFK\roblox_afk.log" -Tail 20 -Wait
```

## Test inside Roblox

1. Manually enter the treadmill, close chat/menus, and confirm training increases.
   Use normal Space/A controls and a fixed camera. Record the starting training value.
2. Start the script and leave Roblox active. Watch the FIRST movement at about
   5 seconds. Confirm Space then A produces the desired movement and training resumes.
   Stop if the character leaves the treadmill; reposition manually. Adjust
   MOVE_SECONDS conservatively only after observing the result.
3. After the first movement succeeds, observe a full 25-30-minute session with
   Roblox active and the computer awake/unlocked. Record final training value,
   any disconnect time, and whether every movement returned to training.
4. Stop with Ctrl+C. Sent-key logs do not prove Roblox accepted the input or that
   the treadmill was re-entered. Compare with a separate session without the tool.

## Local tests

After setup, check dependencies and run the tests:

```powershell
cd C:\Users\meirn\roblox-afk
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest -v
```

All movement tests mock key input. `check_input.py` runs these same tests and
does not send live input:

```powershell
.\.venv\Scripts\python.exe .\check_input.py
```

The tests cover input ordering and timing, held-control skips, focus loss,
interruption cleanup, startup behavior, and mouse-corner detection. Real Tk
widgets and worker threads test ten Start/Stop cycles, duplicate Start clicks,
GUI responsiveness, worker exit, and closing while running, including held-key
cleanup with mocked keyboard input. Cancellation tests cover startup, both key
holds, the pause, and the repeat wait. Native mutex tests check duplicate
process rejection and release after exit or an exception. The tests also
check the native event layout, scan codes, press/release flags, and
rejected-event handling with mocked Windows calls. Run them on Windows with
the dependencies installed. They do not verify in-game movement, treadmill
re-entry, or AFK prevention; those require the manual checks above.

PyAutoGUI reference: https://pyautogui.readthedocs.io/en/latest/keyboard.html

Windows reference: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
