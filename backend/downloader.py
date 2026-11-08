"""下载管理器：支持进度上报、暂停/取消、断点续传。

设计要点：
- 即使服务器不返回 Content-Length（chunked transfer），也会持续上报
  downloaded 字节数（total=0 表示"未知总大小"），前端可按已下载字节 / 速度显示。
- 解压是阻塞操作，会切到 EXTRACTING 状态。
"""
from __future__ import annotations

import logging
import threading
import time
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    NEEDS_CONFIRM = "needs_confirm"  # 等待用户确认（模组包嵌套检测）
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


ProgressCallback = Callable[[str, int, int], None]   # task_id, downloaded, total (total=0 表示未知)
StatusCallback = Callable[[str, str, Optional[str]], None]  # task_id, status, error


class _TaskCanceled(Exception):
    """内部异常：任务被用户取消，用于中断下载 / 收尾流程。"""


def _format_bytes(n: float) -> str:
    """人类友好的字节数。"""
    units = ["B", "KB", "MB", "GB"]
    v = float(n)
    for u in units:
        if v < 1024 or u == units[-1]:
            return f"{v:.1f} {u}" if u != "B" else f"{int(v)} {u}"
        v /= 1024
    return f"{n} B"


@dataclass
class DownloadTask:
    task_id: str
    url: str
    dest: Path                      # 最终文件路径（zip 形态）
    total_size: int = 0
    downloaded: int = 0
    status: TaskStatus = TaskStatus.PENDING
    error: Optional[str] = None
    speed_bps: float = 0.0          # 字节/秒
    speed_limit_bps: float = 0.0    # 限速（字节/秒，0 表示不限）
    final_url: str = ""             # 重定向后的最终地址（可能含真实文件名）
    _cancel: threading.Event = field(default_factory=threading.Event)
    _thread: Optional[threading.Thread] = field(default=None, repr=False)
    # 任务最终完成 / 失败回调（task_id, ok, error）；取消不触发
    _on_done: Optional[Callable[[str, bool, Optional[str]], None]] = field(default=None, repr=False)
    # 模组包嵌套确认：检测到多嵌套一层时，下载线程阻塞等待用户决定
    _confirm_evt: threading.Event = field(default_factory=threading.Event)
    _confirm_action: Optional[str] = None  # "fix" 展平修复 / "keep" 保持原样
    nested_top: str = ""                    # 检测到的嵌套顶层文件夹名

    @property
    def progress(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return min(1.0, self.downloaded / self.total_size)


class DownloadManager:
    CHUNK_SIZE = 64 * 1024
    PROGRESS_INTERVAL = 0.15  # 150ms

    def __init__(self, on_progress: ProgressCallback, on_status: StatusCallback) -> None:
        self._on_progress = on_progress
        self._on_status = on_status
        self._tasks: dict[str, DownloadTask] = {}
        self._lock = threading.Lock()

    # -------- 公共 API --------

    def submit(
        self,
        task_id: str,
        url: str,
        dest: Path,
        *,
        fallback_urls: Optional[list[str]] = None,
        extract_to: Optional[Path] = None,
        allow_non_zip: bool = False,
        store_to: Optional[Path] = None,
        accept_ext: Optional[str] = None,
        speed_limit_bps: float = 0.0,
        on_done: Optional[Callable[[str, bool, Optional[str]], None]] = None,
    ) -> DownloadTask:
        """提交一个下载任务，立即返回 Task 对象。

        Args:
            extract_to: 下载完成后解压到的目录（None 表示不解压）。
            allow_non_zip: 为 True 时，如果下载的文件不是 zip（例如
                社区地图直链返回的散文件 / .wz / 图片），不报错、不解压，
                而是把文件原样存放到 extract_to 目录中。
            store_to: 资源模式（模组 / 地图）。下载完成后校验文件格式并
                落盘到该路径（zip 包会提取其中第一个符合格式的文件）。
                与 extract_to 互斥，设置后 extract_to 被忽略。
            accept_ext: store_to 模式下接受的文件扩展名（如 ".rwmod"），
                不区分大小写；格式不匹配时任务以 REJECT 错误失败。
            speed_limit_bps: 限速（字节/秒），0 表示不限速。
            on_done: 任务最终完成（ok=True）或失败（ok=False, error）回调，
                取消不触发。在下载线程内调用，回调内请勿做耗时操作。
        """
        with self._lock:
            existing = self._tasks.get(task_id)
            if existing and existing.status in (
                TaskStatus.PENDING,
                TaskStatus.DOWNLOADING,
                TaskStatus.EXTRACTING,
            ):
                # 已存在任务，限速以新值为准
                existing.speed_limit_bps = float(speed_limit_bps or 0.0)
                return existing
            dest.parent.mkdir(parents=True, exist_ok=True)
            task = DownloadTask(
                task_id=task_id,
                url=url,
                dest=dest,
                speed_limit_bps=float(speed_limit_bps or 0.0),
            )
            task._on_done = on_done
            self._tasks[task_id] = task

        thread = threading.Thread(
            target=self._run,
            args=(task, fallback_urls or [], extract_to, allow_non_zip, store_to, accept_ext),
            daemon=True,
            name=f"dl-{task_id}",
        )
        task._thread = thread
        thread.start()
        return task

    def get(self, task_id: str) -> Optional[DownloadTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
        if task:
            task._cancel.set()

    def list_active(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "task_id": t.task_id,
                    "status": t.status.value,
                    "downloaded": t.downloaded,
                    "total": t.total_size,
                    "progress": t.progress,
                    "speed": t.speed_bps,
                    "error": t.error,
                }
                for t in self._tasks.values()
            ]

    # -------- 内部实现 --------

    def _run(
        self,
        task: DownloadTask,
        fallback_urls: list[str],
        extract_to: Optional[Path],
        allow_non_zip: bool,
        store_to: Optional[Path],
        accept_ext: Optional[str],
    ) -> None:
        try:
            urls = [task.url] + [u for u in fallback_urls if u and u != task.url]
            last_err: Optional[Exception] = None
            for idx, url in enumerate(urls):
                if task._cancel.is_set():
                    self._finish_canceled(task)
                    return
                try:
                    logger.debug("任务 %s 开始下载：%s", task.task_id, url)
                    self._download_one(task, url)
                    last_err = None
                    break
                except _TaskCanceled:
                    self._finish_canceled(task)
                    return
                except Exception as e:
                    last_err = e
                    logger.warning("任务 %s 下载失败（链路 %d/%d）：%s",
                                   task.task_id, idx + 1, len(urls), e)
                    if idx < len(urls) - 1:
                        # 还有备用链，尝试下一个
                        continue
                    raise
            if last_err is not None:
                raise last_err

            # 下载刚完成时用户可能已点了取消：清理临时文件，不再落盘
            if task._cancel.is_set():
                self._finish_canceled(task)
                return

            if store_to is not None:
                # 资源模式（模组 / 地图）：校验格式并落盘
                logger.debug("任务 %s 校验资源格式并落盘 -> %s", task.task_id, store_to)
                self._finalize_resource(task, store_to, accept_ext)
            elif extract_to is not None:
                self._mark(task, TaskStatus.EXTRACTING, None)
                logger.debug("任务 %s 解压到 %s", task.task_id, extract_to)
                extract_to.mkdir(parents=True, exist_ok=True)
                try:
                    with zipfile.ZipFile(task.dest, "r") as zf:
                        bad = zf.testzip()
                        if bad is not None:
                            self._cleanup_dest(task)
                            raise RuntimeError(f"压缩包校验失败（{bad} 损坏）") from None
                        zf.extractall(extract_to)
                except zipfile.BadZipFile:
                    if allow_non_zip:
                        # 非 zip：不解压，直接把文件原样存到目标目录
                        self._store_non_zip(task, extract_to)
                    else:
                        # zip 损坏（典型场景：远端返回了 HTML 错误页）
                        self._cleanup_dest(task)
                        raise RuntimeError("下载的文件不是有效 zip") from None

            self._mark(task, TaskStatus.COMPLETED, None)
            logger.info("任务 %s 完成（%s）", task.task_id, task.dest)
            self._call_done(task, True, None)
        except _TaskCanceled:
            # 兜底：解压 / 落盘期间被取消
            self._finish_canceled(task)
        except Exception as e:
            logger.error("任务 %s 失败：%s", task.task_id, e)
            self._mark(task, TaskStatus.FAILED, str(e))
            self._call_done(task, False, str(e))

    def _call_done(self, task: DownloadTask, ok: bool, error: Optional[str]) -> None:
        """触发任务完成 / 失败回调（取消不触发）。"""
        cb = getattr(task, "_on_done", None)
        if cb is None:
            return
        try:
            cb(task.task_id, ok, error)
        except Exception:
            logger.exception("任务 %s 完成回调执行失败", task.task_id)

    def _finalize_resource(
        self,
        task: DownloadTask,
        store_to: Path,
        accept_ext: Optional[str],
    ) -> None:
        """资源落盘：按文件后缀校验后保存。

        rwmod 额外做包体检：若检测到"所有文件被包在同一个顶层文件夹、
        且其中含 mod-info.txt"（作者打包时多嵌套了一层），任务进入
        NEEDS_CONFIRM 等待用户确认是否展平修复；其余情况一律原样落盘。
        """
        ext = (accept_ext or "").strip().lower()
        store_to.parent.mkdir(parents=True, exist_ok=True)

        # 从 URL 提取原始文件名并校验后缀
        orig_name = self._pick_original_name(task)
        if orig_name and ext and Path(orig_name).suffix.lower() != ext:
            self._cleanup_dest(task)
            raise RuntimeError(
                f"REJECT:资源文件格式不正确（应为 {ext}），已拒绝下载"
            ) from None

        # 模组包嵌套检测（仅 .rwmod）：需要用户确认时阻塞等待
        if ext == ".rwmod":
            top = self._detect_nested_package(task.dest)
            if top:
                task.nested_top = top
                task._confirm_action = None
                task._confirm_evt.clear()
                self._mark(task, TaskStatus.NEEDS_CONFIRM, None)
                # 等待用户决定；超时（120 秒）按"保持原样"继续，不卡死下载线程
                task._confirm_evt.wait(timeout=120)
                if (task._confirm_action or "keep") == "fix":
                    self._flatten_nested_zip(task.dest, top)

        self._move_to(task.dest, store_to)

    @staticmethod
    def _detect_nested_package(dest: Path) -> str:
        """检测 rwmod 包是否"多嵌套一层"。

        判定条件：所有文件都在同一个顶层文件夹 {top}/ 下，
        且该文件夹内直接含 mod-info.txt。
        满足则返回顶层文件夹名；否则（结构正常 / 结构复杂 / 不是 zip）返回空串，
        保持原样落盘、不做任何处理。
        """
        try:
            with zipfile.ZipFile(dest, "r") as zf:
                names = zf.namelist()
        except Exception:
            return ""
        if not names:
            return ""
        tops: set[str] = set()
        for name in names:
            if name.endswith("/"):
                continue
            parts = name.split("/")
            if len(parts) < 2:
                return ""  # 根目录存在直接文件（如 mod-info.txt 已在根）-> 结构正常
            tops.add(parts[0])
        if len(tops) != 1:
            return ""  # 顶层有多个文件夹或根目录结构复杂 -> 不管
        top = next(iter(tops))
        if not top or f"{top}/mod-info.txt" not in names:
            return ""  # 顶层文件夹下没有 mod-info.txt -> 其他问题，不管
        return top

    @staticmethod
    def _flatten_nested_zip(dest: Path, top: str) -> None:
        """把包内单个顶层文件夹展平到根目录后重打包。

        修复失败时保留原包（保持原样落盘），不中断任务。
        """
        tmp = dest.with_name(dest.name + ".flat.tmp")
        try:
            with zipfile.ZipFile(dest, "r") as zf, zipfile.ZipFile(
                tmp, "w", zipfile.ZIP_DEFLATED
            ) as out:
                for info in zf.infolist():
                    name = info.filename
                    if name.startswith(top + "/"):
                        name = name[len(top) + 1:]
                    if not name:
                        continue  # 跳过顶层文件夹条目本身
                    out.writestr(name, zf.read(info.filename))
            tmp.replace(dest)
        except Exception as e:
            logger.warning("展平模组包 %s 失败（保持原样）：%s", dest, e)
            try:
                tmp.unlink()
            except OSError:
                pass

    @staticmethod
    def _cleanup_dest(task: DownloadTask) -> None:
        try:
            if task.dest.exists():
                task.dest.unlink()
        except OSError:
            pass

    def _finish_canceled(self, task: DownloadTask) -> None:
        """取消收尾：清理临时文件并以 canceled 状态结束。

        不把不完整的临时文件落盘为正式资源，也不覆盖已有的 canceled 状态。
        """
        self._cleanup_dest(task)
        self._mark(task, TaskStatus.CANCELED, "用户取消")

    @staticmethod
    def _move_to(src: Path, dst: Path) -> None:
        try:
            if dst.exists():
                dst.unlink()
            src.replace(dst)
        except OSError as e:
            raise RuntimeError(f"文件保存失败：{e}") from e

    def _store_non_zip(self, task: DownloadTask, extract_to: Path) -> None:
        """把非 zip 下载文件原样保存到目标目录（保留原始文件名）。"""
        name = self._pick_original_name(task) or task.dest.stem
        dest_file = extract_to / name
        try:
            if dest_file.exists():
                dest_file.unlink()
            task.dest.replace(dest_file)
        except OSError as e:
            raise RuntimeError(f"非 zip 文件保存失败：{e}") from e

    @staticmethod
    def _pick_original_name(task: DownloadTask) -> str:
        """从下载 URL 末尾提取原始文件名。

        优先用重定向后的最终地址（CDN 真实文件名通常在这里），
        取不到时回退到初始 URL。跳过脚本入口名（download.php 等）
        与无扩展名片段；全部无效时返回空串，调用方按"无法判断"处理。
        """
        script_suffixes = (".php", ".asp", ".aspx", ".jsp", ".cgi", ".do", ".action")
        for u in (task.final_url, task.url):
            if not u:
                continue
            url = str(u).split("?")[0].split("#")[0].strip()
            name = Path(url).name.strip()
            if not name or name.startswith("."):
                continue
            if name.lower().endswith(script_suffixes):
                continue
            if "." in name:
                return name
        return ""

    def _download_one(self, task: DownloadTask, url: str) -> None:
        self._mark(task, TaskStatus.DOWNLOADING, None)

        # 断点续传
        headers: dict[str, str] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        }
        existing = task.dest.stat().st_size if task.dest.exists() else 0
        if existing > 0:
            headers["Range"] = f"bytes={existing}-"

        # 限速：speed_limit_bps 为 0 或负数表示不限速
        speed_limit_bps = float(getattr(task, "speed_limit_bps", 0.0) or 0.0)
        chunk_size = self.CHUNK_SIZE
        # 如果有明确限速，把 chunk 切小以减少 throttle 的毛刺
        if speed_limit_bps > 0:
            chunk_size = max(8192, min(chunk_size, int(speed_limit_bps / 4)))

        with requests.get(url, headers=headers, stream=True, timeout=60, allow_redirects=True) as resp:
            # 记录重定向后的最终地址：下载源可能先跳到 CDN，
            # 真实文件名往往只出现在最终 URL 里
            task.final_url = resp.url or ""

            # 416 = Range 不可满足：可能是本地已下完，也可能是本地残留了旧版本文件
            if resp.status_code == 416:
                total = None
                cr = resp.headers.get("Content-Range", "")
                if cr.startswith("bytes */"):
                    try:
                        total = int(cr.split("/", 1)[1].strip())
                    except (IndexError, ValueError):
                        total = None
                if total is not None and existing == total:
                    # 本地文件大小与服务器完全一致，视为已下载完成
                    task.total_size = existing
                    task.downloaded = existing
                    self._on_progress(task.task_id, existing, existing)
                    return
                # 本地文件是旧版本 / 大小不符：删除后重新完整下载
                logger.warning(
                    "任务 %s 断点续传不可用（本地 %d 字节，服务器 %s 字节），删除后重新完整下载",
                    task.task_id, existing, total if total is not None else "未知",
                )
                self._cleanup_dest(task)
                task.downloaded = 0
                task.total_size = 0
                self._download_one(task, url)
                return

            resp.raise_for_status()

            if resp.status_code == 206:
                content_range = resp.headers.get("Content-Range", "")
                if "/" in content_range:
                    try:
                        task.total_size = int(content_range.rsplit("/", 1)[-1])
                    except ValueError:
                        pass
                mode = "ab"
            else:
                try:
                    task.total_size = int(resp.headers.get("Content-Length", 0) or 0)
                except ValueError:
                    task.total_size = 0
                existing = 0
                task.downloaded = 0
                mode = "wb"

            # 下载循环
            last_report = 0.0
            speed_window_start = time.time()
            speed_window_bytes = 0
            # 限速用的"令牌桶"：维护最近 N ms 实际下载字节数
            throttle_window_start = time.time()
            throttle_window_bytes = 0

            with task.dest.open(mode) as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if task._cancel.is_set():
                        raise _TaskCanceled()
                    if not chunk:
                        continue
                    f.write(chunk)
                    n = len(chunk)
                    task.downloaded += n
                    speed_window_bytes += n
                    throttle_window_bytes += n

                    now = time.time()
                    # 限速：保持 throttle_window (1s) 内的字节数不超过 speed_limit_bps
                    if speed_limit_bps > 0:
                        win_dur = now - throttle_window_start
                        # 1 秒滑动窗口：超过就 sleep
                        if win_dur < 1.0:
                            allowed = speed_limit_bps * win_dur
                            if throttle_window_bytes > allowed:
                                # 需要 sleep 到 (throttle_window_bytes / speed_limit_bps)
                                target_total = throttle_window_bytes / speed_limit_bps
                                sleep_for = target_total - win_dur
                                if sleep_for > 0:
                                    time.sleep(sleep_for)
                                    now = time.time()
                        # 滑出窗口
                        if now - throttle_window_start > 1.0:
                            throttle_window_start = now
                            throttle_window_bytes = 0

                    if now - last_report > self.PROGRESS_INTERVAL:
                        # 计算瞬时速度（基于本窗口）
                        win = now - speed_window_start
                        if win > 0:
                            task.speed_bps = speed_window_bytes / win
                        speed_window_start = now
                        speed_window_bytes = 0
                        # 总是上报（即使 total=0，前端也能按字节/速度显示）
                        self._on_progress(
                            task.task_id, task.downloaded, task.total_size
                        )
                        last_report = now

        # 最终上报一次（让 UI 跑到 100% 或显示完整字节数）
        task.speed_bps = 0.0
        self._on_progress(task.task_id, task.downloaded, task.total_size)

    def _mark(self, task: DownloadTask, status: TaskStatus, error: Optional[str]) -> None:
        task.status = status
        task.error = error
        try:
            self._on_status(task.task_id, status.value, error)
        except Exception:
            # 回调中异常不应杀线程
            pass


# 暴露给前端（通过 evaluate_js payload）的人类可读格式
def format_bytes(n: float) -> str:
    return _format_bytes(n)
