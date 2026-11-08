"""Java 运行环境：探测游戏自带 JRE / 系统 JRE，必要时从 Adoptium 自动补齐。

简体中文增强版（Java 版）的游戏本体是 jar（game-lib.jar + libs/*），
需要 JRE 才能运行。真实启动命令参考游戏根目录的 fallback64.bat：

    jvm64\\bin\\java -Xmx1000M -Dfile.encoding=UTF-8 -Djava.library.path=. \
        -cp "game-lib.jar;libs/*" com.corrodinggames.rts.java.Main <用户参数>

本模块只负责"找 JRE / 下载 JRE"，不负责启动进程；启动由 launcher.GameLauncher 完成。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

import requests

logger = logging.getLogger(__name__)

# 游戏根目录下 JRE 的候选目录名（与官方增强版包结构一致）
JVM_DIR_64 = "jvm64"   # 64 位 JRE（Java 9+，UTF-8 支持完整）
JVM_DIR_32 = "jvm"     # 32 位 JRE（老增强版自带的 Java 8）

# 自动下载 JRE 的目标大版本（LTS）。旧版 Java 13 虽能运行，但 JEP 400 后
# 新版 JRE 在 Windows 上默认 UTF-8，中文路径 / 文本乱码问题最少。
DEFAULT_FEATURE_VERSION = 21

# Adoptium（Eclipse Temurin）资产查询：latest/{feature}/hotspot
ADOPTIUM_QUERY_URL = (
    "https://api.adoptium.net/v3/assets/latest/{feature}/hotspot"
    "?architecture=x64&image_type=jre&os=windows&vendor=eclipse"
)
_ADOPTIUM_UA = "CQRWLauncher/2.x (java-runtime)"

# 窗口创建标记（避免弹黑框）
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


# ---------------------------------------------------------------
# JRE 版本探测
# ---------------------------------------------------------------

def probe_java_major(java_exe: Path, timeout: float = 4.0) -> Optional[int]:
    """探测 java.exe 的主版本号。

    Java 8 输出形如 "1.8.0_121"（主版本取第二段 8）；
    Java 9+ 输出形如 "13.0.2"、"21.0.1"（直接取首段）。
    探测失败（文件不存在 / 超时 / 非 Java）返回 None。
    """
    try:
        r = subprocess.run(
            [str(java_exe), "-version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )
    except Exception:
        return None
    text = (r.stdout or "") + (r.stderr or "")
    m = re.search(r'version\s+"([^"]+)"', text)
    if not m:
        return None
    version = m.group(1)
    first, _, rest = version.partition(".")
    if first == "1":
        second = rest.split(".")[0]
        try:
            return int(second)
        except ValueError:
            return None
    try:
        return int(first)
    except ValueError:
        return None


# ---------------------------------------------------------------
# JRE 查找
# ---------------------------------------------------------------

def _find_java_in(jre_dir: Path) -> Optional[Path]:
    """jre 目录下是否存在可执行 java（bin/java.exe）。"""
    java = jre_dir / "bin" / "java.exe"
    return java if java.is_file() else None


def _probe_dir(jre_dir: Path) -> Optional[dict]:
    """探测某个 JRE 目录，返回 {path, major}；不可用返回 None。"""
    java = _find_java_in(jre_dir)
    if java is None:
        return None
    return {"path": str(java), "major": probe_java_major(java)}


def bundled_jres(game_root: Path) -> dict:
    """探测游戏根目录自带的 JRE（64 位与 32 位分开）。"""
    out = {"jvm64": None, "jvm": None}
    for name, key in ((JVM_DIR_64, "jvm64"), (JVM_DIR_32, "jvm")):
        info = _probe_dir(game_root / name)
        if info is not None:
            out[key] = info
    return out


def system_java() -> Optional[dict]:
    """探测系统 Java（JAVA_HOME 优先，其次 PATH）。返回 {path, major}。"""
    candidates: list[Path] = []
    java_home = os.environ.get("JAVA_HOME", "")
    if java_home:
        candidates.append(Path(java_home) / "bin" / "java.exe")
    which = shutil.which("java")
    if which:
        candidates.append(Path(which))
    for cand in candidates:
        info = _probe_dir(cand.parent.parent) if cand.name == "java.exe" else None
        if info is not None:
            return info
        # 兜底：直接按可执行文件探测
        try:
            major = probe_java_major(cand)
            if major is not None:
                return {"path": str(cand), "major": major}
        except Exception:
            continue
    return None


def _good_major(major: Optional[int]) -> bool:
    """大版本是否满足现代中文增强版的运行需要（9+ 完整支持 UTF-8 参数）。"""
    return major is not None and major >= 9


def resolve_java(game_root: Path) -> dict:
    """按优先级挑选可用 JRE，返回状态字典。

    优先级（避免覆盖游戏自带目录，仅在完全没有可用 JRE 时建议安装）：
    1. 游戏自带 64 位 JRE（jvm64，Java 9+）
    2. 游戏自带 64 位 JRE（任意版本）
    3. 游戏自带 32 位 JRE（jvm，Java 9+）
    4. 系统 Java（Java 9+）
    5. 系统 Java（任意版本）

    返回值字段：java_path / java_major / java_source / needs_install /
    install_dir / reason / bundled（含各目录探测明细）。
    """
    root = Path(game_root)
    bundled = bundled_jres(root)

    def _pick(
        info: Optional[dict], source: str
    ) -> dict:
        return {
            "java_path": info["path"],
            "java_major": info["major"],
            "java_source": source,
            "needs_install": False,
            "install_dir": str(root / JVM_DIR_64),
            "reason": "",
            "bundled": bundled,
        }

    sys_java = system_java()

    j64, j32 = bundled.get("jvm64"), bundled.get("jvm")
    for info, source in ((j64, "bundled64"), (j32, "bundled32")):
        if info and _good_major(info.get("major")):
            return _pick(info, source)

    if sys_java and _good_major(sys_java.get("major")):
        return _pick(sys_java, "system")

    for info, source in ((j64, "bundled64"), (j32, "bundled32"), (sys_java, "system")):
        if info and info.get("major"):
            return _pick(info, source)

    install_dir = root / JVM_DIR_64
    return {
        "java_path": None,
        "java_major": None,
        "java_source": "none",
        "needs_install": True,
        "install_dir": str(install_dir),
        "reason": (
            "未找到可用 Java 运行环境（游戏自带 jvm64/jvm 与系统 Java 均不可用），"
            f"自动下载 JRE {DEFAULT_FEATURE_VERSION} 将安装到：{install_dir}"
        ),
        "bundled": bundled,
    }


# ---------------------------------------------------------------
# Adoptium 资产查询
# ---------------------------------------------------------------

def query_adoptium_jre(
    feature_version: int = DEFAULT_FEATURE_VERSION, timeout: float = 12.0
) -> dict:
    """查询 Adoptium 指定版本的 JRE Windows x64 资产。

    返回 {"ok": True, "link": 下载地址, "name": 文件名, "size": 字节}
    失败时抛 RuntimeError（带可读原因）。
    """
    url = ADOPTIUM_QUERY_URL.format(feature=feature_version)
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _ADOPTIUM_UA},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"查询 Java {feature_version} 下载信息失败：{e}") from e

    if not isinstance(data, list) or not data:
        raise RuntimeError(f"Adoptium 返回了空资产列表（Java {feature_version} JRE）")
    asset = data[0]
    binary = asset.get("binary") or {}
    pkg = binary.get("package") or {}
    link = pkg.get("link") or ""
    name = pkg.get("name") or ""
    size = int(pkg.get("size") or 0)
    if not link or not name:
        raise RuntimeError("Adoptium 资产缺少下载地址")
    return {"ok": True, "link": link, "name": name, "size": size}


# ---------------------------------------------------------------
# JRE 安装（zip 解压归一化）
# ---------------------------------------------------------------

def download_jre(
    asset: dict,
    dest_zip: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    """流式下载 Adoptium JRE zip 到 dest_zip（带进度回调）。"""
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    total = int(asset.get("size") or 0)
    downloaded = 0
    with requests.get(
        asset["link"],
        headers={"User-Agent": _ADOPTIUM_UA},
        stream=True,
        timeout=60,
        allow_redirects=True,
    ) as resp:
        resp.raise_for_status()
        if total <= 0:
            try:
                total = int(resp.headers.get("Content-Length", 0) or 0)
            except ValueError:
                total = 0
        with dest_zip.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb is not None:
                    progress_cb(downloaded, total)


def install_jre_zip(dest_zip: Path, target_dir: Path) -> Path:
    """把 Adoptium JRE zip 解压并归一化到 target_dir（游戏根/jvm64）。

    Adoptium zip 顶层是 "jdk-21.x+12-jre/" 目录，这里把它整体提升为
    target_dir（即 jvm64/bin/java.exe）。target_dir 已存在时抛出错误，
    由调用方保证不覆盖已有 JRE。

    返回安装后的 java.exe 路径。
    """
    if target_dir.exists():
        raise FileExistsError(f"目标目录已存在，拒绝覆盖：{target_dir}")
    if not dest_zip.is_file():
        raise FileNotFoundError(f"JRE 压缩包不存在：{dest_zip}")

    try:
        with zipfile.ZipFile(dest_zip, "r") as zf:
            names = zf.namelist()
            bad = zf.testzip()
            if bad is not None:
                raise RuntimeError(f"JRE 压缩包校验失败（{bad} 损坏）")
            # 顶层唯一目录（形如 jdk-21.0.x+y-jre/）
            top = ""
            for name in names:
                head = name.split("/", 1)[0]
                if not name.endswith("/"):
                    continue
                if not top:
                    top = head
                elif head != top:
                    top = ""  # 多个顶层目录：按普通解压处理
                    break
            staging = target_dir.parent / f"{target_dir.name}.staging"
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)
            zf.extractall(staging)
    except zipfile.BadZipFile:
        raise RuntimeError("下载的 JRE 文件不是有效 zip，请重试") from None

    try:
        src_root = staging / top if top else staging
        if not src_root.is_dir():
            # 归一化失败兜底：尝试找 staging 下第一个目录
            for child in staging.iterdir():
                if child.is_dir():
                    src_root = child
                    break
        shutil.move(str(src_root), str(target_dir))
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    java_exe = _find_java_in(target_dir)
    if java_exe is None:
        raise RuntimeError(f"JRE 安装后未找到可执行文件：{target_dir}")
    return java_exe


def cleanup_old_jre(game_root: Path, keep: Optional[dict] = None) -> list[Path]:
    """清理游戏根目录下残留的归一化临时目录（.staging）。

    只在游戏未运行 JRE 时调用（下载线程 on_done），防堆积。
    """
    removed: list[Path] = []
    try:
        for child in Path(game_root).iterdir():
            if child.is_dir() and child.name.endswith(".staging"):
                shutil.rmtree(child, ignore_errors=True)
                removed.append(child)
    except OSError:
        pass
    return removed
