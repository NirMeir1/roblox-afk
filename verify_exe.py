"""Exercise the exact distribution binary with its opt-in mocked-input diagnostic."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time

import roblox_afk as app


def main():
    exe = Path(__file__).parent / "dist" / "RobloxAFK.exe"
    data = exe.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert struct.unpack_from("<H", data, pe + 4)[0] == 0x8664, "not AMD64"
    assert struct.unpack_from("<H", data, pe + 24 + 68)[0] == 2, "not Windows GUI"
    # Child environments omit Python/virtualenv paths; only the EXE is launched.
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV")}
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    env["ROBLOXAFK_PACKAGING_TEST"] = "1"
    directory = app.get_log_file().parent
    reports = []
    for scenario in ("cycles", "sequence", "space", "a", "idle"):
        env["ROBLOXAFK_TEST_SCENARIO"] = scenario
        report = directory / f"packaging-{scenario}.json"
        report.unlink(missing_ok=True)
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="RobloxAFK unrelated cwd ") as cwd:
            process = subprocess.Popen([str(exe)], env=env, cwd=cwd)
            try:
                deadline = start + 20
                while not report.exists():
                    assert process.poll() is None, "EXE exited before GUI ready"
                    assert time.monotonic() < deadline, "GUI startup timeout"
                    time.sleep(0.02)
                ready_seconds = time.monotonic() - start
                if scenario == "idle":
                    # A second copy of the same binary must fail before opening a GUI.
                    duplicate_env = dict(env, ROBLOXAFK_TEST_SCENARIO="duplicate")
                    duplicate_report = directory / "packaging-duplicate.json"
                    duplicate_report.unlink(missing_ok=True)
                    duplicate = subprocess.run([str(exe)], env=duplicate_env, cwd=cwd, timeout=15)
                    assert duplicate.returncode == 1, "duplicate EXE accepted"
                    result = json.loads(duplicate_report.read_text(encoding="utf-8"))
                    assert "already open" in result["errors"][0], result
                assert process.wait(timeout=45) == 0, "EXE failed"
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        result = json.loads(report.read_text(encoding="utf-8"))
        assert result["passed"], result
        assert not Path(result["extraction"]).exists(), "onefile extraction left behind"
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, result["pid"])
        if handle:
            kernel.CloseHandle(handle)
            raise AssertionError("application child process still exists")
        with app.SingleInstance():
            pass  # Production mutex must be released after every launch.
        if scenario in ("space", "a"):
            assert result["closed_while_held"] == scenario, result
            assert result["events"][-1] == ["up", scenario], result
        if scenario == "sequence":
            assert result["events"][:4] == [["down", "space"], ["up", "space"],
                                           ["down", "a"], ["up", "a"]], result
        result["ready_seconds"] = round(ready_seconds, 3)
        reports.append(result)
        print(f"PASS {scenario}: GUI ready {ready_seconds:.3f}s; no keys/workers/process/extraction left")
    output = Path(__file__).parent / "build" / "verification.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print(f"Verified AMD64 GUI EXE: {exe} ({exe.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
