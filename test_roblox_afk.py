"""Safety and Windows event tests. All keyboard events are mocked."""
import ctypes
import subprocess
import sys
import threading
import time
import tkinter as tk
import unittest
import uuid
from unittest.mock import Mock, call, patch
import pyautogui
import roblox_afk as app


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.mouse = Mock(FAILSAFE=True)
        self.keyboard = Mock()
        self.user32 = Mock()
        self.user32.GetAsyncKeyState.return_value = 0
        for item in (patch.object(app, 'configure_logging'),
                     patch.object(app.ctypes, 'WinDLL', return_value=self.user32),
                     patch.object(app, 'ScanKeyboard', return_value=self.keyboard)):
            item.start()
            self.addCleanup(item.stop)

    def test_inactive_window_sends_nothing(self):
        self.assertFalse(app.send_input(self.mouse, lambda: False))
        self.keyboard.key_down.assert_not_called()

    def test_space_then_a_in_order_with_correct_holds(self):
        with patch.object(app, 'wait_safely', return_value=True) as wait:
            self.assertTrue(app.send_input(self.mouse, lambda: True))
        self.assertEqual(self.keyboard.method_calls,
                         [call.key_down('space'), call.key_up('space'),
                          call.key_down('a'), call.key_up('a')])
        self.assertEqual([c.args[0] for c in wait.call_args_list], [0.15, 1.85, 0.1])
        self.assertAlmostEqual(wait.call_args_list[0].args[0] +
                               wait.call_args_list[1].args[0], 2.0)
        self.mouse.keyDown.assert_not_called()
        self.assertTrue(self.mouse.FAILSAFE)

    def test_held_controls_skip_input(self):
        self.user32.GetAsyncKeyState.return_value = 0x8000
        self.assertFalse(app.send_input(self.mouse, lambda: True))
        self.keyboard.key_down.assert_not_called()

    def test_focus_change_before_movement(self):
        self.assertFalse(app.send_input(self.mouse, Mock(side_effect=[True, False])))
        self.keyboard.key_down.assert_not_called()

    def test_focus_loss_during_space_releases_and_cancels_a(self):
        with patch.object(app, 'wait_safely', return_value=False):
            self.assertFalse(app.send_input(self.mouse, lambda: True))
        self.keyboard.key_down.assert_called_once_with('space')
        self.keyboard.key_up.assert_called_once_with('space')

    def test_interrupts_always_release_held_key(self):
        for exception in (KeyboardInterrupt, pyautogui.FailSafeException, RuntimeError):
            with self.subTest(exception=exception):
                keyboard = Mock()
                with patch.object(app, 'wait_safely', side_effect=exception):
                    with self.assertRaises(exception):
                        app.send_input(self.mouse, lambda: True, keyboard=keyboard)
                keyboard.key_up.assert_called_once_with('space')
                self.assertTrue(self.mouse.FAILSAFE)

    def test_interruption_during_a_releases_a(self):
        with patch.object(app, 'wait_safely', side_effect=[True, True, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                app.send_input(self.mouse, lambda: True)
        self.assertEqual(self.keyboard.key_up.call_args_list, [call('space'), call('a')])

    def test_focus_loss_in_pause_does_not_press_a(self):
        with patch.object(app, 'wait_safely', side_effect=[True, False]):
            self.assertFalse(app.send_input(self.mouse, lambda: True))
        self.keyboard.key_down.assert_called_once_with('space')
        self.keyboard.key_up.assert_called_once_with('space')

    def test_failsafe_in_pause_does_not_press_a(self):
        with patch.object(app, 'wait_safely', side_effect=[True, pyautogui.FailSafeException]):
            with self.assertRaises(pyautogui.FailSafeException):
                app.send_input(self.mouse, lambda: True)
        self.keyboard.key_down.assert_called_once_with('space')
        self.keyboard.key_up.assert_called_once_with('space')
        self.assertTrue(self.mouse.FAILSAFE)

    def test_failed_keydown_still_attempts_release(self):
        self.keyboard.key_down.side_effect = RuntimeError
        with self.assertRaises(RuntimeError):
            app.send_input(self.mouse, lambda: True)
        self.keyboard.key_up.assert_called_once_with('space')

    def test_release_error_preserves_failsafe(self):
        self.keyboard.key_up.side_effect = RuntimeError
        with patch.object(app, 'wait_safely', return_value=True):
            with self.assertRaises(RuntimeError):
                app.send_input(self.mouse, lambda: True)
        self.assertTrue(self.mouse.FAILSAFE)

    def test_movement_wait_stops_on_focus_loss(self):
        with patch.object(app.time, 'sleep') as sleep:
            self.assertFalse(app.wait_safely(0.1, self.mouse, lambda: False))
            sleep.assert_not_called()

    def test_real_failsafe_detects_corner_without_input(self):
        pyautogui.FAILSAFE = True
        with patch.object(pyautogui, 'position', return_value=(0, 0)):
            with self.assertRaises(pyautogui.FailSafeException):
                pyautogui.failSafeCheck()

    def test_startup_and_interval(self):
        with patch.object(app, 'Foreground'), patch.object(app, 'wait_safely') as wait, \
                patch.object(app, 'send_input', side_effect=[True, KeyboardInterrupt]) as send:
            self.assertEqual(app.main(), 0)
            self.assertEqual([c.args[0] for c in wait.call_args_list], [5, 300])
            self.assertEqual(send.call_count, 2)

    def test_custom_settings_reach_actual_sequence_and_repeat_wait(self):
        with patch.object(app, 'Foreground') as foreground, \
                patch.object(pyautogui, 'failSafeCheck'), \
                patch.object(app, 'wait_safely',
                             side_effect=[True, True, True, True, KeyboardInterrupt]) as wait:
            foreground.return_value.is_roblox.return_value = True
            self.assertEqual(app.main(interval_seconds=12.5, after_space_seconds=0.65), 0)
        self.assertEqual([c.args[0] for c in wait.call_args_list], [5, 0.15, 0.65, 0.1, 12.5])
        self.assertEqual(self.keyboard.method_calls,
                         [call.key_down('space'), call.key_up('space'),
                          call.key_down('a'), call.key_up('a')])
        self.assertEqual(app.INTERVAL_SECONDS, 300)
        self.assertEqual(app.AFTER_SPACE_SECONDS, 1.85)

    def test_first_attempt_runs_after_startup_without_interval_wait(self):
        with patch.object(app, 'Foreground'), patch.object(app, 'wait_safely') as wait, \
                patch.object(app, 'send_input', side_effect=KeyboardInterrupt):
            self.assertEqual(app.main(), 0)
            self.assertEqual([c.args[0] for c in wait.call_args_list], [5])

    def test_shutdown_before_any_input(self):
        for exception in (KeyboardInterrupt, pyautogui.FailSafeException):
            with self.subTest(exception=exception), patch.object(app, 'Foreground'), \
                    patch.object(app, 'wait_safely', side_effect=exception), \
                    patch.object(app, 'send_input') as send:
                self.assertEqual(app.main(), 0)
                send.assert_not_called()

    def test_cancellation_before_input_sends_nothing(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(app.Cancelled):
            app.send_input(self.mouse, lambda: True, stop_event=stop)
        self.keyboard.key_down.assert_not_called()

    def test_cancellation_during_each_hold_releases_key(self):
        for key in ('space', 'a'):
            with self.subTest(key=key):
                stop = threading.Event()
                keyboard = Mock()
                keyboard.key_down.side_effect = lambda pressed: stop.set() if pressed == key else None
                with patch.object(app, 'SPACE_SECONDS', 0), \
                        patch.object(app, 'AFTER_SPACE_SECONDS', 0):
                    with self.assertRaises(app.Cancelled):
                        app.send_input(self.mouse, lambda: True, keyboard, stop)
                self.assertEqual(keyboard.key_up.call_args_list[-1], call(key))
                if key == 'space':
                    keyboard.key_down.assert_called_once_with('space')

    def test_cancellation_in_pause_prevents_a(self):
        stop = threading.Event()
        self.keyboard.key_up.side_effect = lambda key: stop.set()
        with patch.object(app, 'SPACE_SECONDS', 0):
            with self.assertRaises(app.Cancelled):
                app.send_input(self.mouse, lambda: True, stop_event=stop)
        self.keyboard.key_down.assert_called_once_with('space')
        self.keyboard.key_up.assert_called_once_with('space')

    def test_long_wait_is_interruptible(self):
        stop = threading.Event()
        entered = threading.Event()
        cancelled = threading.Event()
        self.mouse.failSafeCheck.side_effect = entered.set

        def wait():
            try:
                app.wait_safely(300, self.mouse, stop_event=stop)
            except app.Cancelled:
                cancelled.set()

        worker = threading.Thread(target=wait)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            stop.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertTrue(cancelled.is_set())
        finally:
            stop.set()
            worker.join()

    def test_stop_during_startup_prevents_input(self):
        stop = threading.Event()
        stop.set()
        with patch.object(app, 'Foreground'), \
                patch.object(pyautogui, 'failSafeCheck'), \
                patch.object(app, 'send_input') as send:
            self.assertEqual(app.main(stop), 0)
        send.assert_not_called()

    def test_stop_during_interval_prevents_next_attempt(self):
        stop = threading.Event()
        with patch.object(app, 'Foreground'), \
                patch.object(pyautogui, 'failSafeCheck'), \
                patch.object(app, 'STARTUP_SECONDS', 0), \
                patch.object(app, 'send_input', side_effect=lambda *a, **kw: stop.set()) as send:
            self.assertEqual(app.main(stop), 0)
        send.assert_called_once()


class GuiTests(unittest.TestCase):
    """Real Tk widgets and real threads; automation is replaced with safe waits."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.window = app.AfkWindow(self.root)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.window.cleanup()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def pump_until(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.005)
        self.assertTrue(predicate())

    def test_repeated_start_stop_and_duplicate_start(self):
        entered = threading.Event()

        def automation(stop, **settings):
            entered.set()
            stop.wait()

        with patch.object(app, 'main', side_effect=automation) as run:
            for cycle in range(10):
                entered.clear()
                self.window.start_button.invoke()
                self.assertTrue(entered.wait(1))
                worker = self.window.worker
                self.assertEqual(self.window.status.get(), 'Running')
                self.assertFalse(worker.daemon)
                self.window.start()
                self.assertIs(self.window.worker, worker)
                # Tk remains responsive while the worker is waiting.
                tick = []
                self.root.after(0, lambda: tick.append(True))
                self.pump_until(lambda: bool(tick))
                self.window.stop_button.invoke()
                self.pump_until(lambda: self.window.worker is None)
                self.assertFalse(worker.is_alive())
                self.assertEqual(self.window.status.get(), 'Stopped')
                self.assertEqual(str(self.window.start_button['state']), 'normal')
            self.assertEqual(run.call_count, 10)
        self.assertFalse(any(t.name == 'RobloxAFK' for t in threading.enumerate()))

    def test_close_while_running_joins_worker_and_destroys_window(self):
        cleaned = threading.Event()

        def automation(stop, **settings):
            try:
                stop.wait()
            finally:
                cleaned.set()

        with patch.object(app, 'main', side_effect=automation):
            self.window.start()
            worker = self.window.worker
            # Invoke the actual WM close handler through Tcl.
            self.root.tk.call(self.root.protocol('WM_DELETE_WINDOW'))
            self.window.start()
            self.pump_until(lambda: self.window.worker is None)
        self.assertTrue(cleaned.is_set())
        self.assertFalse(worker.is_alive())
        with self.assertRaises(tk.TclError):
            self.root.winfo_exists()
        self.assertIsNone(self.window.poll_id)

    def test_close_while_stopped(self):
        self.window.close()
        with self.assertRaises(tk.TclError):
            self.root.winfo_exists()

    def test_worker_exit_updates_status_and_allows_restart(self):
        with patch.object(app, 'main', return_value=1):
            for cycle in range(2):
                self.window.start()
                self.pump_until(lambda: self.window.worker is None)
                self.assertEqual(self.window.status.get(), 'Stopped')
                self.assertEqual(str(self.window.start_button['state']), 'normal')

    def test_cleanup_on_mainloop_interruption_joins_worker(self):
        with patch.object(app, 'main', side_effect=lambda stop, **settings: stop.wait()):
            self.window.start()
            worker = self.window.worker
            self.window.cleanup()
        self.assertFalse(worker.is_alive())
        self.assertIsNone(self.window.poll_id)

    def test_invalid_settings_do_not_start_worker(self):
        cases = [('', '1.85'), ('text', '1.85'), ('0', '1.85'), ('-1', '1.85'),
                 ('nan', '1.85'), ('inf', '1.85'), ('300', ''), ('300', 'text'),
                 ('300', '-1'), ('300', 'nan'), ('300', 'inf')]
        with patch.object(app, 'main') as run:
            for interval, pause in cases:
                with self.subTest(interval=interval, pause=pause):
                    self.window.interval_value.set(interval)
                    self.window.after_space_value.set(pause)
                    self.window.start_button.invoke()
                    self.assertIsNone(self.window.worker)
                    self.assertEqual(self.window.status.get(), 'Stopped')
                    self.assertTrue(self.window.validation_error.get())
            run.assert_not_called()

    def test_gui_settings_are_snapshotted_and_apply_on_each_start(self):
        entered = threading.Event()
        captured = []

        def automation(stop, **settings):
            captured.append(settings)
            entered.set()
            stop.wait()

        self.window.interval_value.set('invalid')
        self.window.start()
        with patch.object(app, 'main', side_effect=automation):
            for interval, pause in [('30.5', '0'), ('300', '1.85')]:
                entered.clear()
                self.window.interval_value.set(interval)
                self.window.after_space_value.set(pause)
                self.window.start_button.invoke()
                self.assertTrue(entered.wait(1))
                self.assertEqual(captured[-1], {'interval_seconds': float(interval),
                                                'after_space_seconds': float(pause)})
                self.assertFalse(self.window.validation_error.get())
                for entry in self.window.setting_entries:
                    self.assertEqual(str(entry['state']), 'disabled')
                # Even programmatic edits cannot change the worker's snapshot.
                self.window.interval_value.set('999')
                self.assertEqual(captured[-1]['interval_seconds'], float(interval))
                self.window.stop()
                self.pump_until(lambda: self.window.worker is None)
                for entry in self.window.setting_entries:
                    self.assertEqual(str(entry['state']), 'normal')
        self.assertEqual(app.INTERVAL_SECONDS, 300)
        self.assertEqual(app.AFTER_SPACE_SECONDS, 1.85)

    def test_close_during_real_automation_releases_held_space(self):
        entered = threading.Event()
        keyboard = Mock()
        keyboard.key_down.side_effect = lambda key: entered.set()
        user32 = Mock()
        user32.GetAsyncKeyState.return_value = 0
        with patch.object(app, 'configure_logging'), \
                patch.object(app, 'STARTUP_SECONDS', 0), \
                patch.object(app, 'SPACE_SECONDS', 300), \
                patch.object(app, 'Foreground') as foreground, \
                patch.object(app.ctypes, 'WinDLL', return_value=user32), \
                patch.object(app, 'ScanKeyboard', return_value=keyboard), \
                patch.object(pyautogui, 'failSafeCheck'):
            foreground.return_value.is_roblox.return_value = True
            self.window.start()
            self.assertTrue(entered.wait(1))
            worker = self.window.worker
            self.window.close()
            self.pump_until(lambda: self.window.worker is None)
        self.assertFalse(worker.is_alive())
        keyboard.key_down.assert_called_once_with('space')
        keyboard.key_up.assert_called_once_with('space')


class LaunchTests(unittest.TestCase):
    def test_gui_launch_closes_mainloop_and_cleans_up(self):
        windows = []
        entered = threading.Event()
        finished = threading.Event()
        window_type = app.AfkWindow
        name = 'Local\\RobloxAFKTest-' + uuid.uuid4().hex

        def automation(stop, **settings):
            entered.set()
            try:
                stop.wait()
            finally:
                finished.set()

        def build_window(root):
            window = window_type(root)
            windows.append(window)
            root.after(0, window.start)
            root.after(100, window.close)
            return window

        with patch.object(app.sys, 'argv', ['roblox_afk.py', '--gui']), \
                patch.object(app, 'SingleInstance', return_value=app.SingleInstance(name)), \
                patch.object(app, 'AfkWindow', side_effect=build_window), \
                patch.object(app, 'main', side_effect=automation), \
                patch.object(app.logging, 'shutdown') as shutdown:
            self.assertEqual(app.launch(), 0)
        self.assertTrue(entered.is_set())
        self.assertTrue(finished.is_set())
        self.assertIsNone(windows[0].worker)
        self.assertIsNone(windows[0].poll_id)
        shutdown.assert_called_once()
        with app.SingleInstance(name):
            pass


class SingleInstanceTests(unittest.TestCase):
    def test_mutex_blocks_another_process(self):
        name = 'Local\\RobloxAFKTest-' + uuid.uuid4().hex
        code = (
            'import sys, roblox_afk as app\n'
            'try:\n'
            '    with app.SingleInstance(sys.argv[1]): pass\n'
            'except RuntimeError:\n'
            '    sys.exit(2)\n'
        )
        command = [sys.executable, '-c', code, name]
        with app.SingleInstance(name):
            duplicate = subprocess.run(command, capture_output=True, text=True, timeout=5,
                                       cwd=app.Path(app.__file__).parent)
            self.assertEqual(duplicate.returncode, 2, duplicate.stderr)
        released = subprocess.run(command, capture_output=True, text=True, timeout=5,
                                  cwd=app.Path(app.__file__).parent)
        self.assertEqual(released.returncode, 0, released.stderr)

    def test_native_mutex_blocks_duplicates_and_is_released(self):
        name = 'Local\\RobloxAFKTest-' + uuid.uuid4().hex
        with app.SingleInstance(name):
            with self.assertRaisesRegex(RuntimeError, 'already open'):
                with app.SingleInstance(name):
                    self.fail('Duplicate instance was accepted')
        with app.SingleInstance(name):
            pass

    def test_mutex_is_released_after_exception(self):
        name = 'Local\\RobloxAFKTest-' + uuid.uuid4().hex
        with self.assertRaises(ValueError):
            with app.SingleInstance(name):
                raise ValueError('test')
        with app.SingleInstance(name):
            pass


class NativeInputTests(unittest.TestCase):
    def test_windows_input_layout(self):
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(ctypes.sizeof(app.Input), expected)
        self.assertEqual(app.Input.data.offset, 8 if expected == 40 else 4)

    def test_scan_events_have_correct_flags_and_size(self):
        dll = Mock()
        events = []
        def accept(count, pointer, size):
            event = ctypes.cast(pointer, ctypes.POINTER(app.Input)).contents
            events.append((count, size, event.type, event.data.ki.wVk,
                           event.data.ki.wScan, event.data.ki.dwFlags))
            return 1
        dll.SendInput.side_effect = accept
        with patch.object(app.ctypes, 'WinDLL', return_value=dll):
            keyboard = app.ScanKeyboard()
            keyboard.key_down('space')
            keyboard.key_up('space')
            keyboard.key_down('a')
            keyboard.key_up('a')
        self.assertEqual(events, [
            (1, ctypes.sizeof(app.Input), 1, 0, 0x39, 0x08),
            (1, ctypes.sizeof(app.Input), 1, 0, 0x39, 0x0A),
            (1, ctypes.sizeof(app.Input), 1, 0, 0x1E, 0x08),
            (1, ctypes.sizeof(app.Input), 1, 0, 0x1E, 0x0A)])

    def test_rejected_windows_event_raises(self):
        dll = Mock()
        dll.SendInput.return_value = 0
        with patch.object(app.ctypes, 'WinDLL', return_value=dll):
            with self.assertRaises(OSError):
                app.ScanKeyboard().key_down('space')

    def test_unknown_key_is_never_sent(self):
        dll = Mock()
        with patch.object(app.ctypes, 'WinDLL', return_value=dll):
            with self.assertRaises(KeyError):
                app.ScanKeyboard().key_down('enter')
        dll.SendInput.assert_not_called()


if __name__ == '__main__':
    unittest.main()
