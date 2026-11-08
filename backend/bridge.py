"""pywebview 桥接层：把 Python 能力暴露给前端 JS。

所有方法都通过 `window.pywebview.api.<method>(...)` 被前端调用。
- 短任务（搜索、读配置）直接同步返回。
- 长任务（下载）立即返回 task_id，由后台线程完成，进度通过
  `window.evaluate_js` 主动推送到前端。

⚠️ 实现约束：pywebview 5.4 在 `inject_pywebview` 中会通过
`dir(self)` 遍历 Bridge 实例的所有公共属性，对每个"非可调用且
有 __module__ 属性"的对象递归调用 `get_functions`。
如果这些对象在 pythonnet 互操作链路上，就可能触发
`.NET Rectangle.op_Equality` 等反射错误。
为避免此问题，本类所有不应被前端直接访问的实例属性均使用
下划线前缀，使其在 pywebview 的 `if name.startswith('_'): continue`
分支中被跳过。
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import re
import shutil
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import webview

# 统一使用绝对包导入：开发模式与 PyInstaller 打包都能正确解析。
from backend.config import APP_BUILD_DATE, APP_VERSION, Config
from backend.diagnoser import (
    GameMonitor,
    find_saves_dirs,
    game_data_dirs,
    game_procs,
    iter_save_files,
    pid_alive,
    resolve_restore_root,
    run_diagnosis,
)
from backend.downloader import DownloadManager, TaskStatus
from backend.festival import detect as detect_festival
from backend.frp import DEFAULT_FRPC, FrpConfig, FrpStatus, get_manager as get_frp_manager
from backend.java_runtime import (
    DEFAULT_FEATURE_VERSION,
    JVM_DIR_64,
    cleanup_old_jre,
    download_jre,
    install_jre_zip,
    query_adoptium_jre,
)
from backend.launcher import GameLauncher, JavaRuntimeMissingError
from backend.rtsbox_api import RtsboxAPI, RtsboxAPIError
from backend.version_manager import VersionInfo, VersionManager

logger = logging.getLogger(__name__)


# 前端监听的事件名（通过 window.evaluate_js 派发）
EVT_PROGRESS = "rw:download:progress"
EVT_STATUS = "rw:download:status"
EVT_TOAST = "rw:toast"


def _safe_js_payload(data: Any) -> str:
    """把 Python 数据安全地序列化为 JS 字面量。"""
    return json.dumps(data, ensure_ascii=False)


def _sanitize_folder_name(name: str, max_len: int = 60) -> str:
    """将资源标题转成合法的文件夹名。"""
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip()
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = "untitled"
    return name[:max_len]


# 版本号提取：优先 "vX.X.X"，其次 "X.X.X版"，最后裸 "X.X.X"（至少一位小数）
_VERSION_RE = re.compile(
    r"(?:v\d+(?:\.\d+)+)|(?:\d+\.\d+(?:\.\d+)*\s*版)|(?:\d+\.\d+(?:\.\d+)*)",
    re.IGNORECASE,
)


def _extract_version(title: str) -> str:
    """从资源标题中提取版本号，如 "v1.2.3"、"2.0版"；提取不到返回空串。"""
    if not title:
        return ""
    m = _VERSION_RE.search(title)
    return m.group(0).strip() if m else ""


def _version_tuple(v: str) -> tuple[int, ...]:
    """把 "X.X.X" 类版本号拆成可比较的整数元组（非数字段按 0 计）。"""
    out: list[int] = []
    for part in re.split(r"[._\-]", (v or "").strip()):
        m = re.match(r"\d+", part)
        out.append(int(m.group()) if m else 0)
    return tuple(out)


def _version_gt(a: str, b: str) -> bool:
    """版本号 a 是否大于 b（如 "2.5.0" > "2.4.1"）。"""
    ta, tb = _version_tuple(a), _version_tuple(b)
    n = max(len(ta), len(tb))
    ta += (0,) * (n - len(ta))
    tb += (0,) * (n - len(tb))
    return ta > tb


_ERROR_GUIDES = {
    "10060": {
        "title": "连接超时",
        "desc": "目标主机未在预期时间内响应，通常是服务未启动、网络不通或端口被拦截。",
        "suggest": "请检查服务是否已启动，确认地址和端口是否正确，再重试；如仍失败，可联系开发者 CQFISH（QQ3981491440）。",
    },
    "10061": {
        "title": "连接被拒绝",
        "desc": "目标端口没有监听或服务已关闭，常见于服务未启动、端口错误或防火墙拦截。",
        "suggest": "请确认服务正在运行，检查端口是否正确，以及防火墙/安全软件是否阻止了连接；若仍无法解决，可联系开发者 CQFISH（QQ3981491440）。",
    },
    "401": {
        "title": "未授权",
        "desc": "请求缺少有效凭据，或登录状态已过期。",
        "suggest": "请重新登录账号，检查 Token 是否失效；必要时退出重进或联系开发者 CQFISH（QQ3981491440）。",
    },
    "402": {
        "title": "需要付费 / 访问受限",
        "desc": "该资源或功能要求付费、授权或平台资格。",
        "suggest": "请确认当前账号是否具备访问权限；若为功能受限，请先检查账号状态或联系开发者 CQFISH（QQ3981491440）。",
    },
    "403": {
        "title": "禁止访问",
        "desc": "当前请求被服务器拒绝，通常是权限不足、IP 被限制或访问策略拦截。",
        "suggest": "请确认是否使用了正确账号、正确地址和权限；如遇到访问限制，可稍后重试或联系开发者 CQFISH（QQ3981491440）。",
    },
    "404": {
        "title": "未找到资源",
        "desc": "请求的路径或资源不存在，可能是 URL 错误、服务版本不一致或服务未发布。",
        "suggest": "请检查 URL、接口地址和版本是否匹配；若确认配置正确，可联系开发者 CQFISH（QQ3981491440）排查服务端状态。",
    },
    "429": {
        "title": "请求过于频繁",
        "desc": "当前访问被限流，通常是短时间内触发了过多请求。",
        "suggest": "请稍后再试，降低刷新频率；如果是自动重试造成，请稍作延迟后重试，必要时联系开发者 CQFISH（QQ3981491440）。",
    },
    "500": {
        "title": "服务器内部错误",
        "desc": "服务端发生了未处理异常，通常与后端代码或配置有关。",
        "suggest": "请重试一次；若持续出现，请联系开发者 CQFISH（QQ3981491440）并附上完整报错日志。",
    },
    "502": {
        "title": "网关错误",
        "desc": "上游服务异常或代理中间层返回了错误响应。",
        "suggest": "请稍后重试，确认后端服务是否正常；如持续失败，可联系开发者 CQFISH（QQ3981491440）。",
    },
    "503": {
        "title": "服务暂不可用",
        "desc": "目标服务当前正忙、重启中或临时不可用。",
        "suggest": "请稍后重试，确认服务是否正在维护；必要时联系开发者 CQFISH（QQ3981491440）。",
    },
    "504": {
        "title": "网关超时",
        "desc": "请求在服务端或上游处理超时，常见于后端响应过慢或网络不稳定。",
        "suggest": "请稍后重试，检查网络和服务状态；如果持续超时，可联系开发者 CQFISH（QQ3981491440）。",
    },
}


def _decorate_error(raw_error: Any) -> str:
    """给原始错误字符串前追加状态码说明与处理建议。"""
    if raw_error is None:
        return ""
    text = str(raw_error).strip()
    if not text:
        return ""
    if "当前您遇到了" in text:
        return text

    match = re.search(r"(?:HTTP\s*|状态码\s*[:=]?\s*|code\s*[:=]?\s*)(\d{3,5})", text, re.IGNORECASE)
    code = match.group(1) if match else None
    if not code:
        code = next((k for k in _ERROR_GUIDES if k in text), None)

    if not code or code not in _ERROR_GUIDES:
        return text

    guide = _ERROR_GUIDES[code]
    return (
        f"当前您遇到了 {code} 状态码，这代表出现了 {guide['title']}：{guide['desc']} "
        f"建议您：{guide['suggest']} 原始响应：{text}"
    )


class Bridge:
    """暴露给前端的全部方法（pywebview js_api）。"""

    def __init__(self, config: Config) -> None:
        # 全部以 _ 开头：避免被 pywebview 反射为可暴露成员
        self._config = config
        self._window: Any = None  # 由 main.py 注入
        # 窗口是否处于最大化（由 pywebview 的 maximized/restored 事件维护，
        # 供前端标题栏"最大化/还原"按钮切换图标状态）
        self._maximized = False

        self._api = RtsboxAPI()
        self._downloader = DownloadManager(
            on_progress=self._dispatch_progress,
            on_status=self._dispatch_status,
        )
        # 版本管理器：游戏版本清单与本地 versions 多版本目录
        self._version_manager = VersionManager(
            self._config.path,
            game_root=Path(self._config["game_install_path"]),
        )
        self._launcher = self._build_launcher()
        # 游戏进程退出监听（仅用于游戏退出后自动云备份，不再做异常告警）
        self._monitor = GameMonitor(
            self._launcher, on_exit=self._auto_backup_after_game
        )


        # 资源 -> 已安装文件夹集合（按 title 哈希缓存）
        self._installed_mods_cache: Optional[set[str]] = None
        self._installed_maps_cache: Optional[set[str]] = None
        self._cache_lock = threading.Lock()
        # 下载历史登记：task_id -> {kind, title, folder, url, time}
        # 下载成功后才落盘到 history 文件，作为云端备份的 URL 清单来源
        self._pending_history: dict[str, dict] = {}
        self._history_lock = threading.Lock()

        # Java 版（简体中文增强版）：最近一次 Java 启动的进程 PID，
        # 供 kill_game / game_running 按 PID 定位（java.exe 无法按名匹配）。
        self._java_pid: Optional[int] = None
        # JRE 自动下载安装线程：避免重复并发安装（同一台机器只装一次）
        self._jre_thread: Optional[threading.Thread] = None

    # ==========================================================
    #  配置
    # ==========================================================

    def get_config(self) -> dict:
        return self._config.all()

    def get_app_info(self) -> dict:
        """应用版本信息（前端"关于"页使用，避免版本号在前端硬编码）。"""
        return {"version": APP_VERSION, "build_date": APP_BUILD_DATE}

    def festival_theme(self) -> dict:
        """节日主题状态：按法定节假日返回今天的点缀配色标识。

        联网同步（可配置接口）→ 本地缓存 → 内置兜底表逐级降级，
        任何一级失败都不影响启动器运行；节假日之外的日期返回 active=False。
        """
        cfg = self._config.get("festival_theme") or {}
        if cfg.get("enabled") is False:
            return {"ok": True, "active": False, "theme": "", "name": "", "disabled": True}
        cache_path = self._config.path.parent / "festival_cache.json"
        try:
            return detect_festival(
                api_url=str(cfg.get("api_url") or ""),
                timeout=float(cfg.get("timeout") or 5),
                cache_path=cache_path,
                cache_max_age_days=int(cfg.get("cache_max_age_days") or 30),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("节日主题检测失败：%s", e)
            return {"ok": False, "active": False, "error": str(e)}

    def check_update(self) -> dict:
        """检查更新：从 update_check.url 拉取版本公告并比较版本号。

        支持两种格式：
        1. JSON格式（windows.json）：{"latest_version":"2.6.0","versions":{...}}
        2. 旧版纯文本格式（new.html）：version:X.X.X / info:<更新内容>
        """
        import urllib.request
        import json

        cfg = self._config.get("update_check") or {}
        url = str(cfg.get("url") or "").strip()
        timeout = float(cfg.get("timeout") or 5)
        if not url:
            return {"ok": False, "error": "未配置更新检查地址"}
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "CQRWLauncher/" + APP_VERSION}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            return {"ok": False, "error": f"获取更新公告失败: {e}"}

        latest = ""
        info = ""
        
        # 先尝试解析为JSON格式（windows.json）
        try:
            data = json.loads(text)
            latest = data.get('latest_version', '')
            versions_data = data.get('versions', {})
            latest_info = versions_data.get(latest, {})
            info = latest_info.get('info', '')
        except (json.JSONDecodeError, TypeError):
            # 回退到旧版纯文本格式（version:X.X.X / info:xxx）
            lines = (text or "").replace("\r\n", "\n").split("\n")
            for i, line in enumerate(lines):
                s = line.strip()
                if s.startswith("version:"):
                    latest = s[len("version:"):].strip()
                elif s.startswith("info:"):
                    info = s[len("info:"):].strip()
                    for nxt in lines[i + 1:]:
                        nxt_s = nxt.strip()
                        if nxt_s.startswith("version:"):
                            break
                        if nxt_s:
                            info = f"{info}\n{nxt_s}" if info else nxt_s
            info = info.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")

        return {
            "ok": True,
            "has_update": bool(latest) and _version_gt(latest, APP_VERSION),
            "current_version": APP_VERSION,
            "latest_version": latest,
            "info": info,
        }

    def get_disclaimer_required(self) -> bool:
        """首次启动是否还需要展示免责声明（未看过则返回 True）。"""
        return not bool(self._config.get("disclaimer_seen"))

    def ack_disclaimer(self) -> None:
        """记录用户已阅读免责声明，之后不再自动弹出。"""
        self._config.set("disclaimer_seen", True)
        self._config.save()

    def update_config(self, updates: dict) -> None:
        if not isinstance(updates, dict):
            return
        # 嵌套 window / appearance / java_runtime / game_version_list 合并
        for sub_key in ("window", "appearance", "java_runtime", "game_version_list"):
            if isinstance(updates.get(sub_key), dict):
                cur = self._config.get(sub_key, {})
                if isinstance(cur, dict):
                    cur = {**cur, **updates[sub_key]}
                else:
                    cur = dict(updates[sub_key])
                updates[sub_key] = cur
        # java_runtime 关键字段的轻量校验，防止前端传回非法值
        jr = updates.get("java_runtime")
        if isinstance(jr, dict):
            if "mode" in jr and jr["mode"] not in ("auto", "java", "exe"):
                jr["mode"] = "auto"
            if "auto_download" in jr:
                jr["auto_download"] = bool(jr["auto_download"])
            if "feature_version" in jr:
                try:
                    jr["feature_version"] = max(9, min(64, int(jr["feature_version"])))
                except (TypeError, ValueError):
                    jr.pop("feature_version", None)
        self._config.update(**updates)
        self._config.save()
        # 版本清单地址变更：清缓存，下次查询重新拉取
        if "game_version_list" in updates:
            self._version_manager.clear_cache()
        # 路径或可执行文件名变了，刷新版本管理器与 launcher
        if "game_install_path" in updates:
            self._version_manager.update_game_root(
                Path(self._config["game_install_path"])
            )
        if (
            "game_install_path" in updates
            or "game_exe_name" in updates
            or "game_selected_version" in updates
        ):
            self._launcher = self._build_launcher()
            self._installed_mods_cache = None
            self._installed_maps_cache = None
            # 监听器绑定旧 launcher，重建（游戏未运行时停止即可）。
            # 必须与 __init__ 一致带上 on_exit：否则改过游戏路径的用户
            # "游戏退出自动备份"会静默失效。
            self._monitor.stop()
            self._monitor = GameMonitor(
                self._launcher,
                on_exit=self._auto_backup_after_game,
            )

    def set_close_behavior(self, behavior: str) -> None:
        """记录用户的关闭行为选择。"""
        if behavior not in ("minimize", "exit", "ask"):
            behavior = "ask"
        self._config.set("close_behavior", behavior)
        self._config.save()

    def get_close_behavior(self) -> str:
        return self._config.get("close_behavior") or "ask"

    # ==========================================================
    #  FRP 内网穿透
    # ==========================================================

    def _read_frp_config(self) -> FrpConfig:
        """从全局 config 读 frp 段，转 FrpConfig 数据类。"""
        c = self._config.get("frp") or {}
        return FrpConfig(
            enabled=bool(c.get("enabled", False)),
            server_addr=str(c.get("server_addr") or DEFAULT_FRPC["serverAddr"]),
            server_port=int(c.get("server_port") or DEFAULT_FRPC["serverPort"]),
            auth_token=str(c.get("auth_token") or ""),
            proxy_name=str(c.get("proxy_name") or "rw-game"),
            proxy_type=str(c.get("proxy_type") or "tcp"),
            local_ip=str(c.get("local_ip") or "127.0.0.1"),
            local_port=int(c.get("local_port") or 5123),
            frpc_path=str(c.get("frpc_path") or ""),
        )

    def get_frp_config(self) -> dict:
        """读取 frp 配置（前端显示用）。"""
        cfg = self._read_frp_config()
        return {"ok": True, "config": cfg.__dict__}

    def set_frp_config(self, updates: dict) -> dict:
        """更新 frp 配置（不立即启动/停止）。"""
        if not isinstance(updates, dict):
            return {"ok": False, "error": "参数错误"}
        cur = self._config.get("frp") or {}
        # 字段白名单
        if "enabled" in updates:
            cur["enabled"] = bool(updates["enabled"])
        if "server_addr" in updates:
            cur["server_addr"] = str(updates["server_addr"] or "").strip()
        if "server_port" in updates:
            try:
                cur["server_port"] = int(updates["server_port"])
            except (ValueError, TypeError):
                return {"ok": False, "error": "server_port 必须是数字"}
        if "auth_token" in updates:
            cur["auth_token"] = str(updates["auth_token"] or "")
        if "proxy_name" in updates:
            cur["proxy_name"] = str(updates["proxy_name"] or "rw-game").strip()
        if "proxy_type" in updates:
            t = str(updates["proxy_type"] or "tcp").strip().lower()
            if t not in ("tcp", "udp"):
                return {"ok": False, "error": "proxy_type 必须是 tcp 或 udp"}
            cur["proxy_type"] = t
        if "local_ip" in updates:
            cur["local_ip"] = str(updates["local_ip"] or "127.0.0.1").strip()
        if "local_port" in updates:
            try:
                cur["local_port"] = int(updates["local_port"])
            except (ValueError, TypeError):
                return {"ok": False, "error": "local_port 必须是数字"}
        if "frpc_path" in updates:
            cur["frpc_path"] = str(updates["frpc_path"] or "").strip()
        self._config.set("frp", cur)
        self._config.save()
        return self.get_frp_config()

    def start_frp(self) -> dict:
        """启动 frpc 子进程。"""
        cfg = self._read_frp_config()
        mgr = get_frp_manager()
        res = mgr.start(cfg)
        if res.get("ok"):
            # 启动成功后把 enabled 标记为 true（提示已运行）。
            # Config.set 不支持点号路径，必须整段写回；
            # 直接 set("frp.enabled", ...) 会产生平铺垃圾键（历史 bug）
            cur = self._config.get("frp") or {}
            cur["enabled"] = True
            self._config.set("frp", cur)
            self._config.save()
        return res

    def stop_frp(self) -> dict:
        """停止 frpc 子进程。"""
        mgr = get_frp_manager()
        res = mgr.stop()
        if res.get("ok"):
            cur = self._config.get("frp") or {}
            cur["enabled"] = False
            self._config.set("frp", cur)
            self._config.save()
        return res

    def get_frp_status(self) -> dict:
        """查询 frpc 当前状态（含进程 PID、frpc.exe 路径、最近日志）。"""
        cfg = self._read_frp_config()
        mgr = get_frp_manager()
        st: FrpStatus = mgr.status(cfg)
        return {
            "ok": True,
            "status": {
                "installed": st.installed,
                "frpc_path": st.frpc_path,
                "running": st.running,
                "pid": st.pid,
                "config_path": st.config_path,
                "last_error": st.last_error,
                "last_log_lines": st.last_log_lines,
            },
        }

    # ==========================================================
    #  游戏
    # ==========================================================

    def get_game_status(self) -> dict:
        jar = self._launcher.java_jar_path
        jr = self._config.get("java_runtime") or {}
        mode = str(jr.get("mode") or "auto")
        return {
            "exists": self._launcher.exists(),
            "path": str(self._launcher.exe_path),
            "game_dir": str(self._launcher.game_dir),       # 用户配置的安装根
            "game_root": str(self._launcher.game_root),     # 智能定位后的真实游戏目录
            "has_java_jar": jar is not None,                # Java 版（简体中文增强版）入口 jar
            "java_jar": str(jar) if jar else None,
            "launchable": self._launcher.launchable(),
            "mode": mode,                                   # auto / java / exe
        }

    def _tmp_dir(self) -> Path:
        """临时下载目录：统一放在游戏安装根下的 _rw_tmp。

        游戏本体 zip 与资源临时文件都放在这里，避免污染版本目录。
        """
        d = Path(self._config["game_install_path"]) / "_rw_tmp"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -------- 游戏版本定位 --------

    def _build_launcher(self) -> GameLauncher:
        """按当前选中版本构造游戏启动器；未选择版本时回退安装根旧布局。"""
        return GameLauncher(
            game_dir=self._selected_game_dir(),
            exe_name=str(self._config.get("game_exe_name") or "RustedWarfare.exe"),
            config=self._config,
        )

    def _selected_game_dir(self) -> Path:
        """当前选中版本的安装目录（versions/<版本>），目录缺失时回退安装根。"""
        root = Path(self._config["game_install_path"])
        version = str(self._config.get("game_selected_version") or "").strip()
        if version:
            vdir = self._version_manager.version_dir(version)
            if vdir.is_dir():
                return vdir
        return root

    def _resolve_download_version(self) -> tuple[str, VersionInfo]:
        """确定本次下载使用的游戏版本与远程清单信息。

        选中为空时取清单 default 编辑版标记的 latest_version 并写入配置记住。
        """
        vm = self._version_manager
        version = str(self._config.get("game_selected_version") or "").strip()
        info = vm.find_remote_version(version) if version else None
        if info is None:
            latest = vm.get_latest_version("default")
            if not latest:
                raise RuntimeError("版本清单中没有任何可用版本")
            info = vm.find_remote_version(latest)
            if info is None:
                raise RuntimeError(f"清单标记的最新版本 {latest} 不在版本列表中")
            version = latest
        if not info.url:
            raise RuntimeError(f"版本 {version} 没有下载地址")
        if str(self._config.get("game_selected_version") or "").strip() != version:
            self._config.set("game_selected_version", version)
            self._config.save()
        return version, info

    def install_game(self) -> str:
        """下载并解压当前选中版本的游戏本体，返回 task_id（失败返回空串）。"""
        task_id = "game_install"
        try:
            version, info = self._resolve_download_version()
        except Exception as e:
            logger.error("提交游戏下载失败：%s", e)
            self._toast(f"获取游戏下载地址失败：{e}", "error")
            return ""
        version_dir = self._version_manager.version_dir(version)
        version_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r'[^A-Za-z0-9._-]', "_", version)
        tmp_zip = self._tmp_dir() / f"game-{safe}.zip"
        limit_kbps = float(self._config.get("download_speed_limit_kbps") or 0.0)
        logger.info("开始下载游戏版本 %s：%s", version, info.url)
        self._downloader.submit(
            task_id=task_id,
            url=info.url,
            dest=tmp_zip,
            extract_to=version_dir,
            speed_limit_bps=limit_kbps * 1024 if limit_kbps > 0 else 0.0,
            on_done=lambda tid, okk, err: self._on_game_version_installed(
                tid, okk, err, version, version_dir
            ),
        )
        return task_id

    @staticmethod
    def _is_game_dir(d: Path) -> bool:
        """目录是否为游戏本体目录（含 RustedWarfare 相关可执行文件 / jar 的一层子目录）。"""
        try:
            for p in d.iterdir():
                if p.is_file():
                    low = p.name.lower()
                    if p.suffix.lower() == ".exe" and "rusted" in low:
                        return True
                    if low == "rustedwarfare.jar":
                        return True
        except OSError:
            pass
        return False

    @staticmethod
    def _merge_dir(src: Path, dst: Path) -> int:
        """把 src 目录合并进 dst：已存在的文件跳过（以 dst 为准），返回新拷贝文件数。"""
        if not src.is_dir():
            return 0
        copied = 0
        for item in src.rglob("*"):
            try:
                rel = item.relative_to(src)
            except ValueError:
                continue
            target = dst / rel
            if item.is_dir():
                try:
                    target.mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass
            elif not target.exists():
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
                    copied += 1
                except OSError:
                    pass
        return copied

    def _merge_game_data(self, target_launcher: GameLauncher) -> int:
        """安装新版本后，把旧布局目录与其他版本目录的 mods/maps/saves 合并进来。"""
        new_root = target_launcher.game_root
        roots: list[Path] = []
        install_root = Path(self._config["game_install_path"])
        # 旧布局：安装根下一层的游戏本体目录
        try:
            for child in install_root.iterdir():
                if (
                    child.is_dir()
                    and child.name not in ("versions", "_rw_tmp")
                    and self._is_game_dir(child)
                ):
                    roots.append(child)
        except OSError:
            pass
        # 其他已安装版本：智能定位到各自真实游戏根
        try:
            for vd in self._version_manager.versions_root.iterdir():
                if not vd.is_dir():
                    continue
                other = GameLauncher(
                    game_dir=vd,
                    exe_name=str(self._config.get("game_exe_name") or "RustedWarfare.exe"),
                    config=self._config,
                )
                if other.launchable():
                    roots.append(other.game_root)
        except OSError:
            pass
        count = 0
        for src_root in roots:
            if src_root == new_root:
                continue
            for name in ("mods", "maps", "saves"):
                count += self._merge_dir(src_root / name, new_root / name)
        return count

    def _on_game_version_installed(
        self,
        task_id: str,
        ok: bool,
        error: Optional[str],
        version: str,
        version_dir: Path,
    ) -> None:
        """游戏版本下载解压完成：验证主程序、合并旧数据、切换启动定位。"""
        if not ok:
            logger.error("游戏版本 %s 安装失败：%s", version, error)
            self._toast(f"版本 {version} 安装失败：{error}", "error")
            return
        try:
            new_launcher = GameLauncher(
                game_dir=version_dir,
                exe_name=str(self._config.get("game_exe_name") or "RustedWarfare.exe"),
                config=self._config,
            )
            if not new_launcher.launchable():
                logger.error("版本 %s 解压完成但未找到游戏主程序（%s）", version, version_dir)
                self._toast(f"版本 {version} 已解压，但未找到游戏主程序", "warning")
                return
            merged = self._merge_game_data(new_launcher)
            # 安装完成即选中新版本并重建启动定位
            self._config.set("game_selected_version", version)
            self._config.save()
            self._launcher = new_launcher
            self._monitor.bind_launcher(new_launcher)
            tip = f"版本 {version} 安装完成"
            if merged:
                tip += f"，已合并 {merged} 项旧数据"
            logger.info("游戏版本 %s 安装完成：%s", version, new_launcher.exe_path)
            self._toast(tip, "success")
        except Exception:
            logger.exception("游戏版本 %s 安装后处理失败", version)
            self._toast(f"版本 {version} 安装后处理异常", "error")

    def launch_game(self, raw_args: str) -> dict:
        """启动游戏（原生 exe / Java 版按 java_runtime.mode 分流）。

        原生 exe 与 Java 版进程都以 DETACHED_PROCESS 直启、脱离本进程组，
        启动器关闭不杀游戏。Java 进程（java.exe）无法按映像名定位，
        因此记录 pid：kill_game / game_running / 故障监控按 pid 跟踪。

        返回：
          {ok: true, mode, pid}            成功；
          {ok: false, error, ...}          失败；
          其中 needs_jre=true 表示缺 JRE，若 auto_download 已开启，
          会触发后台下载安装并在完成后自动重试启动。
        """
        try:
            jr = self._config.get("java_runtime") or {}
            mode = str(jr.get("mode") or "auto")
            if mode not in ("auto", "java", "exe"):
                mode = "auto"
            # 强制 exe 但没装 exe：直接报错，别去尝 Java 版
            if mode == "exe" and not self._launcher.exists():
                return {
                    "ok": False,
                    "mode": mode,
                    "error": f"游戏可执行文件未找到：{self._launcher.exe_path}",
                }
            if not self._launcher.launchable():
                return {
                    "ok": False,
                    "mode": mode,
                    "error": "未找到游戏主程序（既无 exe 也无 Java 版 jar）："
                    f"{self._launcher.game_dir}",
                }
            # 判定本次是否走 Java 版（与 launcher.launch 的 auto 分流一致）
            use_java = mode == "java" or (mode == "auto" and not self._launcher.exists())
            # 记录最近一次参数
            if raw_args != self._config.get("last_launch_args"):
                self._config.set("last_launch_args", raw_args or "")
                self._config.save()
            target = self._launcher.java_jar_path if use_java else self._launcher.exe_path
            logger.info("启动游戏：模式=%s 目标=%s 参数=%r", mode, target, raw_args or "")
            try:
                proc = self._launcher.launch(raw_args or "", mode=mode)
            except JavaRuntimeMissingError as e:
                return self._handle_java_runtime_missing(e, raw_args or "", mode)
            pid = proc.pid if proc is not None else None
            self._java_pid = pid if use_java else None
            # 启动后开启进程退出监听（Java 进程按 PID 跟踪；原生 exe 按映像名轮询）
            self._monitor.begin(watch_pid=pid if use_java else None)
            # 启动后启动器最小化
            if self._window is not None:
                try:
                    self._window.minimize()
                except Exception:
                    pass
            return {"ok": True, "mode": "java" if use_java else "exe", "pid": pid}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _handle_java_runtime_missing(
        self, e: JavaRuntimeMissingError, raw_args: str, mode: str
    ) -> dict:
        """Java 版启动缺 JRE：按 java_runtime.auto_download 决定自动补齐或报错。"""
        jr = self._config.get("java_runtime") or {}
        auto = bool(jr.get("auto_download"))
        feature = int(jr.get("feature_version") or DEFAULT_FEATURE_VERSION)
        install_dir = e.install_dir
        if not install_dir:
            jar = self._launcher.java_jar_path
            install_dir = str(jar.parent / JVM_DIR_64) if jar is not None else ""
        reason = str(e) or "未找到可用 Java 运行环境"
        logger.warning("Java 版启动缺少 JRE：%s（install_dir=%s）", reason, install_dir)
        if auto:
            if self._jre_thread is not None and self._jre_thread.is_alive():
                return {
                    "ok": False,
                    "mode": mode,
                    "needs_jre": True,
                    "jre_downloading": True,
                    "error": "Java 运行环境正在安装中，请稍候再试",
                }
            self._start_jre_install(raw_args=raw_args, install_dir=install_dir, feature_version=feature)
            return {
                "ok": False,
                "mode": mode,
                "needs_jre": True,
                "jre_downloading": True,
                "error": "未找到 Java 运行环境，已开始自动下载 JRE，完成后将自动启动游戏",
            }
        return {
            "ok": False,
            "mode": mode,
            "needs_jre": True,
            "install_dir": install_dir,
            "error": f"{reason}。请在设置中开启「自动下载 Java 运行环境」，"
            f"或手动把 JRE 放到 {install_dir}",
        }

    def _start_jre_install(
        self,
        raw_args: str = "",
        install_dir: Optional[str] = None,
        feature_version: int = DEFAULT_FEATURE_VERSION,
    ) -> None:
        """后台线程安装 JRE（Adoptium），同一时刻只允许一个安装线程。"""
        if self._jre_thread is not None and self._jre_thread.is_alive():
            return
        t = threading.Thread(
            target=self._install_jre_worker,
            kwargs={
                "raw_args": raw_args,
                "install_dir": install_dir,
                "feature_version": feature_version,
            },
            name="jre-install",
            daemon=True,
        )
        self._jre_thread = t
        t.start()

    def _install_jre_worker(
        self, raw_args: str, install_dir: Optional[str], feature_version: int
    ) -> None:
        """下载并安装 Adoptium JRE 到游戏根目录；成功后自动重试启动游戏。"""
        task_id = "jre_download"
        try:
            jar = self._launcher.java_jar_path
            if jar is None:
                raise RuntimeError("未找到游戏主程序 jar")
            target_dir = Path(install_dir or (jar.parent / JVM_DIR_64))
            self._dispatch_status(task_id, TaskStatus.DOWNLOADING.value, None)
            self._toast(f"未找到 Java 运行环境，正在自动下载 JRE{feature_version}...", "info")
            asset = query_adoptium_jre(feature_version=feature_version)
            if not asset.get("ok") or not asset.get("link"):
                raise RuntimeError(asset.get("error") or "查询 JRE 下载信息失败")
            logger.info("下载 JRE%d：%s", feature_version, asset["link"])
            dest_zip = self._tmp_dir() / f"adoptium-jre{feature_version}.zip"
            download_jre(
                asset,
                dest_zip,
                progress_cb=lambda dl, total: self._dispatch_progress(task_id, dl, total),
            )
            if target_dir.exists():
                raise FileExistsError(f"目标 JRE 目录已存在：{target_dir}")
            self._dispatch_status(task_id, TaskStatus.EXTRACTING.value, None)
            install_jre_zip(dest_zip, target_dir)
            try:
                dest_zip.unlink(missing_ok=True)
            except OSError:
                pass
            cleanup_old_jre(target_dir.parent)
            self._dispatch_status(task_id, TaskStatus.COMPLETED.value, None)
            self._toast(f"Java 运行环境已就绪（JRE{feature_version}）", "success")
            logger.info("JRE 安装完成：%s，自动重试启动游戏", target_dir)
            if raw_args:
                result = self.launch_game(raw_args)
                if not result.get("ok"):
                    self._toast(f"自动启动失败：{result.get('error') or '未知错误'}", "error")
        except Exception as e:  # noqa: BLE001
            logger.exception("JRE 自动安装失败")
            self._dispatch_status(task_id, TaskStatus.FAILED.value, str(e))
            self._toast(f"Java 运行环境下载失败：{e}", "error")

    def java_status(self) -> dict:
        """Java 版（简体中文增强版）运行环境状态，供首页提示条 / 设置页展示。"""
        st = self._launcher.java_status()
        jr = self._config.get("java_runtime") or {}
        mode = str(jr.get("mode") or "auto")
        st["mode"] = mode
        st["auto_download"] = bool(jr.get("auto_download"))
        st["feature_version"] = int(jr.get("feature_version") or DEFAULT_FEATURE_VERSION)
        st["install_jvm_dir"] = str(jr.get("install_jvm_dir") or JVM_DIR_64)
        st["has_jar"] = st.get("jar") is not None
        st["installing"] = self._jre_thread is not None and self._jre_thread.is_alive()
        return st

    def install_java_runtime(self) -> dict:
        """手动触发 JRE 下载安装（设置页按钮）。成功后由线程自动重试无需参数启动。

        需要 Java 版 jar 才允许安装；已存在可用 JRE 时直接返回 ok。
        """
        jar = self._launcher.java_jar_path
        if jar is None:
            return {"ok": False, "error": "未找到 Java 版游戏 jar，无需安装 JRE"}
        st = self._launcher.java_status()
        if not st.get("needs_install") and st.get("java_path"):
            return {"ok": True, "already": True}
        if self._jre_thread is not None and self._jre_thread.is_alive():
            return {"ok": True, "installing": True}
        jr = self._config.get("java_runtime") or {}
        feature = int(jr.get("feature_version") or DEFAULT_FEATURE_VERSION)
        self._start_jre_install(install_dir=st.get("install_dir"), feature_version=feature)
        return {"ok": True, "installing": True}

    def kill_game(self) -> dict:
        """快速结束游戏进程（强制终止所有匹配的游戏进程实例）。

        两类目标：
        1. Java 版（简体中文增强版）：java.exe 无法按映像名匹配，
           按最近一次 Java 启动记录的 pid 结束；
        2. 原生 exe：映像名不固定（RustedWarfare.exe、RustedWarfare -64.exe、
           带空格的 Rusted Warfare.exe），全量扫描后按映像名模糊匹配。
        返回 killed=True 表示确实结束了进程；killed=False 表示未检测到游戏在运行；
        若部分进程因权限等无法结束，会返回 error/warning 说明。
        """
        import subprocess

        # 用户主动干预：停止退出监听（进程被主动结束时不触发退出自动备份）
        self._monitor.stop()
        try:
            killed: list[str] = []
            failed: list[str] = []
            # 1. Java 版：按 pid 结束
            pid = self._java_pid
            self._java_pid = None
            if pid is not None and pid_alive(pid):
                r = subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True, text=True, timeout=4,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if r.returncode == 0:
                    killed.append(f"Java(PID {pid})")
                    logger.info("已结束 Java 版游戏进程：PID %s", pid)
                else:
                    failed.append(f"PID {pid}")
                    logger.warning("结束 Java 版游戏进程失败 PID %s", pid)
            # 2. 原生 exe：按映像名匹配
            names = self._find_game_processes()
            for name in set(names):
                r = subprocess.run(
                    ["taskkill", "/F", "/IM", name],
                    capture_output=True, text=True, timeout=4,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if r.returncode == 0:
                    killed.append(name)
                    logger.info("已结束游戏进程：%s", name)
                else:
                    failed.append(name)
                    detail = (r.stderr or r.stdout or "").strip().splitlines()
                    logger.warning(
                        "结束游戏进程失败 %s：%s",
                        name,
                        detail[-1] if detail else f"exit={r.returncode}",
                    )
            if not killed and not names and pid is None:
                return {"ok": True, "killed": False}
            if failed and not killed:
                return {
                    "ok": False,
                    "error": "游戏进程无法结束（可能需要以管理员身份运行启动器）：" + "、".join(failed),
                }
            if failed:
                return {
                    "ok": True,
                    "killed": True,
                    "warning": "部分游戏进程无法结束：" + "、".join(failed),
                }
            return {"ok": True, "killed": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def game_running(self) -> dict:
        """检测游戏进程是否在运行（Java 版按 PID，原生 exe 按映像名）。"""
        if self._java_pid is not None:
            return {"running": pid_alive(self._java_pid)}
        return {"running": bool(self._find_game_processes())}

    # ==========================================================
    #  手动诊断
    # ==========================================================

    def run_diagnosis(self) -> dict:
        """手动运行一次全项诊断，返回诊断报告。"""
        return run_diagnosis(self._launcher, self._config)

    # ==========================================================
    #  存档管理
    # ==========================================================

    def _saves_backup_root(self) -> Path:
        """存档备份根目录：启动器同目录 saves_backup/（绿色便携，随启动器移动）。"""
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
        else:
            base = Path(__file__).resolve().parent.parent
        d = base / "saves_backup"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return d

    def list_saves(self) -> dict:
        """列出全部存档（便携版与我的文档版，含大小 / 时间 / 来源）。"""
        dirs = find_saves_dirs(self._launcher.game_root)
        items: list[dict] = []
        game_saves = (self._launcher.game_root / "saves").as_posix().lower()
        for d in dirs:
            loc = "游戏目录" if d.as_posix().lower() == game_saves else "我的文档"
            for p in iter_save_files(d):
                try:
                    st = p.stat()
                except OSError:
                    continue
                items.append({
                    "name": p.name,
                    "relpath": p.relative_to(d).as_posix(),
                    "path": str(p),
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "location": loc,
                })
        return {"dirs": [str(d) for d in dirs], "items": items}

    def backup_saves(self, paths: Optional[list] = None) -> dict:
        """备份存档到 saves_backup/backup-时间戳/。paths 为空时备份全部。"""
        items = self.list_saves()["items"]
        if not items:
            return {"ok": False, "error": "没有可备份的存档"}
        if paths:
            wanted = set(paths)
            selected = [it for it in items if it["path"] in wanted]
            if not selected:
                return {"ok": False, "error": "所选存档不存在"}
        else:
            selected = items

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = self._saves_backup_root() / f"backup-{stamp}"
        meta: list[dict] = []
        try:
            dest.mkdir(parents=True, exist_ok=False)
            for it in selected:
                rel = Path(it["relpath"])
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(it["path"], target)
                meta.append({
                    "name": it["name"],
                    "relpath": it["relpath"],
                    "location": it["location"],
                    "origin": it["path"],
                })
            with (dest / "meta.json").open("w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except OSError as e:
            shutil.rmtree(dest, ignore_errors=True)
            return {"ok": False, "error": f"备份失败：{e}"}
        logger.info("已备份 %d 个存档到 %s", len(selected), dest)
        return {"ok": True, "created": dest.name, "count": len(selected), "path": str(dest)}

    def list_save_backups(self) -> dict:
        """列出全部存档备份（按时间倒序）。"""
        root = self._saves_backup_root()
        out: list[dict] = []
        for d in sorted(root.glob("backup-*")):
            if not d.is_dir():
                continue
            meta: list = []
            try:
                with (d / "meta.json").open("r", encoding="utf-8") as f:
                    parsed = json.load(f)
                if isinstance(parsed, list):
                    meta = parsed
            except (OSError, json.JSONDecodeError):
                pass
            size = 0
            for p in d.rglob("*"):
                if p.is_file() and p.name != "meta.json":
                    try:
                        size += p.stat().st_size
                    except OSError:
                        pass
            out.append({
                "name": d.name,
                "path": str(d),
                "count": len(meta),
                "size": size,
                "created": d.name.replace("backup-", "").replace("-", " "),
            })
        out.sort(key=lambda x: x["name"], reverse=True)
        return {"items": out}

    def restore_save_backup(self, name: str) -> dict:
        """从备份恢复到原存档位置（恢复前校验路径安全）。"""
        dest = self._saves_backup_root() / name
        if not dest.is_dir() or not dest.name.startswith("backup-"):
            return {"ok": False, "error": "备份不存在"}
        try:
            with (dest / "meta.json").open("r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return {"ok": False, "error": f"备份信息损坏：{e}"}
        if not isinstance(meta, list) or not meta:
            return {"ok": False, "error": "备份信息为空或损坏"}

        backup_root = str(self._saves_backup_root()).lower()
        restored = 0
        errors: list[str] = []
        for entry in meta:
            relpath = entry.get("relpath")
            origin = entry.get("origin")
            if not relpath or not origin:
                errors.append("备份条目缺少路径信息")
                continue
            target_root = resolve_restore_root(entry, self._launcher.game_root)
            if target_root is None:
                errors.append(f"无法确定 {entry.get('name', relpath)} 的恢复位置")
                continue
            dst = target_root / relpath
            dst_low = str(dst).lower()
            if dst_low.startswith(backup_root) or "saves" not in dst.parts:
                errors.append(f"拒绝恢复不安全路径：{dst}")
                continue
            src = dest / relpath
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                restored += 1
            except OSError as e:
                errors.append(f"恢复 {relpath} 失败：{e}")
        logger.info("从备份 %s 恢复了 %d 个存档", name, restored)
        return {
            "ok": not errors,
            "error": "；".join(errors) if errors else None,
            "restored": restored,
        }

    def delete_saves(self, paths: list) -> dict:
        """删除指定存档文件。"""
        if not isinstance(paths, list) or not paths:
            return {"ok": False, "error": "未选择要删除的存档"}
        items = self.list_saves()["items"]
        valid = {it["path"] for it in items}
        removed = 0
        errors: list[str] = []
        for p in paths:
            if p not in valid:
                errors.append(f"存档不存在：{Path(p).name}")
                continue
            try:
                Path(p).unlink()
                removed += 1
            except OSError as e:
                errors.append(f"删除 {Path(p).name} 失败：{e}")
        return {"ok": not errors, "error": "；".join(errors) if errors else None, "removed": removed}

    def delete_save_backup(self, name: str) -> dict:
        """删除一个存档备份。"""
        dest = self._saves_backup_root() / name
        if not dest.is_dir() or not dest.name.startswith("backup-"):
            return {"ok": False, "error": "备份不存在"}
        shutil.rmtree(dest, ignore_errors=True)
        if dest.exists():
            return {"ok": False, "error": "删除备份失败（可能被占用）"}
        return {"ok": True}

    def open_saves_dir(self) -> dict:
        """打开存档目录（优先游戏目录版）。"""
        dirs = find_saves_dirs(self._launcher.game_root)
        if not dirs:
            return {"ok": False, "error": "未找到存档目录，请先运行一次游戏"}
        import os as _os

        try:
            _os.startfile(str(dirs[0]))
        except OSError as e:
            return {"ok": False, "error": f"打开目录失败：{e}"}
        return {"ok": True, "path": str(dirs[0])}

    def _find_game_processes(self) -> list[str]:
        """列出当前所有匹配的游戏进程映像名（如 RustedWarfare.exe、RustedWarfare -64.exe）。

        复用 diagnoser.game_procs 的 Toolhelp32 快照实现（无子进程开销）。
        """
        return [name for name, _pid in game_procs()]

    # ==========================================================
    #  模组 / 地图
    # ==========================================================

    def search_mods(self, keyword: str = "", page: int = 1, pages: int = 1) -> dict:
        return self._search("mod", keyword, page, pages)

    def search_maps(self, keyword: str = "", page: int = 1, pages: int = 1) -> dict:
        return self._search("map", keyword, page, pages)

    def get_bbs_post(self, url: str) -> dict:
        """获取 RTSBox 原帖正文，供启动器内置查看。"""
        try:
            return {"ok": True, "html": self._api.fetch_post(url)}
        except RtsboxAPIError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001
            logger.warning("原贴加载失败：%s", e)
            return {"ok": False, "error": "原贴加载失败"}

    def _search(self, kind: str, keyword: str, page: int, pages: int) -> dict:
        """搜索资源。优先走配套服务代理（缓存+降级），失败回退本地直连。

        注意：代理不可用不等于搜索失败。只要本地 rtsbox 直连取到数据，
        就照常返回结果，代理失败原因只放进 fallback_reason 供前端提示。
        这样账号服务不可用时，「铁锈盒子」渠道依旧可以搜索并下载模组。
        """
        pages = max(1, min(10, int(pages or 1)))
        items: list[dict] = []
        error: Optional[str] = None
        fallback_reason: Optional[str] = None
        via = "local"

        proxy = bool(self._config.get("rtsbox_proxy_enabled", True))
        if proxy:
            try:
                import urllib.parse
                qs = urllib.parse.urlencode({
                    "kind": kind, "keyword": keyword,
                    "page": int(page), "pages": pages,
                })
                data = self._account_request("GET", f"/api/rtsbox/search?{qs}")
            except Exception as e:  # noqa: BLE001
                data = {"ok": False, "error": f"代理请求异常：{e}"}
            if data.get("ok"):
                items = list(data.get("items") or [])
                via = "proxy"
                # 代理成功但一条都没有时，才把它的提示当错误展示
                error = None if items else data.get("error")
            else:
                fallback_reason = str(data.get("error") or "代理不可用")
                logger.info("rtsbox 代理不可用，回退本地直连：%s", fallback_reason)

        if via != "proxy":
            try:
                items = self._search_local(kind, keyword, page, pages)
                error = None
            except RtsboxAPIError as e2:
                error = str(e2)
                items = []

        cache = self._installed_cache(kind)
        enriched: list[dict] = []
        for it in items:
            it = dict(it)
            it["kind"] = kind
            folder = _sanitize_folder_name(it.get("title", "untitled"))
            it["folder"] = folder
            it["installed"] = folder in cache
            it["version"] = _extract_version(it.get("title", ""))
            enriched.append(it)
        return {
            "items": enriched,
            "error": error,
            "via": via,
            "fallback_reason": fallback_reason,
        }

    def _search_local(self, kind: str, keyword: str, page: int, pages: int) -> list[dict]:
        """本地直连 rtsbox 搜索并聚合多页去重；失败抛 RtsboxAPIError。"""
        merged: list[dict] = []
        seen: set[tuple] = set()
        for p in range(page, page + pages):
            if kind == "mod":
                batch = self._api.search_mods(keyword=keyword, page=p)
            else:
                batch = self._api.search_maps(keyword=keyword, page=p)
            if not batch:
                break
            for it in batch:
                key = (it.get("title"), it.get("downurl"))
                if key in seen:
                    continue
                seen.add(key)
                merged.append(it)
        return merged

    def list_installed(self, kind: str) -> list[str]:
        """已安装的模组 / 地图文件夹名列表。"""
        cache = self._installed_cache(kind)
        return sorted(cache)

    # ==========================================================
    #  模组分享同步码 / 房间（配套服务）
    # ==========================================================

    def share_code_create(self, mods: list, ttl_hours: int = 0) -> dict:
        """生成模组分享同步码（匿名，绑定 mod 元数据，不传文件）。"""
        ttl = int(ttl_hours or 0)
        if ttl <= 0:
            ttl = int(self._config.get("share_code_ttl_hours", 168))
        if not isinstance(mods, list) or not mods:
            return {"ok": False, "error": "没有可分享的模组"}
        payload: list[dict] = []
        for m in mods:
            if not isinstance(m, dict):
                continue
            title = str(m.get("title") or "")[:120]
            url = str(m.get("url") or m.get("downurl") or "")[:1024]
            kind = "map" if m.get("kind") == "map" else "mod"
            if title and url:
                payload.append({"title": title, "url": url, "kind": kind})
        if not payload:
            return {"ok": False, "error": "模组清单为空"}
        return self._account_request(
            "POST", "/api/shareCodes", {"mods": payload, "ttl_hours": ttl}
        )

    def share_code_resolve(self, code: str) -> dict:
        """凭 6 位同步码取回模组列表。"""
        code = (code or "").strip().upper()
        if len(code) != 6:
            return {"ok": False, "error": "分享码格式不正确（应为 6 位）"}
        return self._account_request("GET", f"/api/shareCodes/{code}")

    def share_code_delete(self, code: str) -> dict:
        """删除分享码。"""
        code = (code or "").strip().upper()
        return self._account_request("DELETE", f"/api/shareCodes/{code}")

    def room_list(self, status: str = "open") -> dict:
        """房间列表（配套服务从 RW-HPS 集成，含绑定的分享码）。"""
        status = status if status in ("open", "closed") else "open"
        return self._account_request("GET", f"/api/rooms?status={status}")

    def room_bind_share(self, room_id: str, share_code: str) -> dict:
        """房主给房间绑定分享码。"""
        code = (share_code or "").strip().upper()
        return self._account_request(
            "POST", f"/api/rooms/{room_id}/bind", {"share_code": code}
        )

    def room_sync_mods(self, room_id: str) -> dict:
        """一键同步房间模组：取房间分享码 → 解析 → 逐个加入下载队列。"""
        data = self._account_request("GET", "/api/rooms?status=open")
        if not data.get("ok"):
            return {"ok": False, "error": data.get("error", "无法获取房间列表")}
        room = next(
            (r for r in data.get("items", []) if r.get("room_id") == room_id), None
        )
        if room is None:
            return {"ok": False, "error": "房间不存在"}
        code = (room.get("share_code") or "").strip()
        if not code:
            return {"ok": False, "error": "该房间未绑定模组分享码"}
        resolved = self._account_request("GET", f"/api/shareCodes/{code}")
        if not resolved.get("ok"):
            return {"ok": False, "error": resolved.get("error", "分享码无效")}
        mods = resolved.get("mods") or []
        if not mods:
            return {"ok": False, "error": "分享码中没有模组"}
        results: list[dict] = []
        queued = 0
        for m in mods:
            title = str(m.get("title") or "")
            url = str(m.get("url") or m.get("downurl") or "")
            kind = "map" if m.get("kind") == "map" else "mod"
            if not title or not url:
                results.append({"title": title, "ok": False, "error": "缺少标题或下载链接"})
                continue
            res = self.download_resource(kind, title, url)
            results.append({
                "title": title, "ok": bool(res.get("ok")),
                "error": res.get("error"), "installed": bool(res.get("installed")),
            })
            if res.get("ok"):
                queued += 1
        return {"ok": True, "queued": queued, "total": len(mods), "results": results}

    def clear_game_cache(self, targets: list[str]) -> dict:
        """一键清除游戏缓存。

        targets 可取：mods（下载的模组）、maps（下载的地图）、saves（游戏存档）。
        只删除启动器下载格式的文件与存档内容，保留游戏自带的示例 / 模板文件，
        避免误删不可恢复的默认内容。
        """
        if isinstance(targets, str):
            targets = [targets]
        if not isinstance(targets, list):
            return {"ok": False, "error": "参数格式错误"}
        allowed = {"mods", "maps", "saves"}
        todo = [t for t in targets if t in allowed]
        if not todo:
            return {"ok": False, "error": "未选择任何清除项"}

        root = self._launcher.game_root
        if not root or not root.is_dir():
            return {"ok": False, "error": "游戏目录不存在，无法清除"}

        import shutil

        removed = {"mods": 0, "maps": 0, "saves": 0}
        errors: list[str] = []

        def _remove_entry(p: Path) -> None:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass

        if "mods" in todo:
            # 只清 mods/units 下下载的 .rwmod 单文件（游戏自带的是 custom_units_here.txt）
            d = root / "mods" / "units"
            if d.is_dir():
                for f in list(d.iterdir()):
                    if f.is_file() and f.suffix.lower() == ".rwmod":
                        try:
                            f.unlink()
                            removed["mods"] += 1
                        except OSError as e:
                            errors.append(f"删除 {f.name} 失败：{e}")

        if "maps" in todo:
            # 只清 mods/maps 顶层的 .tmx 地图文件，保留游戏自带示例
            # example_mission.tmx 与 rules/ 等子目录模板
            d = root / "mods" / "maps"
            if d.is_dir():
                for f in list(d.iterdir()):
                    if (
                        f.is_file()
                        and f.suffix.lower() == ".tmx"
                        and f.name.lower() != "example_mission.tmx"
                    ):
                        try:
                            f.unlink()
                            removed["maps"] += 1
                        except OSError as e:
                            errors.append(f"删除 {f.name} 失败：{e}")

        if "saves" in todo:
            # 存档目录：游戏目录 saves（便携版），并兼容 Documents\Rusted Warfare\saves
            candidates = [
                root / "saves",
                Path.home() / "Documents" / "Rusted Warfare" / "saves",
            ]
            for d in candidates:
                if d.is_dir():
                    for child in list(d.iterdir()):
                        _remove_entry(child)
                        removed["saves"] += 1

        # 清完后刷新已安装缓存
        self._invalidate_cache("mod")
        self._invalidate_cache("map")

        ok = not errors
        return {
            "ok": ok,
            "error": "；".join(errors) if errors else None,
            "removed": removed,
        }

    def _installed_cache(self, kind: str) -> set[str]:
        with self._cache_lock:
            if kind == "mod":
                cache = self._installed_mods_cache
            else:
                cache = self._installed_maps_cache

            if cache is None:
                cache = set()
                root = self._resource_root(kind)
                if root.is_dir():
                    for p in root.iterdir():
                        if p.is_dir():
                            cache.add(p.name)
                        elif p.is_file():
                            # 单文件资源（xxx.rwmod / xxx.tmx）：用不带扩展名的名字
                            cache.add(p.stem)
                if kind == "mod":
                    self._installed_mods_cache = cache
                else:
                    self._installed_maps_cache = cache
            return cache

    def _resource_root(self, kind: str) -> Path:
        """模组 / 地图存放根目录：游戏根目录（含 exe）下 mods 文件夹内。

        mod 单文件放 mods/units，地图单文件放 mods/maps，
        与游戏实际读取的目录保持一致。
        """
        sub = "units" if kind == "mod" else "maps"
        return self._launcher.game_root / "mods" / sub

    def _invalidate_cache(self, kind: str) -> None:
        with self._cache_lock:
            if kind == "mod":
                self._installed_mods_cache = None
            else:
                self._installed_maps_cache = None

    def download_resource(self, kind: str, title: str, downurl: str) -> dict:
        """下载一个模组 / 地图。

        模组固定为 .rwmod、地图固定为 .tmx 单文件格式，无需解压，
        直接存放到 mods/units 或 mods/maps 目录；格式不正确时拒绝下载。
        """
        if kind not in ("mod", "map"):
            return {"ok": False, "error": "未知资源类型"}
        if not downurl:
            return {"ok": False, "error": "缺少下载链接"}

        folder = _sanitize_folder_name(title)
        ext = ".rwmod" if kind == "mod" else ".tmx"
        target_file = self._resource_root(kind) / f"{folder}{ext}"
        # 旧版本遗留的"子文件夹"形态也视为已安装
        legacy_dir = self._resource_root(kind) / folder
        if target_file.exists() or legacy_dir.is_dir():
            return {"ok": False, "error": f"已存在：{folder}", "installed": True}

        logger.info("开始下载%s：%s -> %s", kind, title, target_file)
        limit_kbps = float(self._config.get("download_speed_limit_kbps") or 0.0)

        # 临时下载文件统一放在 _rw_tmp，避免污染资源目录
        tmp_zip = self._tmp_dir() / f"{folder}.tmp"

        # 用 folder 名做 task_id，便于前端跟踪
        digest = hashlib.md5(f"{kind}:{title}:{downurl}".encode("utf-8")).hexdigest()[:10]
        task_id = f"{kind}_{digest}"

        self._downloader.submit(
            task_id=task_id,
            url=downurl,
            dest=tmp_zip,
            # 资源模式：下载后校验格式（.rwmod / .tmx）并直接落盘到资源目录
            store_to=target_file,
            accept_ext=ext,
            speed_limit_bps=limit_kbps * 1024 if limit_kbps > 0 else 0.0,
        )
        # 登记下载意图：成功后写入历史（备份清单用）
        with self._history_lock:
            self._pending_history[task_id] = {
                "kind": kind,
                "title": title,
                "folder": folder,
                "url": downurl,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        return {"ok": True, "task_id": task_id, "folder": folder}

    def confirm_resource(self, task_id: str, action: str) -> dict:
        """用户对模组包嵌套检测的确认：fix 展平修复 / keep 保持原样。

        下载线程在 needs_confirm 状态下阻塞等待，收到确认后继续落盘。
        """
        task = self._downloader.get(task_id)
        if task is None:
            return {"ok": False, "error": "任务不存在"}
        task._confirm_action = action if action in ("fix", "keep") else "keep"
        task._confirm_evt.set()
        return {"ok": True}

    def cancel_download(self, task_id: str) -> None:
        self._downloader.cancel(task_id)

    def get_downloads(self) -> list[dict]:
        return self._downloader.list_active()

    # ==========================================================
    #  云端账号服务（登录注册 + 玩家数据备份）
    # ==========================================================

    def _account_cfg(self) -> dict:
        """读取 account 配置段。"""
        return self._config.get("account") or {}

    def _account_request(self, method: str, path: str, payload: dict = None) -> dict:
        """向账号服务发 HTTP 请求，统一解析 JSON 与错误。"""
        import json
        import urllib.error
        import urllib.request

        cfg = self._account_cfg()
        base = (cfg.get("base_url") or "http://127.0.0.1:4123").rstrip("/")
        token = cfg.get("token") or ""
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url=base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=float(cfg.get("timeout") or 5)) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode("utf-8"))
                if isinstance(payload, dict) and payload.get("error"):
                    payload["error"] = _decorate_error(payload["error"])
                    if payload.get("detail"):
                        payload["detail"] = _decorate_error(payload["detail"])
                    return payload
                return {"ok": False, "error": _decorate_error(f"账号服务返回 HTTP {e.code}")}
            except Exception:
                return {"ok": False, "error": _decorate_error(f"账号服务返回 HTTP {e.code}")}
        except Exception as e:
            return {"ok": False, "error": _decorate_error(f"无法连接账号服务: {e}")}

    def get_account_status(self) -> dict:
        """账号配置与登录态（本地视角）。"""
        cfg = self._account_cfg()
        return {
            "ok": True,
            "base_url": cfg.get("base_url", "http://127.0.0.1:4123"),
            "timeout": cfg.get("timeout", 5),
            "username": cfg.get("username", ""),
        }

    def set_account_config(self, *, base_url: str = None, timeout: float = None) -> dict:
        """更新账号服务地址 / 超时。"""
        cfg = self._account_cfg()
        if base_url is not None:
            cfg["base_url"] = str(base_url).strip().rstrip("/")
        if timeout is not None:
            cfg["timeout"] = float(timeout)
        self._config.set("account", cfg)
        return self.get_account_status()

    def account_health(self) -> dict:
        """探测账号服务可达性。"""
        data = self._account_request("GET", "/api/health")
        if data.get("ok"):
            return {
                "ok": True,
                "reachable": True,
                "service": data.get("service", ""),
                "version": data.get("version", ""),
                "users_total": data.get("users_total", 0),
            }
        return {"ok": False, "reachable": False, "error": data.get("error", "服务不可达")}

    def account_captcha(self) -> dict:
        """获取人机验证码（算术题；image 非空时前端展示图片）。"""
        return self._account_request("GET", "/api/auth/captcha")

    def account_register(
        self,
        username: str,
        password: str,
        captcha_id: str = "",
        captcha_answer: str = "",
        phone: str = "",
        email: str = "",
    ) -> dict:
        """注册账号：手机号 / 电子邮箱至少填写一项（仅记录不验证），需通过人机验证。成功即自动登录。"""
        data = self._account_request(
            "POST",
            "/api/auth/register",
            {
                "username": username,
                "password": password,
                "captcha_id": captcha_id,
                "captcha_answer": captcha_answer,
                "phone": phone,
                "email": email,
            },
        )
        if data.get("ok"):
            cfg = self._account_cfg()
            cfg["username"] = data.get("username", username)
            cfg["token"] = data.get("token", "")
            self._config.set("account", cfg)
        return data

    def account_login(self, username: str, password: str, captcha_id: str = "", captcha_answer: str = "") -> dict:
        """登录账号：人机验证 + 校验密码并保存会话 token。"""
        data = self._account_request(
            "POST",
            "/api/auth/login",
            {
                "username": username,
                "password": password,
                "captcha_id": captcha_id,
                "captcha_answer": captcha_answer,
            },
        )
        if data.get("ok"):
            cfg = self._account_cfg()
            cfg["username"] = data.get("username", username)
            cfg["token"] = data.get("token", "")
            self._config.set("account", cfg)
        return data

    def account_logout(self) -> dict:
        """登出账号：本地会话立即失效。"""
        self._account_request("POST", "/api/auth/logout")
        cfg = self._account_cfg()
        cfg["username"] = ""
        cfg["token"] = ""
        self._config.set("account", cfg)
        return {"ok": True}

    def account_me(self) -> dict:
        """当前登录账号信息（服务端校验）。"""
        return self._account_request("GET", "/api/auth/me")

    def account_profile_upload(self, preferences_xml: str = "", mods: list = None) -> dict:
        """上传玩家数据备份：身份文件 + 模组下载 URL 清单（存档不上传）。"""
        return self._account_request(
            "PUT", "/api/profile", {"preferences_xml": preferences_xml, "mods": mods or []}
        )

    def account_profile_pull(self) -> dict:
        """拉取玩家数据备份。"""
        return self._account_request("GET", "/api/profile")

    # ---- 玩家数据自动备份：身份文件 + 模组 URL 清单 ----

    def _history_path(self) -> Path:
        """下载历史文件（与 config.json 同目录的 data 文件夹）。"""
        base = Path(__file__).resolve().parent.parent
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
        return base / "data" / "resource_history.json"

    def _load_history(self) -> list[dict]:
        """读取下载历史（{kind,title,folder,url,time} 列表）。"""
        try:
            data = json.loads(self._history_path().read_text(encoding="utf-8"))
            items = data.get("items", []) if isinstance(data, dict) else []
            return [i for i in items if isinstance(i, dict)]
        except Exception:
            return []

    def _save_history(self, item: dict) -> None:
        """写入一条下载历史；同 kind + folder 覆盖旧记录。"""
        with self._history_lock:
            items = [i for i in self._load_history()
                     if not (i.get("kind") == item.get("kind") and i.get("folder") == item.get("folder"))]
            items.append(item)
            try:
                p = self._history_path()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError as e:
                logger.warning("保存下载历史失败：%s", e)

    def _find_preferences(self) -> Optional[Path]:
        """定位游戏身份文件 preferences.xml（游客号 + 昵称）。"""
        for d in game_data_dirs(self._launcher.game_root):
            p = d / "preferences.xml"
            if p.is_file():
                return p
        return None

    def _restore_preferences_path(self) -> Path:
        """恢复身份文件的写入位置：已有则原位覆盖，否则写我的文档标准位置。"""
        existing = self._find_preferences()
        if existing is not None:
            return existing
        return Path.home() / "Documents" / "Rusted Warfare" / "preferences.xml"

    def _installed_resources(self) -> list[dict]:
        """已下载且文件仍在本机的模组 / 地图清单（{title, url, kind}）。

        只含启动器下载过、且文件仍在本机的记录；
        手动放入的本地资源（无 URL）不参与。
        """
        mods: list[dict] = []
        for item in self._load_history():
            kind = item.get("kind", "mod")
            folder = item.get("folder", "")
            url = item.get("url", "")
            if kind not in ("mod", "map") or not folder or not url:
                continue
            ext = ".rwmod" if kind == "mod" else ".tmx"
            target = self._resource_root(kind) / f"{folder}{ext}"
            legacy = self._resource_root(kind) / folder
            if not (target.is_file() or legacy.is_dir()):
                continue  # 文件已被清除 / 手动删除，不参与分享
            mods.append({"title": item.get("title", folder), "url": url, "kind": kind})
        return mods

    def resource_local_installed(self) -> dict:
        """本地已下载的模组 / 地图清单，供前端生成分享同步码。"""
        return {"ok": True, "items": self._installed_resources()}

    def _backup_payload(self) -> dict:
        """组装备份数据：身份文件全文 + 已安装资源的下载 URL 清单。

        只含启动器下载过、且文件仍在本机的模组 / 地图 URL；
        手动放入的本地资源（无 URL）不会出现在备份里。
        """
        preferences_xml = ""
        pref = self._find_preferences()
        if pref is not None:
            try:
                preferences_xml = pref.read_text(encoding="utf-8", errors="ignore")
            except OSError as e:
                logger.warning("读取身份文件失败：%s", e)
        return {"preferences_xml": preferences_xml, "mods": self._installed_resources()}

    def _local_backup_path(self) -> Path:
        """本地离线备份文件（云端不可用时自动降级写入）。"""
        base = Path(__file__).resolve().parent.parent
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
        return base / "data" / "local_backup.json"

    def _load_local_backup(self) -> dict:
        """读取本地离线备份。"""
        try:
            data = json.loads(self._local_backup_path().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_local_backup(self, payload: dict) -> None:
        """写入本地离线备份（含备份时间，不校验登录注册）。"""
        try:
            p = self._local_backup_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(
                    {
                        "source": "local",
                        "backed_up_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        **payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("保存本地备份失败：%s", e)

    def account_backup_status(self) -> dict:
        """备份状态：身份文件 / 可备份资源 / 上次备份时间 / 当前模式。"""
        cfg = self._account_cfg()
        payload = self._backup_payload()
        local = self._load_local_backup()
        mode = "cloud" if cfg.get("token") else (
            "local" if local.get("preferences_xml") or local.get("mods") else "none"
        )
        return {
            "ok": True,
            "logged_in": bool(cfg.get("token")),
            "mode": mode,
            "auto_enabled": bool(self._config.get("account_backup_enabled", True)),
            "preferences_path": str(pref) if (pref := self._find_preferences()) else "",
            "preferences_exists": self._find_preferences() is not None,
            "backup_mods": len(payload["mods"]),
            "installed_mods": len(self.list_installed("mod")),
            "installed_maps": len(self.list_installed("map")),
            "last_backup_at": cfg.get("last_backup_at", "") or local.get("backed_up_at", ""),
        }

    def account_backup_now(self) -> dict:
        """立即备份：云端优先；云端不可用 / 未登录时自动降级为本地离线备份。

        本地备份不校验登录注册，内容与云端一致（身份文件 + 模组 URL 清单）。
        """
        cfg = self._account_cfg()
        payload = self._backup_payload()

        if cfg.get("token"):
            data = self._account_request("PUT", "/api/profile", payload)
            if data.get("ok"):
                cfg["last_backup_at"] = data.get("updated_at", "")
                self._config.set("account", cfg)
                data["mode"] = "cloud"
                data["mods"] = len(payload["mods"])
                return data
            logger.warning("云端备份不可用（%s），自动降级为本地备份", data.get("error"))

        self._save_local_backup(payload)
        return {
            "ok": True,
            "mode": "local",
            "mods": len(payload["mods"]),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def account_restore(self) -> dict:
        """恢复数据：云端优先；云端不可用 / 未登录时降级读取本地备份。"""
        cfg = self._account_cfg()

        if cfg.get("token"):
            data = self._account_request("GET", "/api/profile")
            if data.get("ok"):
                return self._apply_restore(data, "cloud")
            logger.warning("云端恢复不可用（%s），尝试本地备份", data.get("error"))
        else:
            data = None

        local = self._load_local_backup()
        if not local.get("preferences_xml") and not local.get("mods"):
            return {"ok": False, "error": "云端不可用且本机无备份，无法恢复"}
        return self._apply_restore(local, "local")

    def _apply_restore(self, data: dict, mode: str) -> dict:
        """按备份内容写回身份文件，并返回模组清单（云端 / 本地共用）。"""
        restored = {"preferences": False, "preferences_path": ""}
        xml = data.get("preferences_xml", "") or ""
        if xml:
            try:
                target = self._restore_preferences_path()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(xml, encoding="utf-8")
                restored = {"preferences": True, "preferences_path": str(target)}
            except OSError as e:
                return {"ok": False, "error": f"写回身份文件失败：{e}"}
        result = dict(data)
        result.setdefault("ok", True)
        result["restored"] = restored
        result["mode"] = mode
        return result

    def _auto_backup_after_game(self) -> None:
        """游戏进程退出后的自动备份。

        不校验登录注册：云端可用走云端，云端不可用 / 未登录自动降级为
        本地离线备份，后台静默执行。
        """
        if not bool(self._config.get("account_backup_enabled", True)):
            return

        def _run() -> None:
            try:
                res = self.account_backup_now()
                logger.info("游戏退出自动备份结果：mode=%s ok=%s", res.get("mode"), res.get("ok"))
            except Exception:
                logger.exception("游戏退出自动备份失败")

        threading.Thread(target=_run, daemon=True, name="auto-backup").start()

    # ==========================================================
    #  平台 Mod 与状态（配套服务：账号 + 模组 + 状态同 IP）
    # ==========================================================

    def _platform_base(self) -> str:
        """配套服务地址（与账号服务同源，一个 IP 下按 URL 区分功能）。"""
        cfg = self._account_cfg()
        return str(cfg.get("base_url") or "http://127.0.0.1:4123").rstrip("/")

    def get_platform_status(self) -> dict:
        """拉取状态页总数据（公网服务探测 + 本机资源 + 事件）。"""
        data = self._account_request("GET", "/api/status")
        if data.get("ok") is False and "error" in data:
            return data
        return {"ok": True, "data": data}

    def search_platform_mods(self, keyword: str = "", kind: str = "", page: int = 1) -> dict:
        """搜索平台自有 Mod / 地图（数据源 2，与 rtsbox 并列）。

        返回结构与 rtsbox 搜索结果对齐，条目额外带 mod_id 供下载使用。
        """
        import urllib.parse

        page = max(1, int(page or 1))
        kw = urllib.parse.quote((keyword or "").strip())
        path = f"/api/modsList?keyword={kw}&kind={kind}&page={page}&page_size=20"
        data = self._account_request("GET", path)
        if data.get("ok") is False and "error" in data:
            return {"items": [], "total": 0, "error": data.get("error")}

        items = data.get("items") or []
        cache = self._installed_cache(kind or "mod")
        enriched: list[dict] = []
        for it in items:
            title = it.get("title", "untitled")
            folder = _sanitize_folder_name(title)
            enriched.append({
                "mod_id": it.get("id"),
                "title": title,
                "kind": it.get("kind") or kind,
                "version": it.get("version") or _extract_version(title),
                "description": it.get("description", ""),
                "uploader": it.get("uploader", ""),
                "file_size": it.get("file_size", 0),
                "downloads": it.get("downloads", 0),
                "folder": folder,
                "installed": folder in cache,
                "created_at": it.get("created_at", ""),
            })
        return {"items": enriched, "total": data.get("total", len(items)), "error": None}

    def platform_mod_download(self, mod_id: int, title: str, kind: str = "mod") -> dict:
        """下载平台 Mod（.rwmod 格式，复用下载管理器：进度 / 限速 / 格式校验）。

        与 rtsbox 资源下载的区别：平台地图同样是 .rwmod 单文件，
        不按 .tmx 校验；下载计数由服务端累计。
        """
        if kind not in ("mod", "map"):
            return {"ok": False, "error": "未知资源类型"}
        try:
            mod_id = int(mod_id)
        except (ValueError, TypeError):
            return {"ok": False, "error": "模组 ID 无效"}
        if not title:
            return {"ok": False, "error": "缺少模组标题"}

        folder = _sanitize_folder_name(title)
        ext = ".rwmod"
        target_file = self._resource_root(kind) / f"{folder}{ext}"
        legacy_dir = self._resource_root(kind) / folder
        if target_file.exists() or legacy_dir.is_dir():
            return {"ok": False, "error": f"已存在：{folder}", "installed": True}

        url = f"{self._platform_base()}/api/modsDownload?mod_id={mod_id}"
        logger.info("开始下载平台%s：%s -> %s", kind, title, target_file)
        limit_kbps = float(self._config.get("download_speed_limit_kbps") or 0.0)
        tmp_zip = self._tmp_dir() / f"{folder}.tmp"

        digest = hashlib.md5(f"platform:{kind}:{mod_id}".encode("utf-8")).hexdigest()[:10]
        task_id = f"pl_{kind}_{digest}"

        self._downloader.submit(
            task_id=task_id,
            url=url,
            dest=tmp_zip,
            store_to=target_file,
            accept_ext=ext,
            speed_limit_bps=limit_kbps * 1024 if limit_kbps > 0 else 0.0,
        )
        with self._history_lock:
            self._pending_history[task_id] = {
                "kind": kind,
                "title": title,
                "folder": folder,
                "url": url,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        return {"ok": True, "task_id": task_id, "folder": folder}

    def platform_mod_feedback(self, mod_id: int, content: str) -> dict:
        """提交平台 Mod 反馈（需登录）。"""
        if not (self._account_cfg().get("token") or ""):
            return {"ok": False, "error": "请先登录账号后再反馈"}
        content = (content or "").strip()
        if not content:
            return {"ok": False, "error": "反馈内容不能为空"}
        return self._account_request(
            "POST", f"/api/modsFeedback?mod_id={int(mod_id)}", {"content": content[:500]}
        )

    def platform_mod_feedbacks(self, mod_id: int) -> dict:
        """平台 Mod 反馈列表（公开）。"""
        data = self._account_request("GET", f"/api/modsFeedbacks?mod_id={int(mod_id)}")
        if data.get("ok") is False and "error" in data:
            return data
        return {"ok": True, "data": data}

    def platform_mod_upload(
        self, title: str, kind: str = "mod", version: str = "", description: str = ""
    ) -> dict:
        """上传平台 Mod：弹原生文件选择框选 .rwmod，即传即上架（需登录）。"""
        import os
        import urllib.error
        import urllib.parse
        import urllib.request

        token = self._account_cfg().get("token") or ""
        if not token:
            return {"ok": False, "error": "请先登录账号后再上传"}
        title = (title or "").strip()
        if not title:
            return {"ok": False, "error": "请填写模组标题"}
        if kind not in ("mod", "map"):
            return {"ok": False, "error": "类型必须是 mod 或 map"}
        if self._window is None:
            return {"ok": False, "error": "窗口未就绪"}
        try:
            import webview

            picked = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=("模组文件 (*.rwmod)",),
                allow_multiple=False,
            )
        except Exception as e:
            return {"ok": False, "error": f"无法打开文件选择框: {e}"}
        if not picked:
            return {"ok": False, "error": "已取消选择"}
        file_path = picked[0] if isinstance(picked, (list, tuple)) else picked
        if not file_path or not os.path.isfile(file_path):
            return {"ok": False, "error": "文件不存在"}
        name = os.path.basename(str(file_path))
        if not name.lower().endswith(".rwmod"):
            return {"ok": False, "error": "仅支持 .rwmod 格式的模组文件"}
        try:
            with open(file_path, "rb") as f:
                raw = f.read()
        except Exception as e:
            return {"ok": False, "error": f"读取文件失败: {e}"}
        if not raw:
            return {"ok": False, "error": "文件内容为空"}

        params = urllib.parse.urlencode({
            "title": title,
            "kind": kind,
            "version": (version or "").strip(),
            "description": (description or "").strip(),
            "file_name": name,
        })
        req = urllib.request.Request(
            url=f"{self._platform_base()}/api/modsUpload?{params}",
            data=raw,
            headers={
                "Content-Type": "application/octet-stream",
                "Authorization": "Bearer " + token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode("utf-8", errors="replace"))
                if isinstance(payload, dict) and payload.get("error"):
                    payload["error"] = _decorate_error(payload["error"])
                    if payload.get("detail"):
                        payload["detail"] = _decorate_error(payload["detail"])
                    return payload
                return {"ok": False, "error": _decorate_error(f"服务返回 HTTP {e.code}")}
            except Exception:
                return {"ok": False, "error": _decorate_error(f"服务返回 HTTP {e.code}")}
        except Exception as e:
            return {"ok": False, "error": _decorate_error(f"上传失败: {e}")}

    # ==========================================================
    #  窗口控制
    # ==========================================================

    def minimize_window(self) -> None:
        if self._window is not None:
            self._window.minimize()

    def toggle_maximize(self) -> None:
        """切换窗口最大化 / 还原。"""
        if self._window is None:
            return
        try:
            if hasattr(self._window, "toggle_maximize"):
                self._window.toggle_maximize()
            else:
                if self._maximized:
                    self._window.restore()
                else:
                    self._window.maximize()
        except Exception as e:
            logger.warning("切换窗口最大化失败：%s", e)

    def get_window_state(self) -> dict:
        """返回窗口当前状态（前端标题栏初始化用）。"""
        return {"maximized": bool(self._maximized)}

    def _bind_window_events(self) -> None:
        """绑定窗口最大化 / 还原事件，维护 _maximized 并推送给前端。"""
        if self._window is None:
            return
        try:
            self._window.events.maximized += self._on_window_maximized
            self._window.events.restored += self._on_window_restored
        except Exception as e:
            logger.warning("绑定窗口最大化事件失败：%s", e)

    def _on_window_maximized(self) -> None:
        self._maximized = True
        self._push_maximize_state()

    def _on_window_restored(self) -> None:
        self._maximized = False
        self._push_maximize_state()

    def _push_maximize_state(self) -> None:
        """把最大化状态广播给前端（rw:window:maxstate 事件）。"""
        if self._window is None:
            return
        try:
            flag = "true" if self._maximized else "false"
            self._window.evaluate_js(
                "window.dispatchEvent(new CustomEvent('rw:window:maxstate', "
                f"{{detail: {{maximized: {flag}}}}}));"
            )
        except Exception:
            pass

    def close_window(self) -> None:
        if self._window is not None:
            self._window.destroy()

    def begin_window_drag(self) -> bool:
        """兼容保留：实际拖动由 pywebview 通过 .pywebview-drag-region class 自动处理。

        只要给前端标题栏加 class="pywebview-drag-region"，
        pywebview 会在 mousedown 时自动调后端 `pywebviewMoveWindow` 移动窗口。
        本方法保留为 no-op，仅用于旧前端代码兼容。
        """
        return True

    def open_url(self, url: str) -> bool:
        """用系统默认浏览器打开外部链接（用于广告跳转等）。"""
        if not url or not isinstance(url, str):
            return False
        url = url.strip()
        if not url:
            return False
        # 仅允许 http(s) 协议，避免被滥用执行本地程序
        if not (url.startswith("http://") or url.startswith("https://")):
            return False
        try:
            return bool(webbrowser.open(url, new=2, autoraise=True))
        except Exception:
            return False

    def pick_background_image(self) -> dict:
        """选择一张图片作为启动器背景，复制到应用目录后返回新路径。"""
        if self._window is None:
            return {"ok": False, "error": "窗口未就绪"}
        try:
            files = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=(
                    "图片文件 (*.png;*.jpg;*.jpeg;*.bmp;*.webp)",
                    "所有文件 (*.*)",
                ),
            )
        except Exception as e:
            logger.warning("打开文件选择框失败：%s", e)
            return {"ok": False, "error": f"打开文件选择框失败：{e}"}
        if not files:
            return {"ok": False, "canceled": True}
        src = Path(files[0])
        if not src.is_file():
            return {"ok": False, "error": "所选文件不存在"}

        # 复制到应用目录 backgrounds/（绿色便携，随启动器移动）
        bg_dir = self._backgrounds_dir()
        try:
            bg_dir.mkdir(parents=True, exist_ok=True)
            suffix = src.suffix.lower() or ".png"
            dest = bg_dir / f"bg{suffix}"
            shutil.copy2(src, dest)
        except OSError as e:
            logger.error("复制背景图失败：%s", e)
            return {"ok": False, "error": f"复制背景图失败：{e}"}
        logger.info("已设置背景图：%s", dest)
        # 配置里只存相对文件名（如 "bg.jpg"），解析时统一定位到应用
        # backgrounds/ 目录——存绝对路径会在移动/换盘后失效（历史 bug）
        rel_name = dest.name
        appearance = self._config.get("appearance")
        if not isinstance(appearance, dict):
            appearance = {}
        appearance["background_image"] = rel_name
        self._config.set("appearance", appearance)
        self._config.save()
        return {"ok": True, "path": rel_name, "data_uri": self._img_data_uri(dest)}

    def _backgrounds_dir(self) -> Path:
        """背景图目录：应用根目录/backgrounds（绿色便携，随启动器移动）。"""
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
        else:
            base = Path(__file__).resolve().parent.parent
        return base / "backgrounds"

    def _resolve_background_path(self, stored: str) -> Optional[Path]:
        """把配置里的 background_image 解析为实际文件路径。

        - 相对值：直接定位应用 backgrounds/ 目录
        - 绝对路径：优先原样使用；失效时按同名文件在 backgrounds/ 兜底
          （兼容旧版本写入绝对路径、启动器整体搬迁的场景）
        """
        if not stored:
            return None
        bg_dir = self._backgrounds_dir()
        p = Path(stored)
        candidates = []
        if p.is_absolute():
            candidates.append(p)
            candidates.append(bg_dir / p.name)
        else:
            candidates.append(bg_dir / p)
        for c in candidates:
            try:
                if c.is_file():
                    return c
            except OSError:
                continue
        return None

    def background_image_data(self) -> dict:
        """返回当前背景图的 base64 data URI（供前端直接嵌入 CSS）。

        未设置背景图或文件丢失时返回空串。因为 pywebview 以 localhost
        HTTP 方式加载页面，file:// 与相对路径引用本地图片都会失败，
        所以统一用 data URI 传递。
        """
        path = ""
        try:
            appearance = self._config.get("appearance")
            if isinstance(appearance, dict):
                path = appearance.get("background_image", "") or ""
        except Exception:
            path = ""
        resolved = self._resolve_background_path(path) if path else None
        if resolved is None:
            if path:
                logger.warning("背景图文件不存在：%s", path)
            return {"ok": True, "data": ""}
        try:
            return {"ok": True, "data": self._img_data_uri(resolved)}
        except OSError as e:
            logger.error("读取背景图失败：%s", e)
            return {"ok": True, "data": ""}

    @staticmethod
    def _img_data_uri(path: Path) -> str:
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"

    # ==========================================================
    #  内部：进度 / 状态推送
    # ==========================================================

    def _dispatch_progress(self, task_id: str, downloaded: int, total: int) -> None:
        if self._window is None:
            return
        # 顺便带上 speed
        speed = 0.0
        try:
            t = self._downloader.get(task_id)
            if t is not None:
                speed = float(getattr(t, "speed_bps", 0.0) or 0.0)
        except Exception:
            speed = 0.0
        payload = _safe_js_payload(
            {"task_id": task_id, "downloaded": downloaded, "total": total, "speed": speed}
        )
        try:
            self._window.evaluate_js(
                f"window.dispatchEvent(new CustomEvent('{EVT_PROGRESS}', {{detail:{payload}}}));"
            )
        except Exception:
            pass

    def _dispatch_status(self, task_id: str, status: str, error: Optional[str]) -> None:
        # 模组 / 地图下载完成时刷新安装缓存
        if status == TaskStatus.COMPLETED.value and task_id.startswith(("mod_", "map_")):
            kind = "mod" if task_id.startswith("mod_") else "map"
            self._invalidate_cache(kind)
            # 下载成功：把登记的资源信息写入历史（备份清单数据源）
            with self._history_lock:
                item = self._pending_history.pop(task_id, None)
            if item is not None:
                self._save_history(item)
            # 通知前端刷新已安装列表
            if self._window is not None:
                payload = _safe_js_payload({"kind": kind, "task_id": task_id})
                try:
                    self._window.evaluate_js(
                        f"window.dispatchEvent(new CustomEvent('rw:installed:changed', {{detail:{payload}}}));"
                    )
                except Exception:
                    pass
        if status == TaskStatus.COMPLETED.value:
            self._toast("下载完成", task_id)
        elif status == TaskStatus.FAILED.value:
            if error and error.startswith("REJECT:"):
                # 格式校验被拒绝：前端弹窗提示
                self._dispatch_blocked(error[len("REJECT:"):].strip())
            else:
                self._toast(f"下载失败：{error or '未知错误'}", "error")

        if status == TaskStatus.NEEDS_CONFIRM.value:
            # 模组包嵌套检测：附带资源信息，前端据此弹出确认框
            task = self._downloader.get(task_id)
            kind = "mod" if task_id.startswith("mod_") else "map"
            with self._history_lock:
                info = self._pending_history.get(task_id, {})
            payload = _safe_js_payload(
                {
                    "task_id": task_id,
                    "status": status,
                    "error": error,
                    "kind": kind,
                    "title": info.get("title", ""),
                    "folder": info.get("folder", ""),
                    "top": getattr(task, "nested_top", "") if task else "",
                }
            )
        else:
            payload = _safe_js_payload(
                {"task_id": task_id, "status": status, "error": error}
            )
        if self._window is None:
            return
        try:
            self._window.evaluate_js(
                f"window.dispatchEvent(new CustomEvent('{EVT_STATUS}', {{detail:{payload}}}));"
            )
        except Exception:
            pass

    def _toast(self, message: str, kind: str = "success") -> None:
        if self._window is None:
            return
        payload = _safe_js_payload({"message": message, "kind": kind})
        try:
            self._window.evaluate_js(
                f"window.dispatchEvent(new CustomEvent('{EVT_TOAST}', {{detail:{payload}}}));"
            )
        except Exception:
            pass

    def _dispatch_blocked(self, message: str) -> None:
        """格式校验被拒绝：前端以弹窗提示（区别于普通 toast）。"""
        if self._window is None:
            return
        payload = _safe_js_payload({"message": message})
        try:
            self._window.evaluate_js(
                f"window.dispatchEvent(new CustomEvent('rw:blocked', {{detail:{payload}}}));"
            )
        except Exception:
            pass

    # ==========================================================
    #  版本管理
    # ==========================================================

    def get_version_catalog(self) -> dict:
        """一次获取清单及本地安装；远程失败时仍展示本地版本和错误原因。"""
        installed = [v.to_dict() for v in self._version_manager.get_installed_versions()]
        current = self.get_current_version()
        try:
            editions = [e.to_dict() for e in self._version_manager.get_editions()]
            return {"ok": True, "editions": editions, "installed_versions": installed,
                    "current_version": current}
        except Exception as e:
            logger.error("获取版本清单失败：%s", e)
            return {"ok": False, "error": str(e), "editions": [],
                    "installed_versions": installed, "current_version": current}

    def get_versions(self) -> dict:
        """获取版本列表（远程版本和已安装版本）。"""
        try:
            remote_versions = self._version_manager.get_remote_versions()
            remote_list = [v.to_dict() for v in remote_versions]
            installed_versions = self._version_manager.get_installed_versions()
            installed_list = [v.to_dict() for v in installed_versions]
            current_version = self.get_current_version()
            return {
                "ok": True,
                "remote_versions": remote_list,
                "installed_versions": installed_list,
                "current_version": current_version,
                "total_remote": len(remote_list),
                "total_installed": len(installed_list),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "remote_versions": [],
                "installed_versions": [],
                "current_version": None,
                "total_remote": 0,
                "total_installed": 0,
            }

    def get_editions(self) -> list:
        """获取编辑版列表。"""
        try:
            editions = self._version_manager.get_editions()
            return [e.to_dict() for e in editions]
        except Exception as e:
            logger.error("获取编辑版列表失败：%s", e)
            return []

    def get_remote_versions(self, edition_name: Optional[str] = None) -> list:
        """获取远程版本列表。
        
        Args:
            edition_name: 编辑版名称（可选），如果指定则只返回该编辑版下的版本
        """
        try:
            versions = self._version_manager.get_remote_versions(edition_name)
            return [v.to_dict() for v in versions]
        except Exception as e:
            logger.error("获取远程版本列表失败：%s", e)
            return []

    def get_installed_versions(self, edition_name: Optional[str] = None) -> list:
        """获取已安装版本列表。
        
        Args:
            edition_name: 编辑版名称（可选），如果指定则只返回该编辑版下的已安装版本
        """
        try:
            versions = self._version_manager.get_installed_versions(edition_name)
            return [v.to_dict() for v in versions]
        except Exception as e:
            logger.error("获取已安装版本列表失败：%s", e)
            return []

    def get_version_details(self, version: str) -> dict:
        """获取指定版本的详细信息。"""
        try:
            # 在远程版本中查找
            remote_versions = self._version_manager.get_remote_versions()
            for v in remote_versions:
                if v.version == version:
                    return v.to_dict()
            
            # 在已安装版本中查找
            installed_versions = self._version_manager.get_installed_versions()
            for v in installed_versions:
                if v.version == version:
                    return v.to_dict()
            
            return {}
        except Exception as e:
            logger.error("获取版本详情失败：%s", e)
            return {}

    def get_version_install_path(self, version: str) -> Optional[str]:
        """获取版本安装路径（目录已存在时返回，否则 None）。"""
        try:
            p = self._version_manager.version_dir(version)
            return str(p) if p.is_dir() else None
        except Exception as e:
            logger.error("获取版本安装路径失败：%s", e)
            return None

    def is_version_installed(self, version: str) -> bool:
        """检查版本是否已安装。"""
        try:
            installed = self._version_manager.get_installed_versions()
            return any(v.version == version for v in installed)
        except Exception as e:
            logger.error("检查版本安装状态失败：%s", e)
            return False

    def get_current_version(self, edition_name: Optional[str] = None) -> Optional[str]:
        """获取当前选中的版本号；选中版本目录已不存在时返回 None。"""
        try:
            version = str(self._config.get("game_selected_version") or "").strip()
            if version and self._version_manager.is_version_installed(version):
                return version
            return None
        except Exception as e:
            logger.error("获取当前版本失败：%s", e)
            return None

    def switch_version(self, version: str, edition_name: Optional[str] = None) -> dict:
        """切换当前使用的版本（仅改变启动定位，不移动任何文件）。"""
        try:
            version = str(version or "").strip()
            if not version:
                return {"ok": False, "error": "未指定版本号", "version": None}
            if not self._version_manager.is_version_installed(version):
                return {
                    "ok": False,
                    "error": f"版本 {version} 未安装，请先下载安装",
                    "version": None,
                }
            if self._monitor.running:
                return {
                    "ok": False,
                    "error": "游戏正在运行，请先结束游戏再切换版本",
                    "version": None,
                }
            vdir = self._version_manager.version_dir(version)
            new_launcher = GameLauncher(
                game_dir=vdir,
                exe_name=str(self._config.get("game_exe_name") or "RustedWarfare.exe"),
                config=self._config,
            )
            if not new_launcher.launchable():
                return {
                    "ok": False,
                    "error": f"版本 {version} 目录中未找到游戏主程序",
                    "version": None,
                }
            logger.info("切换游戏版本：%s（%s）", version, vdir)
            self._config.set("game_selected_version", version)
            self._config.save()
            self._launcher = new_launcher
            self._monitor.bind_launcher(new_launcher)
            self._toast(f"已切换到版本 {version}", "success")
            return {
                "ok": True,
                "message": f"成功切换到版本 {version}",
                "version": version,
                "install_path": str(vdir),
                "current_version": version,
            }
        except Exception as e:
            logger.error("切换版本失败：%s", e)
            return {
                "ok": False,
                "error": f"切换版本失败：{e}",
                "version": None,
            }

    def launch_version(self, version: str, args: str = "") -> dict:
        """启动指定版本的游戏（原生 exe 或 Java 版 jar 均可）。"""
        try:
            version = str(version or "").strip()
            if not version or not self._version_manager.is_version_installed(version):
                return {
                    "ok": False,
                    "error": f"版本 {version} 未安装",
                    "version": None,
                }

            version_path = self._version_manager.version_dir(version)
            version_launcher = GameLauncher(
                game_dir=version_path,
                exe_name=str(self._config.get("game_exe_name") or "RustedWarfare.exe"),
                config=self._config,
            )
            # 游戏可能在 zip 解压出的一层子目录内，交给启动器智能定位
            jar = version_launcher.java_jar_path
            if version_launcher.exists():
                use_java = False
                target = version_launcher.exe_path
            elif jar is not None:
                use_java = True
                target = jar
            else:
                return {
                    "ok": False,
                    "error": f"在版本 {version} 目录中未找到可执行文件或游戏 jar",
                    "version": None,
                }
            mode = "java" if use_java else "auto"

            if args != self._config.get("last_launch_args"):
                self._config.set("last_launch_args", args or "")
                self._config.save()

            logger.info("启动版本 %s：模式=%s 目录=%s 参数=%r", version, mode, version_path, args or "")
            try:
                proc = version_launcher.launch(args or "", mode=mode)
            except JavaRuntimeMissingError as e:
                return {
                    "ok": False,
                    "version": version,
                    "needs_jre": True,
                    "install_dir": e.install_dir,
                    "error": f"版本 {version} 需要 Java 运行环境：{e}。"
                    f"请先到首页安装 JRE，或改用自带 JRE 的版本",
                }
            pid = proc.pid if proc is not None else None
            # 启动成功即把启动定位切到该版本
            self._config.set("game_selected_version", version)
            self._config.save()
            self._launcher = version_launcher
            self._monitor.bind_launcher(version_launcher)
            self._monitor.begin(watch_pid=pid if use_java else None)

            if self._window is not None:
                try:
                    self._window.minimize()
                except Exception:
                    pass

            return {
                "ok": True,
                "message": f"成功启动版本 {version}",
                "version": version,
                "mode": "java" if use_java else "exe",
                "path": str(target),
            }

        except Exception as e:
            logger.error("启动版本失败：%s", e)
            return {
                "ok": False,
                "error": f"启动版本失败：{e}",
                "version": None,
            }

    def quick_launch(self, version: Optional[str] = None, args: str = "") -> dict:
        """快速启动游戏：指定版本或当前选中版本。"""
        try:
            target_version = version or self.get_current_version()
            if not target_version:
                return {
                    "ok": False,
                    "error": "没有已安装且选中的游戏版本，请先在首页选择版本",
                    "version": None,
                }
            return self.launch_version(target_version, args)
        except Exception as e:
            logger.error("快速启动失败：%s", e)
            return {
                "ok": False,
                "error": f"快速启动失败：{e}",
                "version": None,
            }

    def install_version(self, version: str, edition_name: Optional[str] = None) -> dict:
        """下载并安装指定游戏版本（任务化，立即返回 task_id）。

        版本包下载走全局下载队列，解压到 versions/<版本>/ 目录，
        完成后自动合并其他版本的 mods/maps/saves 并切换启动定位。
        """
        try:
            version = str(version or "").strip()
            info = self._version_manager.find_remote_version(version, edition_name)
            if info is None or not info.url:
                return {
                    "ok": False,
                    "error": f"远程版本 {version} 未找到或没有下载地址",
                    "task_id": None,
                }
            if self._version_manager.is_version_installed(version):
                return {
                    "ok": True,
                    "already_installed": True,
                    "version": version,
                    "task_id": None,
                    "install_path": str(self._version_manager.version_dir(version)),
                }

            safe = re.sub(r'[^A-Za-z0-9._-]', "_", version)
            task_id = f"ver_install_{safe}"
            if len(task_id) > 60:
                task_id = "ver_install_" + hashlib.md5(version.encode("utf-8")).hexdigest()[:12]
            existing = self._downloader.get(task_id)
            if existing is not None and existing.status in (
                "pending", "downloading", "extracting",
            ):
                return {"ok": True, "task_id": task_id, "version": version, "reused": True}

            version_dir = self._version_manager.version_dir(version)
            version_dir.mkdir(parents=True, exist_ok=True)
            tmp_zip = self._tmp_dir() / f"version-{safe}.zip"
            limit_kbps = float(self._config.get("download_speed_limit_kbps") or 0.0)

            def _on_done(tid: str, ok: bool, err: Optional[str]) -> None:
                if ok:
                    self._save_history({
                        "kind": "version",
                        "title": f"版本 {version}",
                        "folder": version,
                        "url": info.url or "",
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                self._on_game_version_installed(tid, ok, err, version, version_dir)

            self._downloader.submit(
                task_id=task_id,
                url=info.url,
                dest=tmp_zip,
                extract_to=version_dir,
                speed_limit_bps=limit_kbps * 1024 if limit_kbps > 0 else 0.0,
                on_done=_on_done,
            )
            logger.info("提交游戏版本安装：%s（task=%s, url=%s）", version, task_id, info.url)
            return {
                "ok": True,
                "task_id": task_id,
                "version": version,
                "file_size": info.file_size,
                "description": info.description,
            }
        except Exception as e:
            logger.error("启动版本安装失败：%s", e)
            return {
                "ok": False,
                "error": f"启动版本安装失败：{e}",
                "task_id": None,
            }

    def uninstall_version(self, version: str) -> dict:
        """卸载指定版本；当前选中版本禁止卸载。"""
        try:
            version = str(version or "").strip()
            if not version or not self._version_manager.is_version_installed(version):
                return {
                    "ok": False,
                    "error": f"版本 {version} 未安装",
                    "version": None,
                }
            if self.get_current_version() == version:
                return {
                    "ok": False,
                    "error": f"版本 {version} 正在使用，请先切换到其他版本再卸载",
                    "version": None,
                }
            if self._monitor.running:
                return {
                    "ok": False,
                    "error": "游戏正在运行，请先结束游戏再卸载版本",
                    "version": None,
                }
            ok, err = self._version_manager.uninstall_version(version)
            if not ok:
                return {"ok": False, "error": err or f"卸载版本 {version} 失败", "version": None}
            self._toast(f"版本 {version} 已卸载", "success")
            return {
                "ok": True,
                "message": f"成功卸载版本 {version}",
                "version": version,
            }
        except Exception as e:
            logger.error("卸载版本失败：%s", e)
            return {
                "ok": False,
                "error": f"卸载版本失败：{e}",
                "version": None,
            }

    def get_available_installations(self) -> dict:
        """获取本机所有已安装游戏版本。"""
        try:
            current = self.get_current_version()
            installations = [
                {
                    "version": v.version,
                    "path": v.install_path,
                    "install_date": v.install_date,
                    "current": v.version == current,
                }
                for v in self._version_manager.get_installed_versions()
            ]
            return {
                "ok": True,
                "installations": installations,
                "total": len(installations),
            }
        except Exception as e:
            logger.error("获取可用安装版本失败：%s", e)
            return {
                "ok": False,
                "error": f"获取可用安装版本失败：{e}",
                "installations": [],
                "total": 0,
            }

    def clear_version_cache(self) -> dict:
        """清除版本管理器缓存。"""
        try:
            self._version_manager.clear_cache()
            return {
                "ok": True,
                "message": "版本缓存已清除"
            }
        except Exception as e:
            logger.error("清除版本缓存失败：%s", e)
            return {
                "ok": False,
                "error": f"清除版本缓存失败：{e}"
            }

    def check_version_manifest(self) -> dict:
        """立即重新拉取一次版本清单，用于设置页的连通性检查。

        成功返回分支数量，失败返回具体错误（HTTP 状态 / 无法访问 / 解析失败）。
        """
        try:
            editions = self._version_manager.get_editions(use_cache=False)
            return {
                "ok": True,
                "editions": len(editions),
            }
        except Exception as e:
            logger.error("版本清单连通性检查失败：%s", e)
            return {
                "ok": False,
                "editions": 0,
                "error": str(e),
            }

    def compare_versions(self, version1: str, version2: str) -> dict:
        """比较两个版本号的大小。"""
        try:
            result = self._version_manager.compare_versions(version1, version2)
            
            if result == -1:
                comparison = "小于"
            elif result == 0:
                comparison = "等于"
            else:
                comparison = "大于"
            
            return {
                "ok": True,
                "version1": version1,
                "version2": version2,
                "comparison": comparison,
                "result": result
            }
        except Exception as e:
            logger.error("比较版本失败：%s", e)
            return {
                "ok": False,
                "error": f"比较版本失败：{e}",
                "version1": version1,
                "version2": version2,
                "comparison": "未知",
                "result": None
            }
