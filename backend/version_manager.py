"""游戏版本管理：远程版本清单解析与本地多版本安装目录扫描。

本模块只负责数据层，不直接发起下载任务：

- 远程清单：从 game_version_list.url（默认 https://cdn.cqfishnet.cn/windows.json）
  拉取游戏版本清单，解析 editions 结构，带 5 分钟内存缓存。
- 本地安装：多个游戏版本并存于 <游戏安装根>/versions/<版本号>/，
  切换版本只是改变启动器定位的目录，不复制、不覆盖、不互删。

下载与解压由 bridge 层提交到 DownloadManager 队列统一处理。
"""
from __future__ import annotations

import json
import logging
import re
import socket
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 远程清单内存缓存有效期（秒）
_REMOTE_CACHE_TTL = 300.0


def _version_sort_key(version: str) -> tuple:
    """版本号排序键：抽取全部数字段逐段比较，非数字版本排最后。

    兼容 1.15、1.15-build176、1.15p11-ZHC-Fix3 这类混合命名，
    不使用字符串与整数混排，避免 TypeError。
    """
    nums = re.findall(r"\d+", str(version or ""))
    if not nums:
        return (0, str(version))
    key = tuple(int(n) for n in nums)
    return key


def _safe_dir_name(version: str) -> str:
    """把版本号转成可安全用作目录名的字符串。"""
    name = re.sub(r'[\\/:*?"<>|\s]+', "_", str(version or "").strip())
    return name or "unknown"


@dataclass
class VersionInfo:
    """版本信息（远程清单项 / 本地已安装项共用）。"""
    version: str
    build_date: str = ""
    file_size: int = 0
    url: str = ""
    checksum: str = ""
    description: str = ""
    is_installed: bool = False
    install_path: str = ""
    install_date: str = ""
    edition_name: str = ""
    file_name: str = ""

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "build_date": self.build_date,
            "file_size": self.file_size,
            "url": self.url,
            "checksum": self.checksum,
            "description": self.description,
            "is_installed": self.is_installed,
            "install_path": self.install_path,
            "install_date": self.install_date,
            "edition_name": self.edition_name,
            "file_name": self.file_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VersionInfo":
        return cls(
            version=str(data.get("version") or ""),
            build_date=str(data.get("build_date") or ""),
            file_size=int(data.get("file_size") or 0),
            url=str(data.get("url") or data.get("download_url") or ""),
            checksum=str(data.get("checksum") or ""),
            description=str(data.get("description") or data.get("info") or ""),
            is_installed=bool(data.get("is_installed")),
            install_path=str(data.get("install_path") or ""),
            install_date=str(data.get("install_date") or ""),
            edition_name=str(data.get("edition_name") or ""),
            file_name=str(data.get("file_name") or ""),
        )


@dataclass
class EditionInfo:
    """编辑版信息：windows.json editions 下的一个分组。"""
    name: str
    latest_version: str = ""
    description: str = ""
    versions: list[VersionInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "latest_version": self.latest_version,
            "description": self.description,
            "versions": [v.to_dict() for v in self.versions],
        }


class VersionManager:
    """游戏版本管理器：远程清单 + 本地 versions 目录。"""

    # 原生游戏 exe 前缀（排除卸载器等）
    _EXE_PREFIX = "rusted"
    # Java 版入口 jar 候选名（小写匹配）
    _JAR_NAMES = ("game-lib.jar", "rustedwarfare.jar", "rusted warfare.jar")

    def __init__(self, config_path: Path, game_root: Path) -> None:
        self._config_path = Path(config_path)
        self._game_root = Path(game_root)
        self._cache_ts: float = 0.0
        self._cache_editions: list[EditionInfo] = []

    # -------- 路径与本地安装 --------

    @property
    def game_root(self) -> Path:
        return self._game_root

    @property
    def versions_root(self) -> Path:
        return self._game_root / "versions"

    def update_game_root(self, path) -> None:
        """游戏安装根变更后重新定位。"""
        self._game_root = Path(path)

    def version_dir(self, version: str) -> Path:
        """指定版本的本地安装目录（不要求目录已存在）。"""
        return self.versions_root / _safe_dir_name(version)

    def _dir_launchable(self, directory: Path) -> bool:
        """目录本身或其一层子目录内是否含游戏 exe / Java 入口 jar。"""
        bases = [directory]
        try:
            if directory.is_dir():
                bases.extend(p for p in directory.iterdir() if p.is_dir())
        except OSError:
            return False
        for base in bases:
            try:
                for child in base.iterdir():
                    if not child.is_file():
                        continue
                    name = child.name.lower()
                    if name.endswith(".exe") and name.startswith(self._EXE_PREFIX):
                        return True
                    if name in self._JAR_NAMES:
                        return True
            except OSError:
                continue
        return False

    def is_version_installed(self, version: str, edition_name: Optional[str] = None) -> bool:
        """检查指定版本是否已安装（目录存在且含可启动目标）。"""
        if not version:
            return False
        return self._dir_launchable(self.version_dir(version))

    def get_installed_versions(self, edition_name: Optional[str] = None) -> list[VersionInfo]:
        """扫描 versions 目录，列出所有已安装游戏版本。"""
        installed: list[VersionInfo] = []
        root = self.versions_root
        if not root.is_dir():
            return installed
        try:
            children = sorted(root.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return installed
        for child in children:
            if not child.is_dir() or child.name.startswith("_"):
                continue
            if not self._dir_launchable(child):
                continue
            try:
                mtime = child.stat().st_mtime
                date_str = time.strftime("%Y-%m-%d", time.localtime(mtime))
                dt_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
            except OSError:
                date_str, dt_str = "", ""
            installed.append(VersionInfo(
                version=child.name,
                build_date=date_str,
                is_installed=True,
                install_path=str(child),
                install_date=dt_str,
            ))
        installed.sort(key=lambda v: _version_sort_key(v.version), reverse=True)
        return installed

    def uninstall_version(self, version: str) -> tuple[bool, Optional[str]]:
        """删除指定版本的安装目录（当前版本是否可删由 bridge 判断）。"""
        target = self.version_dir(version)
        try:
            resolved = target.resolve()
            root_resolved = self.versions_root.resolve()
            if root_resolved not in resolved.parents:
                return False, "版本目录不在 versions 根目录内，拒绝删除"
        except OSError as e:
            return False, f"路径解析失败：{e}"
        if not target.is_dir():
            return False, f"版本 {version} 未安装"
        try:
            shutil.rmtree(target)
            logger.info("已删除游戏版本目录：%s", target)
            return True, None
        except OSError as e:
            return False, f"删除失败：{e}"

    # -------- 远程清单 --------

    def clear_cache(self) -> None:
        """强制下次重新拉取远程版本清单。"""
        self._cache_ts = 0.0
        self._cache_editions = []

    def _list_config(self) -> dict:
        """从 config.json 读取 game_version_list 段（url / timeout）。"""
        if not self._config_path.exists():
            # 便携版 EXE 首次启动时配置尚未落盘，仍需使用内置默认清单地址。
            from backend.config import DEFAULT_CONFIG
            return DEFAULT_CONFIG["game_version_list"].copy()
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
            gv = data.get("game_version_list")
            return gv if isinstance(gv, dict) else {}
        except Exception:
            return {}

    def get_editions(self, use_cache: bool = True) -> list[EditionInfo]:
        """获取远程版本清单（按 editions 分组，兼容裸 versions 旧格式）。"""
        if use_cache and self._cache_editions and (time.time() - self._cache_ts) < _REMOTE_CACHE_TTL:
            return self._cache_editions
        gv = self._list_config()
        url = str(gv.get("url") or "").strip()
        if not url:
            raise ValueError("未配置游戏版本清单地址（game_version_list.url）")
        try:
            timeout = float(gv.get("timeout") or 10)
        except (TypeError, ValueError):
            timeout = 10.0
        data = self._fetch_json(url, timeout)
        editions = self._parse_editions(data)
        if not any(ed.versions for ed in editions):
            raise RuntimeError("版本清单中没有可用版本，请检查清单格式")
        self._cache_editions = editions
        self._cache_ts = time.time()
        return editions

    def get_remote_versions(
        self, edition_name: Optional[str] = None, use_cache: bool = True
    ) -> list[VersionInfo]:
        """获取远程版本列表：可按编辑版名过滤，默认聚合全部编辑版。"""
        editions = self.get_editions(use_cache=use_cache)
        if edition_name:
            for ed in editions:
                if ed.name == edition_name:
                    return list(ed.versions)
            return []
        out: list[VersionInfo] = []
        for ed in editions:
            out.extend(ed.versions)
        out.sort(key=lambda v: _version_sort_key(v.version), reverse=True)
        return out

    def find_remote_version(
        self, version: str, edition_name: Optional[str] = None
    ) -> Optional[VersionInfo]:
        """按版本号在远程清单中查找。"""
        if not version:
            return None
        for v in self.get_remote_versions(edition_name):
            if v.version == version:
                return v
        return None

    def get_latest_version(self, edition_name: str = "default") -> Optional[str]:
        """获取指定编辑版（默认 default）标记的最新版本号。

        清单没有标记时回退到版本号排序最大的一项。
        """
        editions = self.get_editions()
        target: Optional[EditionInfo] = None
        for ed in editions:
            if ed.name == edition_name:
                target = ed
                break
        if target is None and editions:
            target = editions[0]
        if target is None:
            return None
        if target.latest_version:
            return target.latest_version
        if target.versions:
            ordered = sorted(target.versions, key=lambda v: _version_sort_key(v.version), reverse=True)
            return ordered[0].version
        return None

    @staticmethod
    def compare_versions(v1: str, v2: str) -> int:
        """比较两个版本号：v1>v2 返回 1，相等 0，否则 -1。"""
        k1, k2 = _version_sort_key(v1), _version_sort_key(v2)
        if k1 == k2:
            return 0
        return 1 if k1 > k2 else -1

    # -------- 拉取与解析 --------

    @staticmethod
    def _fetch_json(url: str, timeout: float) -> dict:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"版本清单请求失败（HTTP {e.code}）") from e
        except (urllib.error.URLError, socket.gaierror) as e:
            if isinstance(e, socket.gaierror) or isinstance(getattr(e, "reason", None), socket.gaierror):
                raise RuntimeError("版本清单域名无法解析（11001），请检查网络或更换版本清单地址") from e
            raise RuntimeError(f"版本清单无法访问：{e.reason}") from e
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"版本清单不是有效 JSON：{e}") from e
        if not isinstance(data, dict):
            raise RuntimeError("版本清单格式不正确：根节点不是对象")
        return data

    def _parse_editions(self, data: dict) -> list[EditionInfo]:
        """解析 windows.json，兼容分支和版本的对象映射或数组结构。"""
        editions: list[EditionInfo] = []

        def build_versions(raw_items, edition: str) -> list[VersionInfo]:
            out: list[VersionInfo] = []
            seen: set[str] = set()
            items = raw_items.items() if isinstance(raw_items, dict) else (
                ((None, item) for item in raw_items) if isinstance(raw_items, list) else ()
            )
            for key, item in items:
                if not isinstance(item, dict):
                    continue
                version = str(
                    item.get("version") or item.get("version_name") or key or item.get("name") or ""
                ).strip()
                if not version or version in seen:
                    continue
                seen.add(version)
                vi = VersionInfo(
                    version=version,
                    build_date=str(item.get("release_date") or item.get("build_date") or ""),
                    file_size=int(item.get("file_size") or item.get("size") or 0),
                    url=str(item.get("download_url") or item.get("url") or ""),
                    checksum=str(item.get("checksum") or item.get("sha256") or ""),
                    description=str(item.get("info") or item.get("description") or ""),
                    file_name=str(item.get("file_name") or ""),
                    edition_name=edition,
                    is_installed=self.is_version_installed(version),
                    install_path=str(self.version_dir(version))
                    if self.is_version_installed(version) else "",
                )
                out.append(vi)
            out.sort(key=lambda v: _version_sort_key(v.version), reverse=True)
            return out

        raw_editions = data.get("editions")
        if isinstance(raw_editions, (list, dict)) and raw_editions:
            entries = raw_editions.items() if isinstance(raw_editions, dict) else (
                (None, item) for item in raw_editions
            )
            for key, ed_item in entries:
                if not isinstance(ed_item, dict):
                    continue
                name = str(ed_item.get("name") or key or "default").strip() or "default"
                editions.append(EditionInfo(
                    name=name,
                    latest_version=str(ed_item.get("latest_version") or ""),
                    description=str(ed_item.get("description") or ed_item.get("info") or ""),
                    versions=build_versions(ed_item.get("versions"), name),
                ))
        else:
            raw_versions = data.get("versions") or data.get("items") or []
            editions.append(EditionInfo(
                name="default",
                latest_version=str(data.get("latest_version") or ""),
                versions=build_versions(raw_versions, "default"),
            ))

        # latest_version 未标注时补一个排序最大的
        for ed in editions:
            if not ed.latest_version and ed.versions:
                ed.latest_version = ed.versions[0].version
        return editions
