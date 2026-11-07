"""Checks for console-free launch and per-user logging; no game inputs."""
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import frozen_launcher
import roblox_afk as app


class PackagingTests(unittest.TestCase):
    def test_windowed_logging_uses_localappdata_without_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(app.os.environ, {"LOCALAPPDATA": directory}), \
                    patch.object(app.sys, "stdout", None):
                try:
                    app.configure_logging()
                    app.LOG.info("windowed test")
                    expected = Path(directory) / "RobloxAFK" / "roblox_afk.log"
                    self.assertEqual(app.get_log_file(), expected)
                    self.assertIn("windowed test", expected.read_text(encoding="utf-8"))
                    self.assertEqual(len(logging.getLogger().handlers), 1)
                finally:
                    for handler in logging.getLogger().handlers[:]:
                        handler.close()
                        logging.getLogger().removeHandler(handler)

    def test_frozen_launcher_opens_gui(self):
        with patch.object(app, "configure_logging"), \
                patch.object(app, "launch", return_value=0) as launch, \
                patch.object(app.sys, "argv", ["RobloxAFK.exe"]), \
                patch.dict(app.os.environ, {"ROBLOXAFK_PACKAGING_TEST": "0"}):
            self.assertEqual(frozen_launcher.run(), 0)
            launch.assert_called_once()
            self.assertEqual(app.sys.argv[1:], ["--gui"])

    def test_startup_error_uses_native_dialog_even_when_logging_fails(self):
        with patch.object(app, "configure_logging", side_effect=OSError("no log access")), \
                patch.object(frozen_launcher.ctypes.windll.user32, "MessageBoxW") as dialog, \
                patch.object(frozen_launcher.logging, "exception"):
            self.assertEqual(frozen_launcher.run(), 1)
            self.assertIn("no log access", dialog.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
