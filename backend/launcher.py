"""游戏启动器：把用户参数原样附加到可执行文件命令行尾部。

智能定位策略：
- 用户配置的 game_install_path 是"安装根目录"（如 D:\\RustedWarfare）
- 实际游戏 exe 在该目录下一层子目录里（典型：Rusted\\Rusted Warfare.exe）
- 这里会自动找到真实游戏根目录（含 RustedWarfare.exe 的目录），
  并把该目录作为 mods/maps 的真正位置以及启动 cwd。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from .java_runtime import resolve_java
from .version_manager import VersionManager

logger = logging.getLogger(__name__)


class JavaRuntimeMissingError(RuntimeError):
    """Java 版启动需要 JRE，但游戏目录与本机都没有可用 Java。

    调用方（bridge）捕获后应触发 JRE 自动下载或引导用户手动补齐。
    """

    def __init__(self, message: str, install_dir: Optional[str] = None) -> None:
        super().__init__(message)
        self.install_dir = install_dir


# 一些"看起来像游戏主程序"的文件名关键字（用于自动识别 64 位优先）
_PREFERRED_64_KEYWORDS = ("64", "x64", "win64")
# 一些"看起来像游戏主程序"的文件名关键字
_GAME_EXE_KEYWORDS = ("RustedWarfare", "Rusted Warfare", "Rusted")


def _clean_install_path(path: Any) -> str:
    """清理玩家填写的安装路径：去掉首尾空白和引号（含全角引号）。

    玩家从聊天 / 网页复制路径时容易带上引号或空白，Windows 对这类
    路径执行 mkdir 会报 WinError 123（文件名、目录名或卷标语法不正确）。
    这里在源头统一清理，后续所有使用 game_dir 的地方都拿到干净路径。
    """
    text = str(path).strip()
    while text and text[0] in "\"'“”‘’":
        text = text[1:]
    while text and text[-1] in "\"'“”‘’":
        text = text[:-1]
    return text


class GameLauncher:
    """封装 RustedWarfare.exe 启动逻辑。

    严格遵循需求：仅把用户输入的文本原样附加到命令行尾部，
    不解析、不校验、不拼接任何额外参数。
    """

    def __init__(self, game_dir: Path, exe_name: str = "RustedWarfare.exe",
                 config: Any = None) -> None:
        self.game_dir = Path(_clean_install_path(game_dir))
        self.exe_name = exe_name

    # -------------------------------------------------------------
    # 智能定位：找到真正的游戏根目录（含 RustedWarfare.exe 的目录）
    # -------------------------------------------------------------
    def _resolve_real_root(self) -> Path | None:
        """扫描 game_dir 找包含主程序 exe 的子目录。

        返回值：找到则返回该子目录路径；找不到返回 None。

        规则：
        1. 先看 game_dir 本身（含主程序）
        2. 找不到再看 game_dir 下的一层子目录（最常见的"Rusted\\"模式）
        3. 优先匹配 exe_name 完全相等的；其次匹配含关键字的 .exe；
           在候选中 64 位版本优先。
        """
        if not self.game_dir.is_dir():
            return None

        candidates: list[tuple[Path, Path]] = []  # (root, exe)

        def _scan(root: Path) -> None:
            try:
                for child in root.iterdir():
                    if not child.is_file():
                        continue
                    if child.suffix.lower() != ".exe":
                        continue
                    candidates.append((root, child))
            except OSError:
                pass

        # 1) 先扫根目录
        _scan(self.game_dir)
        # 2) 扫一层子目录（深度=1）
        try:
            for sub in self.game_dir.iterdir():
                if sub.is_dir() and not sub.name.startswith("_"):
                    _scan(sub)
        except OSError:
            pass

        if not candidates:
            return None

        # 评分：先看完全匹配 exe_name 的；再看含关键字的；同分时优先 64 位
        def _score(item: tuple[Path, Path]) -> tuple[int, int]:
            (_root, exe) = item
            name = exe.name
            score = 0
            if name == self.exe_name:
                score += 1000
            lower = name.lower()
            for kw in _GAME_EXE_KEYWORDS:
                if kw.lower() in lower:
                    score += 50
                    break
            if any(kw.lower() in lower for kw in _PREFERRED_64_KEYWORDS):
                score += 20
            # 排除明显非游戏 exe
            lower_stem = exe.stem.lower()
            if "unins" in lower_stem or "setup" in lower_stem or "update" in lower_stem:
                score -= 500
            return (score, 0)

        candidates.sort(key=_score, reverse=True)
        best_root, _ = candidates[0]
        return best_root

    @property
    def game_root(self) -> Path:
        """真实游戏根目录（含 RustedWarfare.exe 的目录）。"""
        resolved = self._resolve_real_root()
        return resolved if resolved is not None else self.game_dir

    @property
    def exe_path(self) -> Path:
        """游戏可执行文件路径（已智能定位）。"""
        root = self.game_root
        # 先按 exe_name 找
        direct = root / self.exe_name
        if direct.is_file():
            return direct
        # 否则用候选里评分最高的那个
        resolved = self._resolve_real_root()
        if resolved is not None:
            for _root, exe in self._scan_candidates(resolved):
                return exe
        return direct  # 找不到时仍返回猜测路径

    def _scan_candidates(self, root: Path) -> list[tuple[Path, Path]]:
        """列出 root 下的所有 .exe 候选（用于内部排序/展示）。"""
        out: list[tuple[Path, Path]] = []
        try:
            for child in root.iterdir():
                if child.is_file() and child.suffix.lower() == ".exe":
                    out.append((root, child))
        except OSError:
            pass
        return out

    # Java 版（简体中文增强版）入口 jar 候选名，按优先级排列
    _JAR_CANDIDATES = ("game-lib.jar", "RustedWarfare.jar", "Rusted Warfare.jar")

    def _search_bases(self) -> list[Path]:
        """搜索起点：真实游戏根目录 + game_dir 下一层子目录。

        exe 定位依靠 _resolve_real_root；jar 版可能没有 exe，此时
        game_root 退回 game_dir，入口 jar 在"Rusted Warfare"这类子目录里，
        所以这里需要一并扫描一层子目录。
        """
        bases: list[Path] = [self.game_root]
        try:
            if self.game_dir.is_dir():
                for sub in self.game_dir.iterdir():
                    if sub.is_dir() and not sub.name.startswith("_") and sub not in bases:
                        bases.append(sub)
        except OSError:
            pass
        return bases

    @property
    def java_jar_path(self) -> Optional[Path]:
        """Java 版入口 jar（简体中文增强版本体）路径；找不到返回 None。"""
        for base in self._search_bases():
            for name in self._JAR_CANDIDATES:
                p = base / name
                if p.is_file():
                    return p
        return None

    def launchable(self) -> bool:
        """是否存在可启动目标（原生 exe 或 Java 版 jar，任一即可）。"""
        return self.exists() or self.java_jar_path is not None

    def exists(self) -> bool:
        return self.exe_path.is_file()

    # DETACHED_PROCESS（脱离控制台/进程组）+ CREATE_NEW_PROCESS_GROUP：
    # 游戏进程独立于启动器，启动器退出不牵连游戏
    _DETACHED_FLAGS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
    )

    def launch(self, raw_args: str = "", mode: str = "auto") -> Optional[subprocess.Popen]:
        """启动游戏（原生 exe / Java 版 jar 自动分流）。

        关键点：以 CreateProcess 直启并附加 DETACHED_PROCESS +
        CREATE_NEW_PROCESS_GROUP，游戏进程完全脱离启动器进程组，
        启动器关闭不会杀死游戏。

        相比旧实现（cmd /c start ""）：
        - 命令行不再经过 cmd 二次解析，raw_args 原样附加到命令行尾部，
          `&`、`|` 等元字符注入从根源消除；
        - 无需任何引号/转义魔法。

        Args:
            raw_args: 用户在启动器中输入的原始参数字符串。
                       为空时只启动主程序。
            mode: auto=exe 优先、无 exe 有 Java 版 jar 时走 Java；
                  exe=强制原生 exe；java=强制 Java 版（简体中文增强版）。

        Returns:
            Popen 句柄（调用方可拿 pid 做进程监控 / 结束），无需可忽略。
        """
        if mode == "exe":
            return self._launch_exe(raw_args)
        if mode == "java":
            return self.launch_java(raw_args)
        if self.exists():
            return self._launch_exe(raw_args)
        return self.launch_java(raw_args)

    def _launch_exe(self, raw_args: str) -> Optional[subprocess.Popen]:
        """原生 exe 启动。工作目录 = exe 所在目录（保证 mods/maps 相对路径正确）。"""
        exe = self.exe_path
        if not exe.is_file():
            raise FileNotFoundError(f"游戏可执行文件未找到：{exe}")

        logger.info("启动命令：%s（cwd=%s）参数=%r", exe, exe.parent, raw_args or "")
        cwd = exe.parent

        # Popen 传字符串 + shell=False：整串原样作为 lpCommandLine
        # 交给 CreateProcess，由系统按 Windows 规则切分参数
        cmdline = f'"{exe}" {raw_args}'.rstrip()

        return subprocess.Popen(
            cmdline,
            shell=False,
            cwd=str(cwd),
            creationflags=self._DETACHED_FLAGS,
            close_fds=True,
        )

    # Java 版（简体中文增强版）专用：入口 main 类与默认堆内存
    # 与游戏根目录 fallback64.bat 的权威启动命令保持一致
    _JAVA_MAIN_CLASS = "com.corrodinggames.rts.java.Main"
    _JAVA_HEAP_MB = 1000

    def launch_java(self, raw_args: str = "") -> Optional[subprocess.Popen]:
        """Java 版启动：游戏 jar + JRE。

        JRE 选择顺序见 java_runtime.resolve_java：游戏自带 jvm64/jvm →
        系统 Java。全部不可用时抛 JavaRuntimeMissingError，
        调用方（bridge）应据此触发 JRE 自动下载或引导用户补齐。

        -Dfile.encoding=UTF-8 与 JRE9+ 的默认 UTF-8 配合，确保中文不乱码。
        """
        jar = self.java_jar_path
        if jar is None:
            raise FileNotFoundError(
                f"未找到游戏主程序（既无 exe 也无 Java 版 jar）：{self.game_root}"
            )
        st = resolve_java(jar.parent)
        if st["needs_install"] or not st["java_path"]:
            raise JavaRuntimeMissingError(
                st.get("reason") or "未找到可用 Java 运行环境",
                install_dir=st.get("install_dir"),
            )
        java_exe = st["java_path"]
        cmdline = self._build_java_cmdline(java_exe, jar, raw_args)
        logger.info("启动 Java 版游戏（JRE%s）：%s", st.get("java_major"), java_exe)
        logger.info("启动命令：%s（cwd=%s）参数=%r", cmdline, jar.parent, raw_args or "")
        return subprocess.Popen(
            cmdline,
            shell=False,
            cwd=str(jar.parent),
            creationflags=self._DETACHED_FLAGS,
            close_fds=True,
        )

    def _build_java_cmdline(self, java_exe: str, jar: Path, raw_args: str) -> str:
        """拼 Java 启动命令行（权威参考：游戏根目录 fallback*.bat）。

        类路径规则：有 libs/ 时 "game-lib.jar;libs/*"，否则仅入口 jar。
        """
        libs = jar.parent / "libs"
        cp = f"{jar.name};libs/*" if libs.is_dir() else jar.name
        cmd = (
            f'"{java_exe}" -Xmx{self._JAVA_HEAP_MB}M -Dfile.encoding=UTF-8 '
            f'-Djava.library.path=. -cp "{cp}" {self._JAVA_MAIN_CLASS}'
        )
        if raw_args:
            cmd += " " + raw_args
        return cmd

    def java_status(self) -> dict:
        """Java 版启动状态（入口 jar + JRE 解析结果），供 bridge 与诊断复用。"""
        jar = self.java_jar_path
        if jar is None:
            return {
                "jar": None,
                "java_path": None,
                "java_major": None,
                "java_source": "none",
                "needs_install": False,
                "install_dir": None,
                "reason": "",
            }
        st = resolve_java(jar.parent)
        st["jar"] = str(jar)
        return st
    
    def launch_game_by_version(self, version: str, raw_args: str = "", version_manager: Optional[VersionManager] = None) -> bool:
        """通过指定版本启动游戏。
        
        Args:
            version: 要启动的游戏版本
            raw_args: 游戏启动参数
            version_manager: 版本管理器（可选）
            
        Returns:
            是否成功启动
        """
        logger.info("通过版本 %s 启动游戏", version)
        
        try:
            if version_manager is None:
                logger.error("没有版本管理器，无法按版本启动 %s", version)
                return False
            # 检查版本是否已安装（versions/<版本> 目录含游戏主程序）
            if not version_manager.is_version_installed(version):
                logger.error("版本 %s 未安装", version)
                return False
            version_dir = version_manager.version_dir(version)
            # 游戏可能在解压出的一层子目录内，交给 GameLauncher 智能定位
            game_launcher = GameLauncher(version_dir, "RustedWarfare.exe")
            if not game_launcher.launchable():
                logger.error("在版本 %s 目录中未找到游戏可执行文件或 Java 版 jar", version)
                return False
            game_launcher.launch(raw_args)
            logger.info("版本 %s 游戏启动成功", version)
            return True
        except Exception as e:
            logger.error("通过版本 %s 启动游戏失败：%s", version, e)
            return False
    
    def quick_launch(self, game_dir: Optional[Path] = None, raw_args: str = "") -> bool:
        """快速启动游戏（使用默认或指定目录）。
        
        Args:
            game_dir: 游戏目录（可选，默认为上次的配置路径）
            raw_args: 游戏启动参数
            
        Returns:
            是否成功启动
        """
        logger.info("快速启动游戏，目录：%s，参数：%r", game_dir, raw_args)
        
        try:
            # 如果没有指定目录，尝试从配置中获取
            if game_dir is None:
                # 这里可以添加从配置文件读取游戏目录的逻辑
                # 暂时使用当前目录作为fallback
                game_dir = Path(".")
            
            # 创建游戏启动器实例
            game_launcher = GameLauncher(game_dir, "RustedWarfare.exe")

            if not game_launcher.launchable():
                logger.error("在指定目录中未找到游戏可执行文件或 Java 版 jar：%s", game_dir)
                return False
            
            # 启动游戏
            game_launcher.launch(raw_args)
            logger.info("快速启动成功")
            return True
            
        except Exception as e:
            logger.error("快速启动失败：%s", e)
            return False
