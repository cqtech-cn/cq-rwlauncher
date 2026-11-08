"""FRP 客户端封装。

负责：
  1. 解析/写入 frpc.ini 配置（TOML 格式，frp 0.50+ 标准）
  2. 后台启动/停止 frpc.exe 子进程
  3. 监控 frpc 进程状态、收集最近日志
  4. 给上层（Bridge）提供高层 API

设计要点：
  - frpc.exe 通过 subprocess.Popen 启动，独立进程组
  - 启动器退出时不主动杀 frpc（游戏可能还要用隧道，主人自己决定）
  - 同一时间只允许一个 frpc 实例（防止端口冲突）
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# 默认值
DEFAULT_FRPC = {
    "serverAddr": "",
    "serverPort": 7000,
}
DEFAULT_PROXY = {
    "name": "rw-game",
    "type": "tcp",
    "localIP": "127.0.0.1",
    "localPort": 5123,
}
DEFAULT_AUTH_TOKEN = ""  # 服务端如开了 token 校验才需要


@dataclass
class FrpConfig:
    """frp 配置（启动器侧）—— 转 TOML 后写入 frpc.ini"""

    enabled: bool = False          # 启动时是否自动启动 frpc
    server_addr: str = DEFAULT_FRPC["serverAddr"]
    server_port: int = DEFAULT_FRPC["serverPort"]
    auth_token: str = DEFAULT_AUTH_TOKEN
    proxy_name: str = DEFAULT_PROXY["name"]
    proxy_type: str = DEFAULT_PROXY["type"]
    local_ip: str = DEFAULT_PROXY["localIP"]
    local_port: int = DEFAULT_PROXY["localPort"]
    # 自定义 frpc 路径（留空则用 binaries/frpc/frpc.exe）
    frpc_path: str = ""

    def to_ini(self) -> str:
        """序列化为 frp 0.50+ 标准的 TOML 格式。"""
        lines = [
            f'serverAddr = "{self.server_addr}"',
            f'serverPort = {int(self.server_port)}',
        ]
        if self.auth_token:
            lines.append('auth.method = "token"')
            lines.append(f'auth.token = "{self.auth_token}"')
        lines.append('')
        lines.append('[[proxies]]')
        lines.append(f'name = "{self.proxy_name}"')
        lines.append(f'type = "{self.proxy_type}"')
        lines.append(f'localIP = "{self.local_ip}"')
        lines.append(f'localPort = {int(self.local_port)}')
        lines.append('')
        return '\n'.join(lines)


@dataclass
class FrpStatus:
    """当前 frp 运行状态。"""

    installed: bool = False            # frpc.exe 是否存在
    frpc_path: str = ""                # 实际使用的 frpc.exe 路径
    running: bool = False              # 是否正在运行
    pid: int = 0                       # 进程 PID
    config_path: str = ""              # 当前 frpc.ini 路径
    last_error: str = ""               # 最近一次错误
    started_at: float = 0.0            # 启动时间戳
    last_log_lines: list[str] = field(default_factory=list)  # 最近日志


def _resolve_frpc_path(custom: str = "") -> Optional[Path]:
    """解析 frpc.exe 实际路径。优先级：custom > binaries/frpc/frpc.exe"""
    if custom:
        p = Path(custom)
        if p.is_file():
            return p
        return None
    # 自动定位：启动器根目录/binaries/frpc/frpc.exe
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    candidate = base / "binaries" / "frpc" / "frpc.exe"
    if candidate.is_file():
        return candidate
    return None


def _resolve_ini_path(frpc: Path) -> Path:
    """frpc.ini 与 frpc.exe 同目录。"""
    return frpc.parent / "frpc_cqrwl.ini"


class FrpManager:
    """frp 客户端进程管理器（单例风格，全局共享一个实例）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._log_tail: list[str] = []
        self._log_max = 50
        self._stdout_thread: Optional[threading.Thread] = None

    def write_ini(self, cfg: FrpConfig, ini_path: Path) -> bool:
        """把 FrpConfig 写入 frpc.ini。"""
        try:
            ini_path.parent.mkdir(parents=True, exist_ok=True)
            ini_path.write_text(cfg.to_ini(), encoding="utf-8")
            logger.info("frpc.ini 已写入：%s", ini_path)
            return True
        except Exception as e:
            logger.error("写入 frpc.ini 失败：%s", e)
            return False

    # ----- 启停 -----
    def start(self, cfg: FrpConfig) -> dict:
        """启动 frpc.exe。

        Returns:
            {"ok": bool, "pid": int, "error": str}
        """
        with self._lock:
            # 已运行则直接返回
            if self._proc is not None and self._proc.poll() is None:
                return {"ok": True, "pid": self._proc.pid, "already_running": True}

            frpc = _resolve_frpc_path(cfg.frpc_path)
            if frpc is None:
                msg = f"找不到 frpc.exe（自定义路径={cfg.frpc_path!r} 或 binaries/frpc/frpc.exe 不存在）"
                logger.warning(msg)
                return {"ok": False, "error": msg}

            ini = _resolve_ini_path(frpc)
            if not self.write_ini(cfg, ini):
                return {"ok": False, "error": "frpc.ini 写入失败"}

            try:
                # CREATE_NEW_PROCESS_GROUP 让 frpc 不受启动器 Ctrl+C 影响
                # CREATE_NO_WINDOW 隐藏 frpc 黑窗
                creationflags = 0
                if os.name == "nt":
                    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | \
                                    getattr(subprocess, "CREATE_NO_WINDOW", 0)

                self._log_tail.clear()
                self._proc = subprocess.Popen(
                    [str(frpc), "-c", str(ini)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=str(frpc.parent),
                    creationflags=creationflags,
                )
                self._stdout_thread = threading.Thread(
                    target=self._tail_output,
                    args=(self._proc,),
                    daemon=True,
                    name="frpc-stdout-tail",
                )
                self._stdout_thread.start()
                logger.info("frpc 已启动，pid=%d，配置=%s", self._proc.pid, ini)
                return {"ok": True, "pid": self._proc.pid, "frpc_path": str(frpc), "ini_path": str(ini)}
            except Exception as e:
                logger.error("启动 frpc 失败：%s", e)
                return {"ok": False, "error": str(e)}

    def stop(self) -> dict:
        """停止 frpc.exe（不强制杀，按 frpc 自身清理逻辑退出）。"""
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._proc = None
                return {"ok": True, "already_stopped": True}
            try:
                if os.name == "nt":
                    # Windows：用 taskkill 优雅结束进程树
                    subprocess.run(
                        ["taskkill", "/T", "/PID", str(self._proc.pid), "/F"],
                        capture_output=True, timeout=5,
                    )
                else:
                    self._proc.send_signal(signal.SIGTERM)
                    try:
                        self._proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
                logger.info("frpc 已停止，pid=%d", self._proc.pid)
            except Exception as e:
                logger.warning("停止 frpc 失败：%s", e)
                return {"ok": False, "error": str(e)}
            finally:
                self._proc = None
            return {"ok": True}

    def status(self, cfg: FrpConfig) -> FrpStatus:
        """查询当前 frp 状态（含 frpc.exe 路径检测 + 进程运行状态）。"""
        frpc = _resolve_frpc_path(cfg.frpc_path)
        st = FrpStatus(
            installed=frpc is not None,
            frpc_path=str(frpc) if frpc else "",
        )
        # 写一份 ini 给 UI 看（即使没运行也方便看当前配置）
        if frpc:
            ini = _resolve_ini_path(frpc)
            st.config_path = str(ini)
        # 检查进程
        with self._lock:
            if self._proc is not None:
                rc = self._proc.poll()
                if rc is None:
                    st.running = True
                    st.pid = self._proc.pid
                else:
                    # 进程已退出，清理
                    self._proc = None
                    st.last_error = f"frpc 已退出，returncode={rc}"
        st.last_log_lines = list(self._log_tail)
        return st

    # ----- 内部 -----
    def _tail_output(self, proc: subprocess.Popen) -> None:
        """后台线程：把 frpc stdout/stderr 收进环形 buffer。"""
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                if not raw:
                    break
                try:
                    line = raw.decode("utf-8", errors="replace").rstrip()
                except Exception:
                    line = repr(raw)
                self._log_tail.append(line)
                if len(self._log_tail) > self._log_max:
                    self._log_tail = self._log_tail[-self._log_max:]
                # 控制台也回显（启动器 logger）
                if "[WARN]" in line or "[ERR]" in line or "fail" in line.lower():
                    logger.warning("frpc: %s", line)
                else:
                    logger.debug("frpc: %s", line)
        except Exception as e:
            logger.debug("frpc stdout tail 结束：%s", e)


# 模块级单例
_manager: Optional[FrpManager] = None


def get_manager() -> FrpManager:
    """获取全局 FrpManager 实例（懒加载）。"""
    global _manager
    if _manager is None:
        _manager = FrpManager()
    return _manager
