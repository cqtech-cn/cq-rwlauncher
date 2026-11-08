"""无边框窗口边缘拖拽调整大小。

pywebview 的 frameless 窗口把 WinForms 的 FormBorderStyle 设成 None，
边缘没有系统调整大小的热区。这里用 SetWindowSubclass 挂一个 WNDPROC，
在 WM_NCHITTEST 里把窗口边缘 8px 命中区映射成 HTLEFT/HTRIGHT/HTTOP/
HTBOTTOM 等，系统即恢复边缘拖拽调整大小，并保留 Aero Snap（拖动到
屏幕顶部最大化 / 边缘分屏）。

最大化状态下返回 HTCLIENT：与正常软件一致，最大化时边缘不可拖拽。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

WM_NCHITTEST = 0x0084
HTCLIENT = 1
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

_SUBCLASS_ID = 0x5257  # 'RW'

_user32 = ctypes.windll.user32
# SetWindowSubclass / DefSubclassProc 属于 ComCtl32 v6，不是 user32
_comctl32 = ctypes.windll.comctl32

# Python 3.12+ 的 wintypes 不再提供 LRESULT（LONG_PTR），这里手动定义
LRESULT = ctypes.c_ssize_t

SUBCLASSPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

# 提前声明签名（后续 enable_edge_resize 里复用）
_comctl32.SetWindowSubclass.argtypes = [
    wintypes.HWND,
    SUBCLASSPROC,
    ctypes.c_uint,
    ctypes.c_uint,
]
_comctl32.SetWindowSubclass.restype = wintypes.BOOL
_comctl32.DefSubclassProc.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
_comctl32.DefSubclassProc.restype = LRESULT


def _hit_test(hwnd: int, x: int, y: int) -> int:
    """根据屏幕坐标判断命中区域；最大化时不响应边缘。"""
    if _user32.IsZoomed(hwnd):
        return HTCLIENT
    rect = wintypes.RECT()
    _user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))
    # 边缘热区宽度，按 DPI 缩放（125%/150% 下保持手感一致）
    try:
        dpi = int(_user32.GetDpiForWindow(ctypes.c_void_p(hwnd)))
    except Exception:
        dpi = 96
    border = max(6, round(8 * dpi / 96))

    left = x < rect.left + border
    right = x >= rect.right - border
    top = y < rect.top + border
    bottom = y >= rect.bottom - border

    if top and left:
        return HTTOPLEFT
    if top and right:
        return HTTOPRIGHT
    if bottom and left:
        return HTBOTTOMLEFT
    if bottom and right:
        return HTBOTTOMRIGHT
    if left:
        return HTLEFT
    if right:
        return HTRIGHT
    if top:
        return HTTOP
    if bottom:
        return HTBOTTOM
    return HTCLIENT


@SUBCLASSPROC
def _subclass_proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
    if msg == WM_NCHITTEST:
        raw = ctypes.c_long(lparam).value
        x = raw & 0xFFFF
        y = (raw >> 16) & 0xFFFF
        if x >= 0x8000:
            x -= 0x10000
        if y >= 0x8000:
            y -= 0x10000
        region = _hit_test(int(hwnd), x, y)
        if region != HTCLIENT:
            return region
    return _comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)


def enable_edge_resize(native) -> bool:
    """给无边框窗口挂上边缘拖拽调整大小能力；失败返回 False。

    SetWindowSubclass 必须由窗口所属（GUI）线程调用，否则静默返回
    FALSE。这里用 WinForms 的 Control.Invoke 把调用 marshal 到 GUI
    线程执行。
    """
    if native is None:
        return False
    result: list = []

    def _do() -> None:
        try:
            hwnd = int(native.Handle.ToInt64())
            ok = _comctl32.SetWindowSubclass(
                ctypes.c_void_p(hwnd), _subclass_proc, _SUBCLASS_ID, 0
            )
            result.append(bool(ok))
        except Exception:
            result.append(False)

    try:
        import System
        native.Invoke(System.Action(_do))
    except Exception:
        # Invoke 不可用（如非 WinForms 环境）时退化直调
        _do()
    return bool(result and result[0])
