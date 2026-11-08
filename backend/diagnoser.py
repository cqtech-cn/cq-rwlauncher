"""游戏诊断与进程监听模块。

后台监听线程只负责感知游戏进程退出，并在退出时触发外部回调
（如游戏退出自动云备份），不再做任何异常自动弹窗告警。

手动全项诊断 run_diagnosis() 保留，由用户在服务页主动运行，
一键生成包含游戏文件、进程、存档、日志、运行库、服务连通性等项目的报告。
"""
from __future__ import annotations

import ctypes
import logging
import re
import shutil
import subprocess
import threading
import time
import winreg
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from backend.launcher import GameLauncher

logger = logging.getLogger(__name__)

# 日志错误关键字（严格匹配，避免把正常日志误报为异常；手动诊断时使用）
_LOG_ERROR_RE = re.compile(
    r"(?i)(\bexception\b|\bfatal\b|\bcrash\b|out of memory|access violation|"
    r"stack overflow|not enough memory|\bassert\b|missing file|"
    r"\bunable to (load|find|open|create)\b|\bfailed to (load|initialize|open)\b|"
    r"\bjni\b|out of range|gl context)"
)

# 轮询间隔（秒）
POLL_INTERVAL = 3.0
# 启动后等待游戏进程出现的最大秒数，超时静默结束监听
LAUNCH_WAIT_TIMEOUT = 60.0
# 内存占用偏高阈值（MB，游戏进程工作集合计，手动诊断时给出提示）
MEM_HIGH_MB = 2500.0

# 常见游戏日志文件名（游戏根目录 / 我的文档下的游戏数据文件夹）
_LOG_FILE_NAMES = ("log.txt", "logfile.txt", "logs.txt", "crashes.txt", "error.log", "log.log")

# 我的文档下游戏数据文件夹的候选名（兼容 Steam 正版与老版本便携版）
_GAME_DATA_FOLDER_NAMES = ("Rusted Warfare", "Rust Warfare", "rustedWarfare")

# 存档 / 日志目录在我的文档下的候选父目录（兼容 OneDrive 文档重定向）
_DOC_BASE_CANDIDATES = ("Documents", "OneDrive/Documents", "OneDrive/文档")


# --------------------------------------------------------------
# 游戏进程检测（无第三方依赖）
# --------------------------------------------------------------

def game_procs() -> list[tuple[str, int]]:
    """返回当前运行的游戏进程 (映像名, pid) 列表；检测失败返回空列表。"""
    try:
        r = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=4,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return []
    out: list[tuple[str, int]] = []
    for line in r.stdout.splitlines():
        parts = line.split(",")
        if len(parts) < 2:
            continue
        name = parts[0].strip().strip('"')
        if name.lower().replace(" ", "").startswith("rustedwarfare"):
            try:
                pid = int(parts[1].strip().strip('"'))
            except ValueError:
                continue
            out.append((name, pid))
    return out


def pid_alive(pid: int) -> bool:
    """进程是否存活（按 PID 直读，供 Java 版等无法按名匹配的场景使用）。

    查询失败时保守返回 True（存活），避免把一次 tasklist 抖动误判成游戏退出；
    游戏真正退出后下一次轮询会正确返回 False。
    """
    try:
        r = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=4,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return True
    for line in r.stdout.splitlines():
        parts = line.split(",")
        if len(parts) < 2:
            continue
        name = parts[0].strip().strip('"')
        if name.upper().startswith("INFO"):
            continue  # "INFO: No tasks are running ..." 不是进程行
        try:
            if int(parts[1].strip().strip('"')) == pid:
                return True
        except ValueError:
            continue
    return False


def _pid_windows(pid: int) -> list[int]:
    """枚举属于指定进程的所有顶层窗口句柄。"""
    hwnds: list[int] = []
    try:
        _user32 = ctypes.windll.user32

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd: int, _lparam: int) -> bool:
            wpid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid:
                hwnds.append(hwnd)
            return True

        _user32.EnumWindows(_cb, 0)
    except Exception:
        return []
    return hwnds


def _window_responding(hwnd: int) -> bool:
    """窗口是否响应消息（False 表示 Not Responding / 卡死）。"""
    try:
        return bool(ctypes.windll.user32.IsHungAppWindow(hwnd) == 0)
    except Exception:
        return True  # 无法判断时按正常处理


def process_hung(pid: int) -> bool:
    """进程主窗口是否卡死（无窗口的进程无法判断，返回 False）。"""
    hwnds = _pid_windows(pid)
    if not hwnds:
        return False
    return not any(_window_responding(hwnd) for hwnd in hwnds)


# --------------------------------------------------------------
# 进程资源占用读取（无第三方依赖，ctypes 调 Windows API）
# --------------------------------------------------------------

class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def process_mem_kb(pid: int) -> Optional[int]:
    """进程工作集内存（KB）；读取失败返回 None。"""
    try:
        _kernel32 = ctypes.windll.kernel32
        _psapi = ctypes.windll.psapi
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        h = _kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not h:
            return None
        try:
            pmc = _ProcessMemoryCounters()
            pmc.cb = ctypes.sizeof(_ProcessMemoryCounters)
            if _psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                return pmc.WorkingSetSize // 1024
        finally:
            _kernel32.CloseHandle(h)
    except Exception:
        return None
    return None


# --------------------------------------------------------------
# 游戏数据目录 / 日志 / 存档 定位
# --------------------------------------------------------------

def game_data_dirs(game_root: Path) -> list[Path]:
    """游戏数据目录候选：游戏根目录 + 我的文档下的游戏数据文件夹。"""
    home = Path.home()
    dirs = [Path(game_root)]
    for rel in _DOC_BASE_CANDIDATES:
        base = home / rel
        for name in _GAME_DATA_FOLDER_NAMES:
            d = base / name
            if d.is_dir():
                dirs.append(d)
    # 去重保序
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def find_log_files(game_root: Path) -> list[Path]:
    """扫描游戏数据目录，收集日志文件列表。"""
    found: list[Path] = []
    seen: set[str] = set()
    for base in game_data_dirs(game_root):
        try:
            children = list(base.iterdir())
        except OSError:
            continue
        for p in children:
            try:
                if not p.is_file():
                    continue
                low = p.name.lower()
                if low in _LOG_FILE_NAMES or low.endswith(".log"):
                    key = str(p).lower()
                    if key not in seen:
                        seen.add(key)
                        found.append(p)
            except OSError:
                continue
    return found


def find_saves_dirs(game_root: Path) -> list[Path]:
    """存档目录候选（仅返回已存在的）：游戏根目录/saves + 我的文档下的游戏数据文件夹/saves。"""
    home = Path.home()
    candidates = [Path(game_root) / "saves"]
    for rel in _DOC_BASE_CANDIDATES:
        base = home / rel
        for name in _GAME_DATA_FOLDER_NAMES:
            candidates.append(base / name / "saves")
    seen: set[str] = set()
    out: list[Path] = []
    for d in candidates:
        key = str(d).lower()
        if key in seen or not d.is_dir():
            continue
        seen.add(key)
        out.append(d)
    return out


def iter_save_files(d: Path):
    """递归列出存档目录下的文件（跳过隐藏文件与 Office 临时文件）。"""
    for p in sorted(d.rglob("*")):
        if p.is_file() and not p.name.startswith(".") and not p.name.startswith("~$"):
            yield p


def resolve_restore_root(entry: dict, game_root: Path) -> Optional[Path]:
    """根据备份条目信息解析恢复目标根目录。

    - location 为"游戏目录"时固定回游戏根目录/saves
    - location 为"我的文档"时按现存目录依次匹配
    - 兜底使用备份时记录的原始绝对路径（须包含 saves 段，防止路径穿越）
    """
    loc = entry.get("location")
    if loc == "游戏目录":
        return Path(game_root) / "saves"
    if loc == "我的文档":
        for d in find_saves_dirs(game_root):
            if str(d).lower() != str(Path(game_root) / "saves").lower():
                return d
    origin = entry.get("origin")
    if origin and isinstance(origin, str):
        op = Path(origin)
        if "saves" in [x.lower() for x in op.parts]:
            return op
    return None


# 游戏进程退出监听线程

class GameMonitor(threading.Thread):
    """后台监听线程：只负责感知游戏进程退出并触发 on_exit 回调。

    历史上的闪退 / 卡死 / 日志 / 资源（CPU、内存）四类自动告警已按需求移除，
    保留本线程的唯一原因是游戏退出后要自动执行存档云备份。
    """

    def __init__(
        self,
        launcher: GameLauncher,
        on_exit: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(name="game-monitor", daemon=True)
        self._launcher = launcher
        self._on_exit = on_exit  # 游戏进程退出（正常 / 异常）后的回调
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()
        self._active = False
        self._start_time = 0.0
        # 游戏进程是否已经出现过（区分"等待启动"与"运行中"两个阶段）
        self._seen = False
        # Java 版：按启动返回的进程 PID 直读存活，替代按名匹配 game_procs
        self._watch_pid: Optional[int] = None

    def bind_launcher(self, launcher: GameLauncher) -> None:
        """切换游戏版本后重新绑定启动器定位对象。"""
        self._launcher = launcher

    @property
    def running(self) -> bool:
        with self._lock:
            return self._active

    def begin(self, watch_pid: Optional[int] = None) -> None:
        """开始监听（游戏启动成功后调用）。若已在监听则重置。

        Args:
            watch_pid: Java 版启动时传入游戏进程 PID，此后按 PID 直读存活；
                       原生 exe 不传，沿用 game_procs 按名匹配。
        """
        with self._lock:
            self._active = True
            self._start_time = time.time()
            self._watch_pid = watch_pid
            self._seen = False
            self._stop_evt.clear()
        if not self.is_alive():
            self.start()

    def stop(self) -> None:
        """停止监听（用户主动结束游戏 / 启动器退出，不触发退出回调）。"""
        with self._lock:
            self._active = False
        self._stop_evt.set()

    def run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                self._poll()
            except Exception:
                logger.exception("游戏进程监听轮询异常")
            self._stop_evt.wait(POLL_INTERVAL)

    def _alive(self) -> bool:
        """游戏进程是否存活：Java 版按 PID，原生 exe 按映像名。"""
        if self._watch_pid is not None:
            return pid_alive(self._watch_pid)
        return bool(game_procs())

    def _poll(self) -> None:
        if not self.running:
            return
        alive = self._alive()

        # 等待游戏启动阶段：拉起游戏到进程出现可能有延迟
        if not self._seen:
            if alive:
                self._seen = True
                logger.info("游戏进程出现，开始监听退出")
            elif time.time() - self._start_time > LAUNCH_WAIT_TIMEOUT:
                # 超时仍未见进程，静默结束监听，不弹窗
                self.stop()
            return

        if alive:
            return

        # 游戏已退出：记录日志并触发外部回调（如云端自动备份）
        logger.info(
            "游戏进程已退出（运行 %d 秒）",
            int(time.time() - self._start_time),
        )
        if self._on_exit is not None:
            try:
                self._on_exit()
            except Exception:
                logger.exception("游戏退出回调执行失败")
        self.stop()


# --------------------------------------------------------------
# 手动全项诊断
# --------------------------------------------------------------

def _cfg(config: Any, key: str, default: Any = None) -> Any:
    """从 Config 对象或 dict 中安全取值（兼容两种配置载体）。"""
    if config is None:
        return default
    getter = getattr(config, "get", None)
    if callable(getter):
        return getter(key, default)
    if isinstance(config, dict):
        return config.get(key, default)
    return default


def _url_reachable(url: str, timeout: float = 4.0) -> bool:
    """HTTP(S) 地址是否可达（能收到任何 HTTP 响应即视为服务在线）。"""
    if not url:
        return False
    try:
        requests.get(url, timeout=timeout, allow_redirects=True)
        return True
    except Exception:
        return False


def vc_runtime_installed() -> bool:
    """是否已安装 VC++ 2015-2022 运行库（x64，查注册表）。"""
    paths = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"),
    )
    for hive, key_path in paths:
        try:
            with winreg.OpenKey(hive, key_path) as k:
                if winreg.QueryValueEx(k, "Installed")[0]:
                    return True
        except OSError:
            continue
    return False


def run_diagnosis(
    launcher: GameLauncher,
    config: Any = None,
) -> dict:
    """手动全项诊断，返回诊断报告。"""
    items: list[dict] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. 游戏文件
    exe = launcher.exe_path
    java_jar = launcher.java_jar_path
    if exe.is_file():
        size_mb = exe.stat().st_size / 1024 / 1024
        items.append({
            "id": "game", "label": "游戏文件", "status": "ok",
            "message": f"已找到 {exe.name}（{size_mb:.1f} MB）",
        })
    elif java_jar is not None:
        items.append({
            "id": "game", "label": "游戏文件", "status": "ok",
            "message": f"未找到原生可执行文件，将使用 Java 版启动（{java_jar.name}）",
        })
    else:
        items.append({
            "id": "game", "label": "游戏文件", "status": "error",
            "message": f"未找到游戏主程序（exe / jar）：{exe}，请在「路径设置」中检查游戏安装目录",
        })

    # 2. 进程状态
    procs = game_procs()
    if procs:
        hung = [pid for _name, pid in procs if process_hung(pid)]
        if hung:
            items.append({
                "id": "process", "label": "进程状态", "status": "warn",
                "message": f"检测到 {len(procs)} 个游戏进程，其中 {len(hung)} 个无响应",
            })
        else:
            items.append({
                "id": "process", "label": "进程状态", "status": "ok",
                "message": f"游戏正在运行（{len(procs)} 个进程）",
            })
    else:
        items.append({
            "id": "process", "label": "进程状态", "status": "info",
            "message": "游戏当前未运行",
        })

    # 3. 存档目录
    saves_dirs = find_saves_dirs(launcher.game_root)
    if saves_dirs:
        total = sum(1 for d in saves_dirs for _ in iter_save_files(d))
        items.append({
            "id": "saves", "label": "存档目录", "status": "ok",
            "message": f"找到 {len(saves_dirs)} 个存档目录，共 {total} 个存档文件",
        })
    else:
        items.append({
            "id": "saves", "label": "存档目录", "status": "info",
            "message": "未找到存档目录（游戏未运行过或游戏路径有误）",
        })

    # 4. 日志文件
    logs = find_log_files(launcher.game_root)
    if logs:
        items.append({
            "id": "logs", "label": "日志文件", "status": "ok",
            "message": "；".join(str(p) for p in logs),
        })
    else:
        items.append({
            "id": "logs", "label": "日志文件", "status": "info",
            "message": "未找到游戏日志文件",
        })

    # 5. 日志错误
    error_lines: list[str] = []
    for p in logs:
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for ln in lines:
            if _LOG_ERROR_RE.search(ln):
                error_lines.append(ln.strip()[:120])
    if error_lines:
        items.append({
            "id": "log_errors", "label": "日志错误", "status": "warn",
            "message": f"日志中发现 {len(error_lines)} 条异常记录（最近一条：{error_lines[-1]}）",
        })
    else:
        items.append({
            "id": "log_errors", "label": "日志错误", "status": "ok",
            "message": "日志未发现明显错误",
        })

    # 6. 磁盘空间
    try:
        disk = shutil.disk_usage(launcher.game_root.anchor or launcher.game_root)
        free_gb = disk.free / 1024 ** 3
        if free_gb < 0.5:
            items.append({
                "id": "disk", "label": "磁盘空间", "status": "warn",
                "message": f"游戏所在盘剩余空间不足：{free_gb:.1f} GB",
            })
        else:
            items.append({
                "id": "disk", "label": "磁盘空间", "status": "ok",
                "message": f"游戏所在盘剩余 {free_gb:.1f} GB",
            })
    except OSError:
        items.append({
            "id": "disk", "label": "磁盘空间", "status": "info",
            "message": "无法读取磁盘空间",
        })

    # 7. 游戏目录完整性（主程序旁应有关键伴生文件：jar 包 + 运行库目录）
    game_root = launcher.game_root
    missing_parts = []
    libs_ok = (game_root / "libs").is_dir() or (game_root / "lib").is_dir()
    if game_root.is_dir():
        if launcher.exe_path.is_file():
            # 原生 exe 版：不强制 jar 伴生（多版本共存目录可能只有 exe）
            if not libs_ok:
                missing_parts.append("运行库目录（libs / lib）")
        elif launcher.java_jar_path is not None:
            if not libs_ok:
                missing_parts.append("运行库目录（libs）")
        else:
            missing_parts.append("游戏主程序（exe / jar）")
    else:
        missing_parts.append("游戏根目录不存在")
    if missing_parts:
        items.append({
            "id": "game_files", "label": "游戏目录完整性", "status": "warn",
            "message": f"游戏根目录缺少伴生文件：{'、'.join(missing_parts)}，游戏可能无法正常启动",
        })
    else:
        items.append({
            "id": "game_files", "label": "游戏目录完整性", "status": "ok",
            "message": "游戏关键伴生文件齐全",
        })

    # 8.5. Java 运行环境（简体中文增强版用 jar 启动时需要 JRE）
    if java_jar is not None:
        jst = launcher.java_status()
        if jst.get("needs_install"):
            items.append({
                "id": "java_runtime", "label": "Java 运行环境", "status": "warn",
                "message": (
                    f"Java 版（{java_jar.name}）需要 JRE，但游戏目录与本机均无可用 Java；"
                    f"启动时将尝试自动从 Adoptium 下载 JRE 安装到 {jst.get('install_dir')}"
                ),
            })
        else:
            _src_label = {
                "bundled64": "游戏自带 64 位 JRE",
                "bundled32": "游戏自带 32 位 JRE",
                "system": "系统 Java",
            }.get(jst.get("java_source"), jst.get("java_source") or "未知来源")
            items.append({
                "id": "java_runtime", "label": "Java 运行环境", "status": "ok",
                "message": (
                    f"Java 版就绪：入口 {java_jar.name}，"
                    f"使用{_src_label}（Java {jst.get('java_major') or '?'}）"
                ),
            })

    # 9. 游戏版本清单连通性（下载地址由清单中的 download_url 提供）
    gv_cfg = _cfg(config, "game_version_list", {})
    list_url = gv_cfg.get("url", "") if isinstance(gv_cfg, dict) else ""
    if list_url:
        if _url_reachable(list_url):
            items.append({
                "id": "download", "label": "版本清单连通性", "status": "ok",
                "message": f"游戏版本清单可达：{list_url}",
            })
        else:
            items.append({
                "id": "download", "label": "版本清单连通性", "status": "error",
                "message": f"游戏版本清单不可达：{list_url}，下载 / 重装游戏会失败",
            })

    # 10. 配套服务连通性
    for name in ("room_service", "account", "health_service"):
        svc = _cfg(config, name)
        if not isinstance(svc, dict):
            continue
        base = svc.get("base_url") or ""
        if not base:
            continue
        if _url_reachable(base):
            items.append({
                "id": f"svc_{name}", "label": f"服务连通性（{name}）", "status": "ok",
                "message": f"{base} 可达",
            })
        else:
            items.append({
                "id": f"svc_{name}", "label": f"服务连通性（{name}）", "status": "warn",
                "message": f"{base} 当前不可达（可能维护中或本机未启动）",
            })

    # 11. 临时目录残留
    tmp_dir = launcher.game_dir.parent / "_rw_tmp"
    if tmp_dir.is_dir():
        leftovers = [p for p in tmp_dir.iterdir() if p.is_file()]
        if leftovers:
            total_mb = sum(p.stat().st_size for p in leftovers) / 1024 / 1024
            items.append({
                "id": "tmp_leftovers", "label": "临时文件残留", "status": "info",
                "message": f"发现 {len(leftovers)} 个残留临时文件（约 {total_mb:.1f} MB）：{tmp_dir}，可手动删除",
            })
        else:
            items.append({
                "id": "tmp_leftovers", "label": "临时文件残留", "status": "ok",
                "message": "临时目录干净",
            })

    # 12. VC++ 运行库
    if vc_runtime_installed():
        items.append({
            "id": "vc_runtime", "label": "VC++ 运行库", "status": "ok",
            "message": "已安装 VC++ 2015-2022 运行库（x64）",
        })
    else:
        items.append({
            "id": "vc_runtime", "label": "VC++ 运行库", "status": "warn",
            "message": "未检测到 VC++ 2015-2022 运行库，游戏可能无法启动，建议安装最新版",
        })

    # 13. 进程资源占用（游戏运行时）
    if procs:
        total_mb = sum((process_mem_kb(pid) or 0) for _name, pid in procs) / 1024
        res_status = "warn" if total_mb >= MEM_HIGH_MB else "ok"
        items.append({
            "id": "process_resources", "label": "进程资源占用", "status": res_status,
            "message": f"游戏进程共占用内存 {total_mb:.0f} MB"
                       + ("，持续偏高，注意保存进度" if res_status == "warn" else ""),
        })

    errors = [it for it in items if it["status"] == "error"]
    warns = [it for it in items if it["status"] == "warn"]
    if errors:
        summary = f"发现 {len(errors)} 项错误、{len(warns)} 项警告"
    elif warns:
        summary = f"发现 {len(warns)} 项警告，未发现致命错误"
    else:
        summary = "各项检查均正常"

    return {"checked_at": now, "items": items, "summary": summary}
