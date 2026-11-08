"""配置管理：JSON 持久化，支持便携模式（配置文件位于启动器同目录）。"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 应用版本信息（单一来源，前端"关于"页从后端读取，避免硬编码脱节）
APP_VERSION = "3.10"


def _app_build_date() -> str:
    """构建日期：优先读打包时写入的 build_meta.json，读不到用回退值。"""
    fallback = "2026-08-25"
    try:
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        meta = json.loads((base / "build_meta.json").read_text(encoding="utf-8"))
        return str(meta.get("build_date") or fallback)
    except Exception:
        return fallback


APP_BUILD_DATE = _app_build_date()

# 默认配置（首次启动使用）
DEFAULT_CONFIG: dict[str, Any] = {
    # 游戏相关
    "game_install_path": "D:\\RustedWarfare",
    "game_exe_name": "RustedWarfare.exe",
    # 当前选中的游戏版本：空字符串表示取版本清单里的 latest_version
    "game_selected_version": "",

    # 下载限速（KB/s，0 表示不限速）
    "download_speed_limit_kbps": 0,

    # UI
    "last_launch_args": "",
    "close_behavior": "ask",  # "ask"=每次询问 / "minimize"=最小化 / "exit"=退出
    "fullscreen_tutorial_seen": False,  # 是否已看过全屏使用教程（看过则不再自动弹）

    # 窗口初始尺寸（main.py 创建窗口时读取）
    "window": {
        "width": 1280,
        "height": 800,
    },

    # 免责声明：是否已阅读（首次启动开屏告知后置 True）
    "disclaimer_seen": False,

    # 外观自定义
    "appearance": {
        "theme": "light",        # light | dark
        "density": "comfortable", # comfortable | compact
        "background_image": "",   # 自定义背景图绝对路径，空 = 无
        "panel_opacity": 100,     # 面板透明度 0-100（100=完全不透明）
        "home_modules": {         # 首页模块显示开关
            "launch": True,       # 启动游戏区
            "download": True,     # 游戏下载区
        },
    },

    # Locale Emulator / 中文输入助手 相关功能已移除（见 git 历史）

    # 服务可用性监控：启动器从该地址拉取各公网服务的健康状态
    # 由配套服务自带 /api/status 提供（Go 版 / Python 版均可）
    "health_service": {
        "base_url": "http://server.cqfishnet.cn:48117",  # 监控服务地址（配套服务自带 /api/status）
        "timeout": 5,                            # HTTP 请求超时（秒）
    },

    # FRP 内网穿透：把本机游戏端口映射到公网
    "frp": {
        "enabled": False,                # 启动器启动时是否自动启动 frpc
        "server_addr": "",   # frp server 地址（旧默认 frps.cqfishnet.cn 已下线，改由用户自填）
        "server_port": 7000,            # frp server 端口
        "auth_token": "",                # 鉴权 token（server 端开启校验时填）
        "proxy_name": "rw-game",         # 隧道名（frp server 端用作转发名）
        "proxy_type": "tcp",             # tcp / udp
        "local_ip": "127.0.0.1",         # 本地监听地址
        "local_port": 5123,              # 本地游戏端口
        "frpc_path": "",                 # 留空 = 自动用 binaries/frpc/frpc.exe
    },

    # 云端账号服务（登录注册 + 玩家数据备份）
    # 注册仅需用户名 + 密码（面向学生，无需邮箱 / 手机号）
    "account": {
        "base_url": "http://server.cqfishnet.cn:48117",  # 公网默认；本地调试改 http://127.0.0.1:4123
        "timeout": 5,                          # HTTP 请求超时（秒）
        "username": "",                        # 当前登录账号（空 = 未登录）
        "token": "",                           # 会话 token（本地保存）
        "last_backup_at": "",                  # 最近一次云端备份时间
    },

    # 账号自动备份：游戏关闭后把游客身份 + 模组 URL 清单自动上传云端
    "account_backup_enabled": True,

    # 末忆铁锈盒子搜索：优先走后端代理（带缓存降级），失败回退本地直连
    "rtsbox_proxy_enabled": True,

    # 模组分享同步码：默认有效期（小时，对应后端 SHARE_CODE_TTL_HOURS）
    "share_code_ttl_hours": 168,

    # 更新检查：从版本公告页拉取版本号与更新介绍
    # 公告格式：JSON（顶层 latest_version / versions）或纯文本两行（version:X.X.X / info:<更新内容>）
    # 旧公告页 server-vs-ot.cqfishnet.cn 已确认下线（三家公共 DNS 均无记录），故不再提供默认地址；
    # 留空时 check_update() 直接返回「未配置更新检查地址」，不会产生任何无效请求
    "update_check": {
        "url": "",  # 留空 = 不检查更新；如需启用请填写可用的公告页地址
        "timeout": 5,                                       # HTTP 请求超时（秒）
    },

    # 游戏本体版本清单：独立于启动器更新检查，从该 JSON 拉取游戏各版本下载地址
    # 格式与 version_manager 兼容的 editions 结构：{"editions":{"default":{"latest_version":"...","versions":{...}}}}
    "game_version_list": {
        "url": "https://cdn.cqfishnet.cn/windows.json",  # 游戏版本清单地址（CDN 镜像站）
        "timeout": 5,                                       # HTTP 请求超时（秒）
    },

    # Java 版（简体中文增强版）运行环境
    "java_runtime": {
        "mode": "auto",           # auto=exe 优先、无 exe 有 jar 走 Java；java=优先 Java 版；exe=只用原生 exe
        "auto_download": True,    # 缺 JRE 且本机/游戏目录都无 Java 时，自动从 Adoptium 下载安装
        "feature_version": 21,    # 自动下载的 JRE 大版本（LTS，默认 UTF-8 避免中文乱码）
        "install_jvm_dir": "jvm64",  # JRE 安装到游戏根目录的哪个子目录
    },

    # 节日特别主题：仅在法定假期当天自动切换点缀配色
    # 数据来源：联网同步 → 本地缓存 → 内置兜底表（backend/festival.py），逐级降级
    "festival_theme": {
        "enabled": True,          # 关闭后不应用任何节日配色
        "api_url": "https://timor.tech/api/holiday/year/{year}",  # {year} 会被替换为当前年份
        "timeout": 5,             # HTTP 请求超时（秒）
        "cache_max_age_days": 30, # 本地缓存有效期（天），超期则重新联网同步
    },
}


class Config:
    """线程安全的 JSON 配置管理器。"""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.path: Path = Path(config_path) if config_path else self._default_config_path()
        self._lock = threading.RLock()
        self._data: dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))  # 深拷贝
        self.load()

    @staticmethod
    def _default_config_path() -> Path:
        """便携模式：配置文件放启动器同目录。"""
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
        else:
            base = Path(__file__).resolve().parent.parent
        return base / "config.json"

    def load(self) -> None:
        """加载配置，缺失字段由默认值补齐。"""
        with self._lock:
            if not self.path.exists():
                return
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    stored = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                # 配置损坏，备份后回退默认值
                logger.warning("配置文件解析失败（%s），已备份并回退默认值", e)
                try:
                    self.path.rename(self.path.with_suffix(".json.bak"))
                except OSError:
                    pass
                return

            # 浅合并顶层
            merged = {**self._data, **stored}
            # 深合并 window / appearance / java_runtime 字典
            # （这样默认值里的新字段升级后能自动补到旧配置文件）
            for sub_key in ("window", "appearance", "java_runtime", "festival_theme", "game_version_list"):
                if isinstance(stored.get(sub_key), dict):
                    merged[sub_key] = {
                        **self._data.get(sub_key, {}),
                        **stored[sub_key],
                    }
            self._data = merged
            # 旧地址迁移：升级后自动把已下线的旧服务地址覆盖为新地址并持久化
            if self._migrate_legacy_urls():
                self.save()

    def _migrate_legacy_urls(self) -> bool:
        """把旧配置文件里的下线服务地址自动覆盖为新地址。"""
        changed = False

        # 游戏下载地址已改为版本清单 windows.json 驱动，旧的固定下载源配置作废
        for key in ("game_download_primary", "game_download_backup"):
            if key in self._data:
                self._data.pop(key, None)
                logger.info("配置迁移：%s 已废弃（下载改由版本清单驱动），已移除", key)
                changed = True

        # 正版购买周期弹窗已移除，相关计数配置作废
        for key in ("purchase_tip_count", "purchase_tip_threshold", "purchase_tip_total"):
            if key in self._data:
                self._data.pop(key, None)
                logger.info("配置迁移：%s 随正版弹窗一并移除", key)
                changed = True

        # 健康监控：旧独立监控进程与旧 IP 端口均已下线，改走配套服务自带状态接口
        health = self._data.get("health_service")
        if isinstance(health, dict) and any(
            m in str(health.get("base_url", ""))
            for m in ("103.40.14.90:13711", "64.90.0.120:48117", "cqrwl-server.cqfishnet.cn")
        ):
            health["base_url"] = DEFAULT_CONFIG["health_service"]["base_url"]
            logger.info("配置迁移：health_service.base_url 由旧地址覆盖为新地址")
            changed = True

        # 账号服务：旧 IP 端口已下线，改走新配套服务域名
        account = self._data.get("account")
        if isinstance(account, dict) and any(
            m in str(account.get("base_url", ""))
            for m in ("103.40.14.90:48117", "64.90.0.120:48117", "cqrwl-server.cqfishnet.cn")
        ):
            account["base_url"] = DEFAULT_CONFIG["account"]["base_url"]
            logger.info("配置迁移：account.base_url 由旧地址覆盖为新地址")
            changed = True

        # frp 服务端：旧服务器已下线，默认地址清空，改为用户自填
        frp = self._data.get("frp")
        if isinstance(frp, dict) and frp.get("server_addr") in (
            "103.40.14.90",
            "frps.cqfishnet.cn",
        ):
            frp["server_addr"] = DEFAULT_CONFIG["frp"]["server_addr"]
            logger.info("配置迁移：frp server 旧地址已下线，默认地址已清空")
            changed = True

        # 更新检查：旧公告页域名已下线，清空默认地址以免产生无效请求
        update_cfg = self._data.get("update_check")
        if isinstance(update_cfg, dict) and any(
            host in str(update_cfg.get("url", ""))
            for host in ("server-vs-ot.cqfishnet.cn", "mirror.cqfishnet.cn")
        ):
            update_cfg["url"] = DEFAULT_CONFIG["update_check"]["url"]
            logger.info("配置迁移：update_check.url 旧公告页已下线，地址已清空")
            changed = True

        # 游戏版本清单：旧镜像域名已下线，改走 CDN
        gv = self._data.get("game_version_list")
        if isinstance(gv, dict):
            gv_url = str(gv.get("url", ""))
            if "mirror.cqfishnet.cn" in gv_url and "cdn.cqfishnet.cn" not in gv_url:
                gv["url"] = DEFAULT_CONFIG["game_version_list"]["url"]
                logger.info("配置迁移：game_version_list.url 由旧地址覆盖为新地址")
                changed = True

        return changed

    def save(self) -> None:
        """保存配置到磁盘。"""
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".json.tmp")
                with tmp.open("w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                os.replace(tmp, self.path)
            except OSError as e:
                # 便携模式下放到系统目录可能没写权限，不致命
                logger.warning("保存配置失败：%s", e)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            self._data.update(kwargs)

    def all(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            return self._data[key]

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._data
