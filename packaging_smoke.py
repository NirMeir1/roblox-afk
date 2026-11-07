"""Opt-in frozen diagnostics. Never sends keyboard input or changes normal runs."""
import json
import os
from pathlib import Path
import threading
import time


def install(app):
    import pyautogui
    from tkinter import messagebox

    scenario = os.environ.get("ROBLOXAFK_TEST_SCENARIO", "cycles")
    report = app.get_log_file().with_name(f"packaging-{scenario}.json")
    state = {"scenario": scenario, "pid": os.getpid(), "events": [], "errors": []}
    held = set()
    original_window = app.AfkWindow
    original_dll = app.ctypes.WinDLL

    def save():
        report.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def error(title, message):
        state["errors"].append(str(message))
        save()

    messagebox.showerror = error

    class Keyboard:
        def key_down(self, key):
            held.add(key)
            state["events"].append(["down", key])

        def key_up(self, key):
            held.discard(key)
            state["events"].append(["up", key])

    # Substitute all game input, while retaining the real mutex and GUI.
    class InputCheck:
        def GetAsyncKeyState(self, key):
            return 0

    def dll(name, *args, **kwargs):
        if name == "user32":
            return InputCheck()
        return original_dll(name, *args, **kwargs)

    app.ctypes.WinDLL = dll
    app.ScanKeyboard = Keyboard
    app.Foreground = lambda: type("Foreground", (), {"is_roblox": lambda self: True})()
    pyautogui.failSafeCheck = lambda: None

    def build(root):
        window = original_window(root)
        state["ready"] = True
        state["extraction"] = str(getattr(app.sys, "_MEIPASS", ""))
        save()
        started = time.monotonic()
        cycle = 0
        phase = "start"

        def require(condition, message):
            if not condition:
                raise AssertionError(message)

        def tick():
            nonlocal cycle, phase
            try:
                require(time.monotonic() - started < 35, "diagnostic timed out")
                if phase == "start":
                    if scenario == "idle":
                        root.after(10000, window.close)
                        return
                    window.interval_value.set("0")
                    window.start_button.invoke()
                    require(window.worker is None and window.validation_error.get(),
                            "invalid settings accepted")
                    window.interval_value.set("0.1")
                    window.after_space_value.set("0.05")
                    window.start_button.invoke()
                    worker = window.worker
                    window.start()
                    require(worker is window.worker, "duplicate worker started")
                    require(window.status.get() == "Running", "running status missing")
                    require(all(str(e["state"]) == "disabled" for e in window.setting_entries),
                            "settings were not disabled")
                    if scenario in ("space", "a", "sequence") and cycle == 0:
                        phase = "input"
                    else:
                        window.stop_button.invoke()
                        phase = "stopping"
                elif phase == "input":
                    if scenario in held:
                        require(window.worker.is_alive(), "worker exited during input")
                        state["closed_while_held"] = scenario
                        root.tk.call(root.protocol("WM_DELETE_WINDOW"))
                        return
                    if scenario == "sequence" and len(state["events"]) >= 4:
                        window.stop_button.invoke()
                        phase = "stopping"
                elif phase == "stopping" and window.worker is None:
                    require(not held, "mock keys stuck")
                    require(window.status.get() == "Stopped", "stopped status missing")
                    require(str(window.start_button["state"]) == "normal", "Start disabled")
                    require(all(str(e["state"]) == "normal" for e in window.setting_entries),
                            "settings did not reenable")
                    cycle += 1
                    state["cycles"] = cycle
                    if cycle >= 10:
                        window.close()
                        return
                    phase = "start"
                root.after(5, tick)
            except Exception as exc:
                state["errors"].append(str(exc))
                window.close()

        def callback_error(kind, value, tb):
            state["errors"].append(str(value))
            window.close()

        root.report_callback_exception = callback_error
        cleanup = window.cleanup

        def final_cleanup():
            cleanup()
            state["held"] = sorted(held)
            state["workers"] = [t.name for t in threading.enumerate() if t.name == "RobloxAFK"]
            state["passed"] = not state["errors"] and not held and not state["workers"]
            save()

        window.cleanup = final_cleanup
        root.after(20, tick)
        return window

    app.AfkWindow = build
