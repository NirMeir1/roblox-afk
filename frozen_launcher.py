"""Windowed executable entry point; the Python CLI remains in roblox_afk.py."""
import ctypes
import logging
import os
import sys


def run():
    try:
        import roblox_afk as app
        app.configure_logging()
        logging.info("GUI startup PID=%d", os.getpid())
        # A self-contained, input-free diagnostic for the exact shipped binary.
        if os.environ.get("ROBLOXAFK_PACKAGING_TEST") == "1":
            import packaging_smoke
            packaging_smoke.install(app)
        sys.argv = [sys.argv[0], "--gui"]
        return app.launch()
    except Exception as error:
        logging.exception("Roblox AFK startup failed")
        ctypes.windll.user32.MessageBoxW(
            None, f"Roblox AFK could not start.\n\n{error}\n\n"
            "Logs (when available): %LOCALAPPDATA%\\RobloxAFK\\roblox_afk.log",
            "Roblox AFK - startup error", 0x10)
        return 1
    finally:
        logging.shutdown()


if __name__ == "__main__":
    raise SystemExit(run())
