"""中文输入助手：把 Unicode 文本经 SendInput 注入到游戏。

原理：Windows 的 SendInput + KEYEVENTF_UNICODE 可以把任意 Unicode
字符（包括中文）直接送入系统输入队列，前台窗口会收到对应的字符事件。
铁锈战争的 libGDX 桌面版通过字符事件接收文本，因此注入的中文能进输入框。

本模块不修改游戏本体、不注入游戏内存，只模拟键盘输入。
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Win32 常量
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_CONTROL = 0x0002
MOD_ALT = 0x0001
MOD_NOREPEAT = 0x4000
SW_RESTORE = 9

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


_user32 = ctypes.windll.user32


def _send_key_event(vk: int = 0, scan: int = 0, flags: int = 0) -> None:
    """发送单个键盘事件。"""
    inp = INPUT(
        type=INPUT_KEYBOARD,
        union=_INPUTUNION(
            ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
        ),
    )
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def send_unicode_text(text: str, press_enter: bool = False, char_delay: float = 0.012) -> int:
    """把文本逐字符注入到前台窗口，可选末尾补一个回车。返回注入字符数。"""
    if not text:
        return 0
    for ch in text:
        scan = ord(ch)
        _send_key_event(scan=scan, flags=KEYEVENTF_UNICODE)
        _send_key_event(scan=scan, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        time.sleep(char_delay)
    if press_enter:
        _send_key_event(vk=VK_RETURN)
        _send_key_event(vk=VK_RETURN, flags=KEYEVENTF_KEYUP)
    return len(text)


def _enum_windows() -> list:
    """枚举所有顶层窗口句柄。"""
    hwnds: list = []

    def _cb(hwnd, _lparam):
        hwnds.append(hwnd)
        return True

    _user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return hwnds


def _window_process_name(hwnd) -> Optional[str]:
    """窗口所属进程的 exe 文件名（小写），失败返回 None。"""
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = _user32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(ctypes.sizeof(buf))
        if _user32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        _user32.CloseHandle(h)
    return None


def find_game_windows() -> list:
    """找到游戏的所有可见顶层窗口（按 exe 名 rustedwarfare 开头匹配）。"""
    result = []
    for hwnd in _enum_windows():
        name = _window_process_name(hwnd)
        if name and name.replace(" ", "").startswith("rustedwarfare"):
            if _user32.IsWindowVisible(hwnd):
                result.append(hwnd)
    return result


def force_foreground(hwnd) -> None:
    """把窗口切到前台（处理 Windows 的前台锁定限制）。"""
    fg = _user32.GetForegroundWindow()
    fg_tid = _user32.GetWindowThreadProcessId(fg, None)
    cur_tid = _user32.GetWindowThreadProcessId(hwnd, None)
    if fg and fg != hwnd and fg_tid != cur_tid:
        _user32.AttachThreadInput(fg_tid, cur_tid, True)
        try:
            _user32.BringWindowToTop(hwnd)
            _user32.SetForegroundWindow(hwnd)
        finally:
            _user32.AttachThreadInput(fg_tid, cur_tid, False)
    else:
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)


def activate_game_window() -> bool:
    """激活游戏窗口并置前台；找不到游戏窗口返回 False。"""
    hwnds = find_game_windows()
    if not hwnds:
        return False
    hwnd = hwnds[0]
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, SW_RESTORE)
    force_foreground(hwnd)
    return True


def restore_window_by_title(title: str) -> bool:
    """按窗口标题找到可见顶层窗口，恢复大小并提到前台（用于热键唤回启动器）。

    返回是否找到窗口。标题匹配用精确比较，避免误伤其他同名窗口。
    """
    found = []

    def _cb(hwnd, _lparam):
        if _user32.IsWindowVisible(hwnd):
            length = _user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value == title:
                    found.append(hwnd)
        return True

    _user32.EnumWindows(WNDENUMPROC(_cb), 0)
    if not found:
        return False
    hwnd = found[0]
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, SW_RESTORE)
    force_foreground(hwnd)
    return True


class HotkeyListener:
    """全局热键监听：RegisterHotKey + GetMessage 消息循环。

    注意：RegisterHotKey 的 hwnd 传 None 时，WM_HOTKEY 只投递到
    RegisterHotKey 所在线程的消息队列，跨线程收不到。因此注册必须
    在监听线程内完成，与 GetMessageW 循环同线程。

    on_press 在监听线程回调，可安全执行轻量逻辑（如 evaluate_js）。
    """

    def __init__(
        self,
        hotkey_id: int = 0x5241,
        modifiers: int = MOD_CONTROL | MOD_ALT,
        vk: int = 0x20,  # VK_SPACE
        on_press: Optional[Callable[[], None]] = None,
    ) -> None:
        self._id = hotkey_id
        self._mods = modifiers | MOD_NOREPEAT
        self._vk = vk
        self._on_press = on_press
        self._thread: Optional[threading.Thread] = None
        self._registered = False
        self._lock = threading.Lock()
        self._reg_event = threading.Event()

    @property
    def running(self) -> bool:
        return self._registered and self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """启动监听线程并在该线程内注册热键；热键被占用返回 False。"""
        if self._registered:
            return True
        if self._thread is not None and self._thread.is_alive():
            return True
        self._reg_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="assistant-hotkey")
        self._thread.start()
        # 注册发生在监听线程内，这里等结果（最多 2 秒）
        self._reg_event.wait(timeout=2.0)
        return self._registered

    def stop(self) -> None:
        """注销热键并结束消息循环。"""
        with self._lock:
            if self._thread is not None and self._registered:
                try:
                    _user32.PostThreadMessageW(self._thread.ident, WM_QUIT, 0, 0)
                    self._thread.join(timeout=1.0)
                except Exception:
                    pass
            if self._registered:
                _user32.UnregisterHotKey(None, self._id)
                self._registered = False
            self._thread = None

    def _run(self) -> None:
        """监听线程入口：注册热键后进入消息循环。"""
        try:
            if not _user32.RegisterHotKey(None, self._id, self._mods, self._vk):
                logger.warning("注册全局热键失败（可能已被其他程序占用）")
                return
            with self._lock:
                self._registered = True
            logger.info("中文输入助手全局热键已注册")
            self._loop()
        finally:
            with self._lock:
                if self._registered:
                    _user32.UnregisterHotKey(None, self._id)
                    self._registered = False
            self._reg_event.set()

    def _loop(self) -> None:
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == self._id:
                try:
                    if self._on_press:
                        self._on_press()
                except Exception as e:
                    logger.warning("热键回调异常：%s", e)
