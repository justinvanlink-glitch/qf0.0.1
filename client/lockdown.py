"""
Lockdown-режим для Windows під час тесту:
- повноекранний режим поверх усіх вікон
- блокування небезпечних комбінацій клавіш (low-level hook)
- ClipCursor у межах вікна
- DisableTaskMgr (HKCU) на час тесту з обов'язковим відновленням
- відстеження втрати фокуса

ОБМЕЖЕННЯ (чесно):
- Ctrl+Alt+Del програмно не блокується
- телефон і другий пристрій програмно не відстежуються
"""

from __future__ import annotations

import atexit
import ctypes
import logging
import sys
import threading
from ctypes import wintypes
from typing import Callable

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# Virtual-Key codes
VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_SNAPSHOT = 0x2C  # PrintScreen
VK_F4 = 0x73
VK_L = 0x4C
VK_D = 0x44
VK_S = 0x53

# Modifiers
MOD_ALT = 0x0001
MOD_CTRL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
HC_ACTION = 0

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
        ctypes.c_long,
        ctypes.c_int,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )


class Lockdown:
    """
    Керує lockdown-режимом на час однієї спроби тесту.
    """

    def __init__(
        self,
        window,  # QMainWindow / QWidget
        on_violation: Callable[[str, str], None],
        # on_violation(vtype, details)
    ) -> None:
        self.window = window
        self.on_violation = on_violation
        self._active = False
        self._hook = None
        self._hook_proc = None
        self._hook_thread: threading.Thread | None = None
        self._taskmgr_was_disabled = False
        self._original_flags = None
        self._cursor_clipped = False

    # ------------------------------------------------------------------ public
    def activate(self) -> None:
        if self._active:
            return
        self._active = True
        logger.info("Lockdown: активація")

        try:
            self._enter_fullscreen()
        except Exception:
            logger.exception("Fullscreen")

        try:
            self._disable_taskmgr()
        except Exception:
            logger.exception("DisableTaskMgr")

        try:
            self._install_keyboard_hook()
        except Exception:
            logger.exception("Keyboard hook")

        try:
            self._clip_cursor()
        except Exception:
            logger.exception("ClipCursor")

        # Відновлення при аварійному виході процесу
        atexit.register(self._atexit_restore)

        # Фокус
        try:
            self.window.activateWindow()
            self.window.raise_()
        except Exception:
            pass

    def deactivate(self) -> None:
        if not self._active:
            return
        self._active = False
        logger.info("Lockdown: деактивація")

        try:
            self._uninstall_keyboard_hook()
        except Exception:
            logger.exception("Unhook")

        try:
            self._unclip_cursor()
        except Exception:
            logger.exception("UnclipCursor")

        try:
            self._restore_taskmgr()
        except Exception:
            logger.exception("Restore TaskMgr")

        try:
            self._exit_fullscreen()
        except Exception:
            logger.exception("Exit fullscreen")

        try:
            atexit.unregister(self._atexit_restore)
        except Exception:
            pass

    def handle_focus_out(self) -> None:
        """Викликати з eventFilter / changeEvent при втраті фокуса."""
        if not self._active:
            return
        self.on_violation("focus_lost", "Втрата фокуса вікна")
        try:
            self.window.activateWindow()
            self.window.raise_()
            if IS_WINDOWS:
                hwnd = int(self.window.winId())
                user32.SetForegroundWindow(hwnd)
        except Exception:
            logger.exception("Повернення фокуса")

    # ------------------------------------------------------------------ fullscreen
    def _enter_fullscreen(self) -> None:
        from PyQt6.QtCore import Qt

        self._original_flags = self.window.windowFlags()
        self.window.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.window.showFullScreen()
        self.window.activateWindow()
        self.window.raise_()

    def _exit_fullscreen(self) -> None:
        if self._original_flags is not None:
            self.window.setWindowFlags(self._original_flags)
        self.window.showNormal()

    # ------------------------------------------------------------------ Task Manager
    def _disable_taskmgr(self) -> None:
        if not IS_WINDOWS:
            return
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
        try:
            key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            try:
                try:
                    current, _ = winreg.QueryValueEx(key, "DisableTaskMgr")
                    self._taskmgr_was_disabled = bool(current)
                except FileNotFoundError:
                    self._taskmgr_was_disabled = False
                winreg.SetValueEx(key, "DisableTaskMgr", 0, winreg.REG_DWORD, 1)
                logger.info("DisableTaskMgr=1 встановлено")
            finally:
                winreg.CloseKey(key)
        except PermissionError:
            logger.warning("Немає прав для DisableTaskMgr (не критично)")
        except Exception:
            logger.exception("DisableTaskMgr")

    def _restore_taskmgr(self) -> None:
        if not IS_WINDOWS:
            return
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            try:
                if self._taskmgr_was_disabled:
                    winreg.SetValueEx(key, "DisableTaskMgr", 0, winreg.REG_DWORD, 1)
                else:
                    try:
                        winreg.DeleteValue(key, "DisableTaskMgr")
                    except FileNotFoundError:
                        winreg.SetValueEx(key, "DisableTaskMgr", 0, winreg.REG_DWORD, 0)
                logger.info("DisableTaskMgr відновлено")
            finally:
                winreg.CloseKey(key)
        except Exception:
            logger.exception("Відновлення DisableTaskMgr")

    def _atexit_restore(self) -> None:
        """Гарантоване відновлення при виході процесу."""
        try:
            self._restore_taskmgr()
        except Exception:
            pass
        try:
            self._unclip_cursor()
        except Exception:
            pass

    # ------------------------------------------------------------------ ClipCursor
    def _clip_cursor(self) -> None:
        if not IS_WINDOWS:
            return
        try:
            hwnd = int(self.window.winId())
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                user32.ClipCursor(ctypes.byref(rect))
                self._cursor_clipped = True
        except Exception:
            logger.exception("ClipCursor")

    def _unclip_cursor(self) -> None:
        if not IS_WINDOWS or not self._cursor_clipped:
            return
        try:
            user32.ClipCursor(None)
            self._cursor_clipped = False
        except Exception:
            pass

    # ------------------------------------------------------------------ Keyboard hook
    def _install_keyboard_hook(self) -> None:
        if not IS_WINDOWS:
            logger.info("Keyboard hook доступний лише на Windows")
            return

        # Зберігаємо self для callback
        lockdown_ref = self

        def _is_blocked(vk: int, flags: int) -> str | None:
            """Повертає назву комбінації якщо заблокована, інакше None."""
            # Alt held?
            alt = bool(user32.GetAsyncKeyState(0x12) & 0x8000)  # VK_MENU
            ctrl = bool(user32.GetAsyncKeyState(0x11) & 0x8000)  # VK_CONTROL
            shift = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
            win = bool(
                (user32.GetAsyncKeyState(VK_LWIN) & 0x8000)
                or (user32.GetAsyncKeyState(VK_RWIN) & 0x8000)
            )

            # Alt+Tab
            if alt and vk == VK_TAB:
                return "Alt+Tab"
            # Alt+F4
            if alt and vk == VK_F4:
                return "Alt+F4"
            # Ctrl+Esc
            if ctrl and vk == VK_ESCAPE:
                return "Ctrl+Esc"
            # Ctrl+Shift+Esc
            if ctrl and shift and vk == VK_ESCAPE:
                return "Ctrl+Shift+Esc"
            # Win key alone or Win+…
            if vk in (VK_LWIN, VK_RWIN):
                return "Win"
            if win and vk == VK_D:
                return "Win+D"
            if win and vk == VK_L:
                return "Win+L"
            if win and shift and vk == VK_S:
                return "Win+Shift+S"
            # PrintScreen
            if vk == VK_SNAPSHOT:
                return "PrintScreen"
            return None

        @LowLevelKeyboardProc
        def hook_proc(nCode, wParam, lParam):
            if nCode == HC_ACTION and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                blocked = _is_blocked(kb.vkCode, kb.flags)
                if blocked:
                    # Порушення в головному потоці Qt — через сигнал складно,
                    # викликаємо напряму (on_violation має бути thread-safe або через QueuedConnection)
                    try:
                        lockdown_ref.on_violation("blocked_key", blocked)
                    except Exception:
                        pass
                    return 1  # block
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._hook_proc = hook_proc  # запобігти GC
        self._hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_proc,
            kernel32.GetModuleHandleW(None),
            0,
        )
        if not self._hook:
            logger.error("SetWindowsHookEx не вдався")
            return

        # Message loop у окремому потоці для LL-hook
        def _msg_loop():
            msg = wintypes.MSG()
            while self._active:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        self._hook_thread = threading.Thread(target=_msg_loop, daemon=True, name="kb-hook")
        self._hook_thread.start()
        logger.info("Keyboard hook встановлено")

    def _uninstall_keyboard_hook(self) -> None:
        if not IS_WINDOWS or not self._hook:
            return
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        # Розбудити GetMessage
        if self._hook_thread and self._hook_thread.is_alive():
            user32.PostThreadMessageW(
                self._hook_thread.ident or 0,
                0x0012,  # WM_QUIT
                0,
                0,
            )
        logger.info("Keyboard hook знято")
