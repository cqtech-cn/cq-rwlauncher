"""下载管理器：专门用于版本下载的独立管理器，提供多线程下载和进度管理功能。"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DownloadStatus(str, Enum):
    """下载状态枚举。"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


# 终态任务：不参与活跃列表
_TERMINAL_STATUSES = {DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELED}


@dataclass
class VersionDownloadTask:
    """版本下载任务信息。"""
    task_id: str
    version: str
    url: str
    dest_path: Path
    expected_size: int = 0
    downloaded_size: int = 0
    status: DownloadStatus = DownloadStatus.PENDING
    speed_bps: float = 0.0
    progress: float = 0.0
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    checksum: Optional[str] = None
    _cancel_event: threading.Event = field(default_factory=threading.Event)
    _pause_event: threading.Event = field(default_factory=threading.Event)
    _thread: Optional[threading.Thread] = field(default=None)


ProgressCallback = Callable[[str, int, int, float], None]  # task_id, downloaded, total, progress
StatusCallback = Callable[[str, str, Optional[str]], None]  # task_id, status, error
CompletionCallback = Callable[[str, bool, Optional[str]], None]  # task_id, success, error


class DownloadManager:
    """版本下载管理器。"""
    
    CHUNK_SIZE = 64 * 1024
    PROGRESS_INTERVAL = 0.5  # 500ms
    MAX_CONCURRENT_DOWNLOADS = 3  # 最大并发下载数
    
    def __init__(
        self,
        on_progress: ProgressCallback,
        on_status: StatusCallback,
        on_completion: CompletionCallback
    ) -> None:
        """初始化下载管理器。
        
        Args:
            on_progress: 进度回调函数
            on_status: 状态回调函数
            on_completion: 完成回调函数
        """
        self._on_progress = on_progress
        self._on_status = on_status
        self._on_completion = on_completion
        self._tasks: Dict[str, VersionDownloadTask] = {}
        self._lock = threading.Lock()
        self._active_downloads = 0
        self._download_sem = threading.Semaphore(self.MAX_CONCURRENT_DOWNLOADS)
    
    def submit_download(
        self,
        task_id: str,
        version: str,
        url: str,
        dest_path: Path,
        expected_size: int = 0,
        checksum: Optional[str] = None,
        resume_partial: bool = True
    ) -> VersionDownloadTask:
        """提交一个版本下载任务。
        
        Args:
            task_id: 任务唯一标识
            version: 版本号
            url: 下载地址
            dest_path: 目标文件路径
            expected_size: 预期文件大小
            checksum: 文件校验和
            resume_partial: 是否支持断点续传
            
        Returns:
            下载任务对象
        """
        with self._lock:
            # 检查是否已有相同任务
            existing_task = self._tasks.get(task_id)
            if existing_task and existing_task.status not in _TERMINAL_STATUSES:
                return existing_task
            
            # 清理已完成的任务
            self._cleanup_completed_tasks()
            
            # 创建下载任务
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 检查是否已存在部分下载的文件
            resume_offset = 0
            if resume_partial and dest_path.exists():
                resume_offset = dest_path.stat().st_size
            
            task = VersionDownloadTask(
                task_id=task_id,
                version=version,
                url=url,
                dest_path=dest_path,
                expected_size=expected_size,
                downloaded_size=resume_offset,
                status=DownloadStatus.PENDING,
                checksum=checksum
            )
            
            self._tasks[task_id] = task
            logger.info("提交下载任务：%s - 版本 %s：%s", task_id, version, url)
            
            # 启动下载线程
            download_thread = threading.Thread(
                target=self._download_worker,
                args=(task,),
                daemon=True,
                name=f"download-{version}-{task_id}"
            )
            task._thread = download_thread
            download_thread.start()
            
            return task
    
    def get_task(self, task_id: str) -> Optional[VersionDownloadTask]:
        """获取下载任务信息。
        
        Args:
            task_id: 任务ID
            
        Returns:
            下载任务对象，如果不存在返回None
        """
        with self._lock:
            return self._tasks.get(task_id)
    
    def pause_download(self, task_id: str) -> bool:
        """暂停下载任务。
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否成功暂停
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.status == DownloadStatus.DOWNLOADING:
                if task:
                    task._pause_event.set()
                    task.status = DownloadStatus.PAUSED
                    self._on_status(task_id, DownloadStatus.PAUSED.value, None)
                    logger.info("任务 %s 已暂停", task_id)
                return True
            return False
    
    def resume_download(self, task_id: str) -> bool:
        """恢复下载任务。
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否成功恢复
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.status == DownloadStatus.PAUSED:
                if task:
                    task._pause_event.clear()
                    if task.status == DownloadStatus.PAUSED:
                        self._start_download(task)
                return True
            return False
    
    def cancel_download(self, task_id: str) -> bool:
        """取消下载任务。
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否成功取消
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status not in _TERMINAL_STATUSES:
                task._cancel_event.set()
                logger.info("任务 %s 已取消", task_id)
                return True
            return False
    
    def list_active_tasks(self) -> List[Dict]:
        """获取活跃的任务列表。
        
        Returns:
            活跃任务信息列表
        """
        with self._lock:
            active_tasks = []
            for task in self._tasks.values():
                if task.status not in _TERMINAL_STATUSES:
                    task_info = {
                        "task_id": task.task_id,
                        "version": task.version,
                        "status": task.status.value,
                        "downloaded": task.downloaded_size,
                        "total": task.expected_size,
                        "progress": task.progress,
                        "speed": task.speed_bps,
                        "error": task.error
                    }
                    active_tasks.append(task_info)
            return active_tasks
    
    def get_task_statistics(self) -> Dict:
        """获取下载统计信息。
        
        Returns:
            下载统计信息
        """
        with self._lock:
            total_tasks = len(self._tasks)
            active_tasks = len([t for t in self._tasks.values() if t.status not in _TERMINAL_STATUSES])
            completed_tasks = len([t for t in self._tasks.values() if t.status == DownloadStatus.COMPLETED])
            failed_tasks = len([t for t in self._tasks.values() if t.status == DownloadStatus.FAILED])
            canceled_tasks = len([t for t in self._tasks.values() if t.status == DownloadStatus.CANCELED])
            
            return {
                "total_tasks": total_tasks,
                "active_tasks": active_tasks,
                "completed_tasks": completed_tasks,
                "failed_tasks": failed_tasks,
                "canceled_tasks": canceled_tasks,
                "active_downloads": self._active_downloads
            }
    
    def _cleanup_completed_tasks(self) -> None:
        """清理已完成的任务。"""
        with self._lock:
            # 移除已完成的任务，保留最近10个
            completed_tasks = [
                (k, v) for k, v in self._tasks.items() 
                if v.status in _TERMINAL_STATUSES
            ]
            
            if len(completed_tasks) > 10:
                # 按结束时间排序，保留最新的10个
                completed_tasks.sort(key=lambda x: x[1].end_time or 0, reverse=True)
                for task_id, task in completed_tasks[10:]:
                    del self._tasks[task_id]
                logger.info("清理了 %d 个旧任务", len(completed_tasks) - 10)
    
    def _start_download(self, task: VersionDownloadTask) -> None:
        """启动下载任务。
        
        Args:
            task: 下载任务
        """
        if self._active_downloads >= self.MAX_CONCURRENT_DOWNLOADS:
            return
        
        self._active_downloads += 1
        task.status = DownloadStatus.DOWNLOADING
        task.start_time = time.time()
        self._on_status(task.task_id, DownloadStatus.DOWNLOADING.value, None)
    
    def _download_worker(self, task: VersionDownloadTask) -> None:
        """下载工作线程。
        
        Args:
            task: 下载任务
        """
        try:
            # 等待下载信号
            while task._pause_event.is_set():
                time.sleep(0.1)
            
            # 获取下载信号
            with self._download_sem:
                self._start_download(task)
                
                # 执行下载
                self._download_file(task)
                
                # 验证下载文件
                if task._cancel_event.is_set():
                    self._handle_task_canceled(task)
                    return
                
                if self._verify_download(task):
                    self._handle_task_completed(task)
                else:
                    self._handle_task_failed(task, "文件校验失败")
                    
        except Exception as e:
            self._handle_task_failed(task, str(e))
        finally:
            self._active_downloads -= 1
    
    def _download_file(self, task: VersionDownloadTask) -> None:
        """下载文件。
        
        Args:
            task: 下载任务
        """
        import requests
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        # 计算断点续传起始位置
        resume_offset = task.downloaded_size
        if resume_offset > 0:
            headers["Range"] = f"bytes={resume_offset}-"
            logger.info("任务 %s 续传下载，起始位置：%d 字节", task.task_id, resume_offset)
        
        try:
            with requests.get(task.url, headers=headers, stream=True, timeout=300) as response:
                response.raise_for_status()
                
                # 获取文件总大小
                if resume_offset > 0 and response.status_code == 206:
                    # 断点续传模式
                    content_range = response.headers.get("Content-Range", "")
                    if "/" in content_range:
                        total_size = int(content_range.rsplit("/", 1)[-1])
                    else:
                        total_size = task.expected_size
                else:
                    # 完整下载模式
                    total_size = int(response.headers.get('Content-Length', 0) or task.expected_size)
                
                if total_size <= 0:
                    total_size = task.expected_size
                
                task.expected_size = total_size
                
                # 下载循环
                last_progress_time = 0
                downloaded_since_last = 0
                speed_window_start = time.time()
                
                mode = "ab" if resume_offset > 0 else "wb"
                
                with task.dest_path.open(mode) as file:
                    for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                        if task._cancel_event.is_set():
                            raise Exception("任务被取消")
                        
                        if task._pause_event.is_set():
                            time.sleep(0.1)  # 等待恢复
                            continue
                        
                        if chunk:
                            file.write(chunk)
                            task.downloaded_size += len(chunk)
                            downloaded_since_last += len(chunk)
                            
                            # 计算进度
                            if total_size > 0:
                                task.progress = task.downloaded_size / total_size
                            
                            # 更新速度
                            now = time.time()
                            time_diff = now - speed_window_start
                            if time_diff >= 1.0:
                                task.speed_bps = downloaded_since_last / time_diff
                                speed_window_start = now
                                downloaded_since_last = 0
                            
                            # 上报进度（限制频率）
                            if now - last_progress_time > self.PROGRESS_INTERVAL:
                                self._on_progress(
                                    task.task_id,
                                    task.downloaded_size,
                                    total_size,
                                    task.progress
                                )
                                last_progress_time = now
                
                logger.info("任务 %s 下载完成：%.2f MB", 
                           task.task_id, task.downloaded_size / 1024 / 1024)
                
        except requests.RequestException as e:
            raise Exception(f"下载请求失败：{e}")
    
    def _verify_download(self, task: VersionDownloadTask) -> bool:
        """验证下载的文件。
        
        Args:
            task: 下载任务
            
        Returns:
            是否验证通过
        """
        if not task.checksum:
            return True
        
        try:
            file_size = task.dest_path.stat().st_size
            if file_size != task.expected_size and task.expected_size > 0:
                logger.warning("任务 %s 文件大小不匹配：预期 %d，实际 %d", 
                             task.task_id, task.expected_size, file_size)
                return False
            
            # 计算文件校验和
            checksum_hash = hashlib.md5()
            with task.dest_path.open('rb') as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    checksum_hash.update(chunk)
            
            actual_checksum = checksum_hash.hexdigest()
            expected_checksum = task.checksum.lower()
            actual_checksum = actual_checksum.lower()
            
            if actual_checksum != expected_checksum:
                logger.warning("任务 %s 文件校验和不匹配：预期 %s，实际 %s", 
                             task.task_id, expected_checksum, actual_checksum)
                return False
            
            logger.info("任务 %s 文件验证通过", task.task_id)
            return True
            
        except Exception as e:
            logger.error("任务 %s 文件验证失败：%s", task.task_id, e)
            return False
    
    def _handle_task_completed(self, task: VersionDownloadTask) -> None:
        """处理任务完成。
        
        Args:
            task: 下载任务
        """
        task.status = DownloadStatus.COMPLETED
        task.end_time = time.time()
        self._on_status(task.task_id, DownloadStatus.COMPLETED.value, None)
        self._on_completion(task.task_id, True, None)
        logger.info("任务 %s 完成", task.task_id)
    
    def _handle_task_failed(self, task: VersionDownloadTask, error: str) -> None:
        """处理任务失败。
        
        Args:
            task: 下载任务
            error: 错误信息
        """
        task.status = DownloadStatus.FAILED
        task.error = error
        task.end_time = time.time()
        self._on_status(task.task_id, DownloadStatus.FAILED.value, error)
        self._on_completion(task.task_id, False, error)
        logger.error("任务 %s 失败：%s", task.task_id, error)
    
    def _handle_task_canceled(self, task: VersionDownloadTask) -> None:
        """处理任务取消。
        
        Args:
            task: 下载任务
        """
        task.status = DownloadStatus.CANCELED
        task.end_time = time.time()
        self._on_status(task.task_id, DownloadStatus.CANCELED.value, "用户取消")
        self._on_completion(task.task_id, False, "用户取消")
        logger.info("任务 %s 被用户取消", task.task_id)
        
        # 清理不完整的下载文件
        try:
            if task.dest_path.exists() and task.expected_size > 0:
                if task.dest_path.stat().st_size < task.expected_size:
                    task.dest_path.unlink()
                    logger.info("清理了不完整的下载文件：%s", task.dest_path)
        except OSError:
            pass


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小为人类可读格式。
    
    Args:
        size_bytes: 字节数
        
    Returns:
        格式化后的文件大小字符串
    """
    if size_bytes == 0:
        return "0 B"
    
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    unit_index = 0
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    return f"{size:.1f} {units[unit_index]}"


def format_speed(speed_bps: float) -> str:
    """格式化下载速度为人类可读格式。
    
    Args:
        speed_bps: 每秒字节数
        
    Returns:
        格式化后的速度字符串
    """
    if speed_bps <= 0:
        return "0 B/s"
    
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    speed = float(speed_bps)
    unit_index = 0
    
    while speed >= 1024 and unit_index < len(units) - 1:
        speed /= 1024
        unit_index += 1
    
    return f"{speed:.1f} {units[unit_index]}"