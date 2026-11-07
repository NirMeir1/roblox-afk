"""Windows-only treadmill AFK experiment using Space followed by A."""

import ctypes
from ctypes import wintypes
import logging
import math
import os
from pathlib import Path, PureWindowsPath
import sys
import threading
import time

INTERVAL_SECONDS = 300
STARTUP_SECONDS = 5
SPACE_SECONDS = 0.15
# Space is held for 0.15s; this pause makes A start about 2s after Space down.
AFTER_SPACE_SECONDS = 1.85
MOVE_SECONDS = 0.1
LOG = logging.getLogger("roblox_afk")


class MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KeyboardInput(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class InputData(ctypes.Union):
    # All three members are required for the Windows INPUT structure's size.
    _fields_ = [("mi", MouseInput), ("ki", KeyboardInput), ("hi", HardwareInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", InputData)]


class ScanKeyboard:
    """Standard Windows SendInput; success means queued by Windows, not the game."""

    SCANS = {"space": 0x39, "a": 0x1E}

    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.user32.SendInput.restype = wintypes.UINT

    def send(self, key, release=False):
        event = Input(type=1)
        event.data.ki = KeyboardInput(wVk=0, wScan=self.SCANS[key],
                                     dwFlags=0x0008 | (0x0002 if release else 0))
        ctypes.set_last_error(0)
        sent = self.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input))
        if sent != 1:
            raise OSError(ctypes.get_last_error(),
                          "Windows SendInput did not accept the keyboard event")
        LOG.info("Windows accepted %s %s (scan code 0x%02X).",
                 key.upper(), "up" if release else "down", self.SCANS[key])

    def key_down(self, key):
        self.send(key)

    def key_up(self, key):
        # Release must remain possible after a mouse-corner stop or focus loss.
        self.send(key, release=True)


class Foreground:
    """Identify the foreground executable; failures deny input."""

    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        ]
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    def window(self):
        return self.user32.GetForegroundWindow()

    def is_roblox(self):
        hwnd = self.window()
        if not hwnd:
            LOG.info("Foreground check: no active window.")
            return False
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = self.kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            LOG.info("Foreground check: cannot inspect process %d (Windows error %d).",
                     pid.value, ctypes.get_last_error())
            return False
        try:
            path = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(path))
            if not self.kernel32.QueryFullProcessImageNameW(
                handle, 0, path, ctypes.byref(size)
            ):
                LOG.info("Foreground check: cannot read executable (Windows error %d).",
                         ctypes.get_last_error())
                return False
            executable = PureWindowsPath(path.value).name
            if executable.casefold() != "robloxplayerbeta.exe":
                LOG.info("Foreground check: %s is active, not Roblox.", executable)
                return False
            if self.window() != hwnd:
                LOG.info("Foreground check: window changed during check.")
                return False
            return True
        finally:
            self.kernel32.CloseHandle(handle)


class Cancelled(Exception):
    """Cooperative stop request, including while a key is held."""


def check_cancelled(stop_event):
    if stop_event is not None and stop_event.is_set():
        raise Cancelled


def wait_safely(seconds, mouse, allowed=None, stop_event=None):
    deadline = time.monotonic() + seconds
    while True:
        check_cancelled(stop_event)
        mouse.failSafeCheck()
        if allowed is not None and not allowed():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        delay = min(0.02 if allowed is not None else 0.25, remaining)
        if stop_event is None:
            time.sleep(delay)
        elif stop_event.wait(delay):
            raise Cancelled


def send_input(mouse, allowed, keyboard=None, stop_event=None, after_space_seconds=None):
    """Tap Space, then briefly hold A; treadmill return must be checked in-game."""
    if after_space_seconds is None:
        after_space_seconds = AFTER_SPACE_SECONDS
    check_cancelled(stop_event)
    mouse.failSafeCheck()
    if not allowed():
        LOG.info("Skipped: target window is not in the foreground.")
        return False
    # Avoid competing with manual movement or mouse controls.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if any(user32.GetAsyncKeyState(key) & 0x8000
           for key in (1, 2, 4, 5, 6, 0x20, 0x41, 0x44, 0x57, 0x53)):
        LOG.info("Skipped: a mouse button or movement key is held.")
        return False
    if keyboard is None:
        keyboard = ScanKeyboard()
    for key, duration in (("space", SPACE_SECONDS), ("a", MOVE_SECONDS)):
        mouse.failSafeCheck()
        if not allowed():
            LOG.info("Movement cancelled: Roblox lost foreground focus.")
            return False
        try:
            check_cancelled(stop_event)
            keyboard.key_down(key)
            LOG.info("Holding %s for %.2f seconds.", key.upper(), duration)
            if not wait_safely(duration, mouse, allowed, stop_event):
                LOG.info("Movement cancelled: Roblox lost foreground focus.")
                return False
        finally:
            # Native key-up does not run a mouse failsafe check: always release.
            keyboard.key_up(key)
            LOG.info("Released %s.", key.upper())
        if key == "space":
            LOG.info("Waiting %.2f seconds before A.", after_space_seconds)
            if not wait_safely(after_space_seconds, mouse, allowed, stop_event):
                LOG.info("Movement cancelled during pause: Roblox lost foreground focus.")
                return False
    LOG.info("Completed Space then A attempt; treadmill return is not verified.")
    return True


def configure_logging():
    log_file = get_log_file()
    handlers = [logging.FileHandler(log_file, encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S",
                        handlers=handlers,
                        force=True)


def get_log_file():
    directory = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "RobloxAFK"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "roblox_afk.log"


def main(stop_event=None, *, interval_seconds=None, after_space_seconds=None):
    # Snapshot each run's settings; never read Tk variables from this thread.
    if interval_seconds is None:
        interval_seconds = INTERVAL_SECONDS
    if after_space_seconds is None:
        after_space_seconds = AFTER_SPACE_SECONDS
    configure_logging()
    log_file = get_log_file()
    LOG.info("Session PID=%d; log file: %s", os.getpid(), log_file)
    if sys.platform != "win32":
        LOG.error("This proof of concept requires Windows.")
        return 1
    try:
        import pyautogui as mouse
    except ImportError:
        LOG.error("Missing dependency. Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        return 1
    mouse.FAILSAFE = True
    mouse.PAUSE = 0.1
    try:
        foreground = Foreground()
        LOG.info("Keyboard backend: Windows SendInput scan codes; PyAutoGUI failsafe enabled.")
        LOG.info("Timing: Space %.2fs, pause %.2fs, A %.2fs.",
                 SPACE_SECONDS, after_space_seconds, MOVE_SECONDS)
        LOG.info("Starting in 5 seconds. Ctrl+C or a primary-screen corner stops the tool.")
        wait_safely(STARTUP_SECONDS, mouse, stop_event=stop_event)
        LOG.info("Ready. Trying Space then A now; waits %g seconds after each attempt. Only RobloxPlayerBeta.exe is eligible.",
                 interval_seconds)
        while True:
            check_cancelled(stop_event)
            send_input(mouse, foreground.is_roblox, stop_event=stop_event,
                       after_space_seconds=after_space_seconds)
            wait_safely(interval_seconds, mouse, stop_event=stop_event)
    except Cancelled:
        LOG.info("Stopped by request; key cleanup completed.")
        return 0
    except KeyboardInterrupt:
        LOG.info("Stopped safely by Ctrl+C.")
        return 0
    except mouse.FailSafeException:
        LOG.warning("Stopped by PyAutoGUI emergency mouse-corner failsafe.")
        return 0
    except Exception:
        LOG.exception("Stopped after an error; no further input will be sent.")
        return 1


class AfkWindow:
    """Tk callbacks own widgets; the worker only reads its cancellation event."""

    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.worker = None
        self.stop_event = threading.Event()
        self.closing = False
        self.poll_id = None
        root.title("Roblox AFK")
        root.configure(background="#f3f5f9")
        root.resizable(False, False)
        root.minsize(440, 340)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        style = ttk.Style(root)
        style.theme_use("clam")  # Ships with Tk; supports button colors on Windows.
        style.configure("App.TFrame", background="#f3f5f9")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#f3f5f9", foreground="#182338",
                        font=("Segoe UI", 23, "bold"))
        style.configure("Hint.TLabel", background="#f3f5f9", foreground="#56647a",
                        font=("Segoe UI", 10))
        style.configure("Caption.TLabel", background="#ffffff", foreground="#56647a",
                        font=("Segoe UI", 10))
        style.configure("Status.TLabel", background="#ffffff", foreground="#56647a",
                        font=("Segoe UI", 12, "bold"))
        for name, normal, hover, pressed, disabled in (
            ("Start", "#2563eb", "#1d4ed8", "#1e40af", "#e3eaf7"),
            ("Stop", "#b42336", "#991b2d", "#7f1d2d", "#f1e7e9"),
        ):
            button_style = f"{name}.TButton"
            style.configure(button_style, font=("Segoe UI", 11, "bold"),
                            padding=(18, 12), borderwidth=0, background=normal,
                            foreground="#ffffff", focusthickness=2,
                            focuscolor="#182338")
            style.map(button_style,
                      background=[("disabled", disabled), ("pressed", pressed),
                                  ("active", hover)],
                      foreground=[("disabled", "#68758a")])

        frame = ttk.Frame(root, padding=28, style="App.TFrame")
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="Roblox AFK", style="Title.TLabel").grid(sticky="w")
        ttk.Label(frame, text="Keep Roblox active after starting.",
                  style="Hint.TLabel").grid(sticky="w", pady=(4, 20))

        card = ttk.Frame(frame, padding=18, style="Card.TFrame")
        card.grid(sticky="ew")
        card.columnconfigure(1, weight=1)
        self.status_dot = ttk.Label(card, text="\u25cf", style="Status.TLabel")
        self.status_dot.grid(row=0, column=0, padx=(0, 9))
        self.status = tk.StringVar(root, value="Stopped")
        self.status_label = ttk.Label(card, textvariable=self.status, style="Status.TLabel")
        self.status_label.grid(row=0, column=1, sticky="w")
        self.timing_summary = tk.StringVar(root)
        self.update_timing_summary(INTERVAL_SECONDS, AFTER_SPACE_SECONDS)
        ttk.Label(card, textvariable=self.timing_summary, style="Caption.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        settings = ttk.Frame(frame, style="App.TFrame")
        settings.grid(sticky="ew", pady=(18, 0))
        settings.columnconfigure(0, weight=1)
        self.interval_value = tk.StringVar(root, value=f"{INTERVAL_SECONDS:g}")
        self.after_space_value = tk.StringVar(root, value=f"{AFTER_SPACE_SECONDS:g}")
        self.setting_entries = []
        for row, (label, variable) in enumerate((
            ("Repeat interval (seconds)", self.interval_value),
            ("Pause after Space (seconds)", self.after_space_value),
        )):
            ttk.Label(settings, text=label, style="Hint.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            entry = ttk.Entry(settings, textvariable=variable, width=10,
                              font=("Segoe UI", 11), justify="right")
            entry.grid(row=row, column=1, sticky="e", pady=5)
            self.setting_entries.append(entry)
        ttk.Label(frame, text="Pause starts when Space is released. Apply with Start.",
                  style="Hint.TLabel", wraplength=380).grid(sticky="w", pady=(6, 0))
        self.validation_error = tk.StringVar(root)
        ttk.Label(frame, textvariable=self.validation_error, style="Hint.TLabel",
                  foreground="#b42336", wraplength=380).grid(sticky="w", pady=(4, 0))

        buttons = ttk.Frame(frame, style="App.TFrame")
        buttons.grid(sticky="ew", pady=(20, 16))
        buttons.columnconfigure((0, 1), weight=1, uniform="buttons")
        self.start_button = ttk.Button(buttons, text="Start", command=self.start,
                                       style="Start.TButton")
        self.start_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.stop_button = ttk.Button(buttons, text="Stop", command=self.stop,
                                      style="Stop.TButton", state="disabled")
        self.stop_button.grid(row=0, column=1, padx=(6, 0), sticky="ew")
        ttk.Label(frame, text=f"Switch to Roblox within {STARTUP_SECONDS} seconds of Start.",
                  style="Hint.TLabel").grid(sticky="w")
        root.protocol("WM_DELETE_WINDOW", self.close)

    def update_timing_summary(self, interval, after_space):
        interval_text = (f"{interval / 60:g} min" if interval % 60 == 0
                         else f"{interval:g} sec")
        self.timing_summary.set(f"{interval_text} interval  \u00b7  "
                               f"{SPACE_SECONDS + after_space:g}s Space to A")

    def set_running(self, running):
        self.status.set("Running" if running else "Stopped")
        color = "#15803d" if running else "#56647a"
        self.status_dot.configure(foreground=color)
        self.status_label.configure(foreground=color)
        for entry in self.setting_entries:
            entry.configure(state="disabled" if running else "normal")

    def start(self):
        if self.closing or self.worker is not None:
            return
        for variable, name, allow_zero in (
            (self.interval_value, "Repeat interval", False),
            (self.after_space_value, "Pause after Space", True),
        ):
            try:
                value = float(variable.get())
                if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
                    raise ValueError
            except ValueError:
                rule = "zero or greater" if allow_zero else "greater than zero"
                self.validation_error.set(f"{name}: enter a number {rule}.")
                return
        interval = float(self.interval_value.get())
        after_space = float(self.after_space_value.get())
        self.validation_error.set("")
        self.stop_event.clear()
        self.worker = threading.Thread(target=main, args=(self.stop_event,),
                                       kwargs={"interval_seconds": interval,
                                               "after_space_seconds": after_space},
                                       name="RobloxAFK", daemon=False)
        try:
            self.worker.start()
        except Exception:
            self.worker = None
            raise
        self.update_timing_summary(interval, after_space)
        self.set_running(True)
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.poll_id = self.root.after(20, self.poll)

    def stop(self):
        self.stop_event.set()
        self.stop_button.configure(state="disabled")

    def poll(self):
        self.poll_id = None
        if self.worker is not None:
            if self.worker.is_alive():
                self.poll_id = self.root.after(20, self.poll)
                return
            self.worker.join()
            self.worker = None
        self.set_running(False)
        self.stop_button.configure(state="disabled")
        if self.closing:
            self.root.destroy()
        else:
            self.start_button.configure(state="normal")

    def close(self):
        self.closing = True
        self.start_button.configure(state="disabled")
        self.stop()
        if self.worker is None:
            self.root.destroy()

    def cleanup(self):
        # Also handles Ctrl+C or an unexpected exit from Tk's main loop.
        self.stop_event.set()
        if self.worker is not None:
            self.worker.join()
            self.worker = None
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None


class SingleInstance:
    """Keep one CLI or GUI instance in this Windows login session."""

    def __init__(self, name="Local\\RobloxAFKPython"):
        self.name = name

    def __enter__(self):
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                               wintypes.LPCWSTR]
        self.kernel32.CreateMutexW.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel32.CreateMutexW(None, False, self.name)
        error = ctypes.get_last_error()
        if not self.handle:
            raise ctypes.WinError(error)
        if error == 183:  # ERROR_ALREADY_EXISTS
            self.kernel32.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError("Roblox AFK is already open. Use the existing window or console.")
        return self

    def __exit__(self, *exc):
        self.kernel32.CloseHandle(self.handle)
        self.handle = None


def launch():
    gui = sys.argv[1:] == ["--gui"]
    if sys.argv[1:] and not gui:
        print("Usage: roblox_afk.py [--gui]")
        return 1
    if sys.platform != "win32":
        print("This proof of concept requires Windows.")
        return 1
    try:
        with SingleInstance():
            if not gui:
                return main()
            import tkinter as tk

            root = tk.Tk()
            window = None
            try:
                window = AfkWindow(root)
                root.mainloop()
            finally:
                if window is not None:
                    window.cleanup()
                try:
                    root.destroy()
                except tk.TclError:
                    pass  # Already destroyed by the close callback.
            return 0
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        LOG.exception("Unable to run Roblox AFK.")
        if gui:
            from tkinter import messagebox
            messagebox.showerror("Roblox AFK", str(error))
        return 1
    finally:
        logging.shutdown()


if __name__ == "__main__":
    raise SystemExit(launch())
