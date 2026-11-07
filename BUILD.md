# Standalone Windows build

Distribute only `dist\RobloxAFK.exe`. Double-clicking it opens the existing GUI.
The recipient needs neither Python nor an installer. Settings still reset on
reopening the window, as in the source application. No administrator privileges
are requested: the executable manifest uses `asInvoker` and `uiAccess=false`.

The target is 64-bit Windows 10/11. This build uses CPython 3.13.13 x64,
PyInstaller 6.22.0, and Tcl/Tk from the standard Windows Python installer.

Final artifact: `C:\Users\meirn\roblox-afk\dist\RobloxAFK.exe`,
12,599,218 bytes (12.02 MiB). SHA-256:
`CCE1DA563319592E82858DDCB5ED5E69F1729D8A416A1D328C0182661DDFE8ED`.

## Reproduce

Run PowerShell from this repository on 64-bit Windows, using the standard
64-bit Python 3.13 installation with Tcl/Tk. If `.venv` does not exist yet:

```powershell
py -3.13 -m venv .venv
```

Then install the pinned application and build dependencies and build:

```powershell
.\.venv\Scripts\python.exe -c "import struct, sys; assert sys.platform == 'win32' and struct.calcsize('P') == 8; print(sys.version)"
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest -v
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm RobloxAFK.spec
.\.venv\Scripts\python.exe .\verify_exe.py
Get-Item .\dist\RobloxAFK.exe | Select-Object FullName, Length
Get-FileHash .\dist\RobloxAFK.exe -Algorithm SHA256
```

`RobloxAFK.spec` selects PyInstaller's single-file, windowed mode, equivalent
to `--onefile --windowed`. The spec bundles Python, Tcl/Tk, and the existing
PyAutoGUI dependency. It excludes optional image-processing and development
packages, which this application does not use. No UPX, extra assets, installer,
or third-party GUI toolkit is needed. Build tools are not runtime dependencies.
See [PyInstaller's build options](https://pyinstaller.org/en/stable/usage.html).

The build recipe is reproducible; byte-identical output across machines and
Python installations is not promised. Use a clean virtual environment and
the exact Python version above to keep the dependency set consistent.

## Packaging changes

- `frozen_launcher.py` starts the existing GUI automatically; the original
  `roblox_afk.py` entry point retains console mode and `--gui` behavior.
- Logs are written to `%LOCALAPPDATA%\RobloxAFK\roblox_afk.log` for both entry
  points. The directory is created automatically. GUI startup is logged before
  creating the window. Logging handles absent stdout in a windowed process.
- Startup exceptions escaping the existing launch handler show a native Windows
  error dialog, including when logging or Tcl/Tk fails. Existing duplicate-instance
  errors retain the application's Tk error dialog.
- GUI widgets, worker ownership, cancellation, timings, settings, failsafe,
  foreground checks, input ordering, and mutex identity are unchanged.

## Verification

`verify_exe.py` launches the actual distribution executable with no arguments,
from unrelated temporary working directories, with Python environment variables
removed and PATH restricted to Windows System32. It verifies AMD64 and the
Windows GUI subsystem. It runs the bundled, opt-in `packaging_smoke.py`
diagnostic by setting `ROBLOXAFK_PACKAGING_TEST=1` in child processes only.
Normal launches never enable this diagnostic.

The diagnostic uses real Tk widgets, button callbacks, worker threads, automation
waits, and the production mutex. It replaces keyboard sending, foreground checks,
manual-key detection, and mouse failsafe detection with controlled mocks before
starting automation. It sends no real game input. It also captures duplicate
error dialogs programmatically, so the test can finish unattended. The original
unit tests separately exercise the failsafe and native input encoding with mocks.

The packaged scenarios cover invalid/valid settings, field disabling, duplicate
Start calls, ten Start/Stop cycles, a full Space/A sequence, closing while Space
or A is held, idle shutdown, and rejection of a second copy of the actual EXE.
After each scenario, checks verify no held mock keys or automation workers,
termination of both the onefile launcher and Python child process, deletion of
the extraction directory, and release of the production mutex.

Reports are saved in `%LOCALAPPDATA%\RobloxAFK\packaging-*.json` and aggregated
in `build\verification.json`. They contain process IDs and diagnostic state.
The diagnostic does not shorten the production startup or movement timings.

The local build passed 42 unit tests (39 original, 3 packaging checks), all five
packaged scenarios, and `pip check` on Windows 11 x64. The packaged tests observed
GUI readiness in approximately 1.0–1.7 seconds on this machine. This is a local
measurement, including diagnostics, rather than a cross-machine startup guarantee.

## Limits

Windows 10 and a fresh PC without Python were not available for testing.
The EXE bundles its runtime, and tests remove Python paths, but this does not
replace a clean-machine compatibility test. Physical double-click behavior,
visual appearance, and error-dialog appearance were not inspected through
desktop automation; the available Computer Use integration had no JavaScript
runtime tool. GUI creation and callbacks were exercised inside the actual EXE.
Native startup-error fallback is covered by a unit test with the dialog mocked.

Real Roblox behavior and physical key releases are unverified: all automated
movement tests deliberately mock inputs. Forced termination, Windows shutdown,
or rejected SendInput key-up events cannot guarantee cleanup; the existing
cooperative cleanup behavior is preserved. The executable is unsigned.

PyInstaller onefile runs a temporary bootloader parent and application child
while open and extracts its bundled runtime into the user's temporary directory.
Both processes and the extraction directory were gone after normal test exits.
