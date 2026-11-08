"""RW Launcher 入口。

启动流程：
1. 加载配置（config.json，不存在则用默认）
2. 创建 pywebview 无边框窗口，加载前端 dist
3. 注入 Bridge 作为 js_api
4. 注册 closing 事件处理"关闭时最小化/退出"逻辑
5. 启动 GUI 事件循环
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

import webview

# 统一使用绝对包导入：开发模式（from backend.main import ...）与
# PyInstaller 打包（PYZ 中按 backend.bridge 收集）都能正确解析。
from backend.bridge import Bridge
from backend.config import Config
from backend.logger import init_logging
from backend.win32_window import enable_edge_resize

logger = logging.getLogger("cqrwl")


def _exit_kill_game(bridge: "Bridge") -> None:
    """启动器退出时在后台结束游戏进程，不阻塞 GUI 线程。

    closing 回调运行在 GUI 线程，若同步执行 tasklist/taskkill，
    系统繁忙时窗口会卡住数秒到十几秒。这里放入独立线程，
    窗口先关闭，进程在后台完成善后（taskkill 均带超时）。
    """
    try:
        res = bridge.kill_game()
        if res.get("killed"):
            logger.info("启动器退出，已自动结束游戏进程")
    except Exception as e:
        logger.warning("退出时结束游戏进程失败：%s", e)


def _resolve_frontend_url() -> str:
    """定位前端入口。优先使用打包后的 dist，否则回退到 Vite dev server。

    开发模式：设置环境变量 CQRWL_FRONTEND_DEV=1 时强制走 Vite dev server，
    便于在浏览器控制台 / 后端控制台直接查看日志。
    """
    if os.environ.get("CQRWL_FRONTEND_DEV") == "1":
        return "http://localhost:5173"
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        base = meipass
    else:
        base = Path(__file__).resolve().parent.parent

    index_html = base / "frontend" / "dist" / "index.html"
    if index_html.exists():
        return str(index_html)
    # 开发模式：让前端走 Vite dev server
    return "http://localhost:5173"


def main() -> int:
    init_logging()
    logger.info("CQ RWLauncher 启动，frozen=%s", getattr(sys, "frozen", False))

    try:
        # 加载配置
        config = Config()
        logger.info("配置加载完成")
        
        # 初始化桥接器（包含版本管理器）
        bridge = Bridge(config)
        logger.info("桥接器和版本管理器初始化完成")
        
        # 验证版本管理器初始化
        try:
            version_status = bridge.get_versions()
            if version_status.get("ok"):
                logger.info("版本管理器验证成功：远程版本 %d 个，已安装版本 %d 个", 
                           version_status.get("total_remote", 0), 
                           version_status.get("total_installed", 0))
                
                # 检查当前版本
                current_version = version_status.get("current_version")
                if current_version:
                    logger.info("当前版本：%s", current_version)
                else:
                    logger.warning("未配置当前版本，将使用默认版本")
            else:
                logger.warning("版本管理器验证失败：%s", version_status.get("error", "未知错误"))
        except Exception as e:
            logger.error("版本管理器初始化验证失败：%s", e)
            
    except Exception as e:
        logger.error("系统初始化失败：%s", e)
        return 1

    # 窗口初始尺寸来自配置（config.json 的 window 块），
    # 不记忆运行时调整过的窗口大小和位置
    win_cfg = config.get("window") or {}
    try:
        width = int(win_cfg.get("width") or 1280)
        height = int(win_cfg.get("height") or 800)
        logger.info("窗口尺寸：%d x %d", width, height)
    except (TypeError, ValueError):
        width, height = 1280, 800
        logger.warning("窗口配置无效，使用默认尺寸：%d x %d", width, height)

    create_kwargs: dict = dict(
        title="CQ RWLauncher",
        url=_resolve_frontend_url(),
        width=width,
        height=height,
        resizable=True,
        frameless=True,        # 自定义标题栏
        easy_drag=False,        # 不依赖 easy_drag（winforms+edgechromium 上无效），改用 drag_selector
        confirm_close=False,    # 我们自己接管关闭逻辑
        js_api=bridge,          # 暴露给 window.pywebview.api
    )
    
    logger.info("窗口参数配置完成，即将创建窗口")

    try:
        window = webview.create_window(**create_kwargs)
        logger.info("窗口创建成功")
        
        bridge._window = window
        bridge._bind_window_events()  # 绑定最大化 / 还原事件，供标题栏切换状态
        logger.info("窗口事件绑定完成")
        
    except Exception as e:
        logger.error("窗口创建失败：%s", e)
        return 1

    # 无边框窗口边缘拖拽调整大小（与正常软件一致：边缘 8px 可拖拽、
    # 拖动到屏幕顶边最大化、最大化时边缘不可拖拽）。
    # 注意：create_window 只注册窗口对象；pywebview 5.4 的 start(func)
    # 会在后台线程、且真正的 Form 创建之前调用 func，所以这里轮询等待
    # native（WinForms Form）出现后再挂接，超时则放弃。
    def _enable_edge_resize() -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                native = getattr(window, "native", None)
                if native is not None:
                    if enable_edge_resize(native):
                        logger.info("已启用窗口边缘拖拽调整大小")
                    else:
                        logger.warning("启用窗口边缘调整大小失败（SetWindowSubclass 返回 False）")
                    return
            except Exception as e:
                logger.debug("等待窗口句柄中：%s", e)
            time.sleep(0.3)
        logger.warning("等待窗口句柄超时，跳过边缘调整大小")

    # 窗口关闭事件：根据配置同步决策，避免 race
    def on_closing() -> bool:
        try:
            behavior = config.get("close_behavior")
        except Exception:
            behavior = None

        if behavior == "exit":
            # 后台结束游戏进程，立即返回 True 让窗口先关闭，避免 GUI 卡死
            try:
                threading.Thread(
                    target=_exit_kill_game, args=(bridge,), daemon=False, name="exit-kill"
                ).start()
            except Exception as e:
                logger.warning("启动退出善后线程失败：%s", e)
            return True  # 允许直接关闭
        if behavior == "minimize":
            try:
                window.minimize()
            except Exception:
                pass
            return False  # 取消关闭

        # "ask" / None / 其他值：通知前端弹窗询问。
        # 弹窗里用户选择后，前端会再调 set_close_behavior + close_window
        try:
            window.evaluate_js(
                "window.__rw && window.__rw.onCloseAttempt && window.__rw.onCloseAttempt();"
            )
        except Exception:
            pass
        return False  # 取消关闭

    window.events.closing += on_closing

    # GUI启动前最终检查：确认版本管理器功能就绪
    try:
        current_version = bridge.get_current_version()
        logger.info("GUI启动准备完成，当前版本：%s", current_version or "未配置")
    except Exception as e:
        logger.error("GUI启动前版本检查异常：%s", e)

    # 优先使用 Edge WebView2（pywebview 6.x 默认在某些系统上回退到 WinForms，
    # 容易因 pythonnet/.NET 异常崩溃）。
    gui_backend = "edgechromium"
    try:
        webview.start(gui=gui_backend, debug=False, func=_enable_edge_resize)
    except Exception as e:
        # 退回 WinForms（兼容老系统 / 无 WebView2 运行时）
        logger.warning("Edge WebView2 启动失败，尝试 WinForms 后端：%s", e)
        try:
            webview.start(gui="winforms", debug=False, func=_enable_edge_resize)
        except Exception as e2:
            logger.error("所有后端均启动失败：%s", e2)
            logger.error(
                "提示：若系统为 Windows 10 1803 以下 / 无 WebView2 Runtime，"
                "请安装 Edge WebView2 Runtime 后重试。"
            )
            raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
