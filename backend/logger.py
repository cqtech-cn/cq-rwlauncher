"""统一日志配置。

- 控制台输出 + 文件落盘（logs/cqrwl-YYYYMMDD.log，按天命名）
- 默认打印 DEBUG 及以上全部日志
- 绿色便携：日志目录 = 启动器（exe）所在目录下的 logs/ 文件夹
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

# 默认日志级别：DEBUG（主人要求 debug 及以上全部打印）
DEFAULT_LEVEL = logging.DEBUG


def log_dir() -> Path:
    """日志目录：启动器同目录 / logs。"""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "logs"


def init_logging(level: int = DEFAULT_LEVEL) -> logging.Logger:
    """初始化根日志器（幂等），返回 CQRWL 命名空间的 logger。"""
    root = logging.getLogger()
    if any(getattr(h, "_cqrwl", False) for h in root.handlers):
        return logging.getLogger("cqrwl")

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)

    # 文件（按天）
    d = log_dir()
    d.mkdir(parents=True, exist_ok=True)
    log_file = d / f"cqrwl-{datetime.now():%Y%m%d}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)

    # 打标记用于幂等判断
    for h in (console, file_handler):
        h._cqrwl = True  # type: ignore[attr-defined]

    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)

    logger = logging.getLogger("cqrwl")
    logger.info("日志系统已初始化，日志文件：%s", log_file)
    return logger
