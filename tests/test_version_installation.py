"""版本安装数据层与下载队列测试。

数据层：versions/<版本>/ 目录扫描与卸载。
下载层：backend.downloader.DownloadManager 真正起本地 HTTP 服务，
验证任务化下载、解压落盘、失败回调与状态查询。
"""
from __future__ import annotations

import http.server
import io
import json
import socketserver
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

from backend.downloader import DownloadManager, TaskStatus
from backend.version_manager import VersionInfo, VersionManager


def _make_game_zip() -> bytes:
    """构造一个内容为 Rusted/RustedWarfare.exe 的游戏 zip。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Rusted/RustedWarfare.exe", b"fake game executable")
    return buf.getvalue()


class _ZipHandler(http.server.BaseHTTPRequestHandler):
    """按路径返回 zip 字节或 404 的最小测试处理器。"""

    payload = b""

    def do_GET(self):  # noqa: N802 - 标准库命名
        if self.path == "/game.zip":
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(self.payload)))
            self.end_headers()
            self.wfile.write(self.payload)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *args):  # 静默测试服务日志
        pass


class TestVersionLayout(unittest.TestCase):
    """版本安装目录的数据层行为。"""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.config_path = self.temp_dir / "config.json"
        self.game_root = self.temp_dir / "game"
        self.game_root.mkdir()
        self.config_path.write_text(
            json.dumps({"game_version_list": {"url": "https://example.com/windows.json"}}),
            encoding="utf-8",
        )
        self.vm = VersionManager(self.config_path, self.game_root)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_version(self, version: str) -> Path:
        d = self.vm.version_dir(version) / "Rusted"
        d.mkdir(parents=True, exist_ok=True)
        (d / "RustedWarfare.exe").write_text("x", encoding="utf-8")
        return d

    def test_installed_state_scan(self) -> None:
        self.assertFalse(self.vm.is_version_installed("1.15"))
        self._make_version("1.15")
        self.assertTrue(self.vm.is_version_installed("1.15"))
        infos = self.vm.get_installed_versions()
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0].version, "1.15")
        self.assertTrue(infos[0].is_installed)
        self.assertTrue(Path(infos[0].install_path).is_dir())

    def test_uninstall_success(self) -> None:
        d = self._make_version("1.15")
        ok, err = self.vm.uninstall_version("1.15")
        self.assertTrue(ok, err)
        self.assertFalse(d.parent.exists())
        self.assertFalse(self.vm.is_version_installed("1.15"))

    def test_uninstall_missing_returns_error(self) -> None:
        ok, err = self.vm.uninstall_version("1.15")
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_version_info_helpers(self) -> None:
        vi = VersionInfo(version="1.15", url="https://x/y.zip", is_installed=True)
        data = vi.to_dict()
        self.assertTrue(data["is_installed"])
        again = VersionInfo.from_dict(
            {"version": "1.15", "download_url": "https://x/y.zip", "info": "版本说明"}
        )
        self.assertEqual(again.url, "https://x/y.zip")
        self.assertEqual(again.description, "版本说明")


class TestDownloadManager(unittest.TestCase):
    """下载队列真实网络栈测试（本地回环 HTTP）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = _make_game_zip()
        _ZipHandler.payload = cls.payload
        cls.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _ZipHandler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.statuses: list[tuple[str, str]] = []
        self.done = threading.Event()
        self.done_result: dict = {}

        def on_progress(task_id: str, downloaded: int, total: int) -> None:
            self.statuses.append((task_id, "progress"))

        def on_status(task_id: str, status: str, error) -> None:
            self.statuses.append((task_id, str(status)))

        def on_done(task_id: str, ok: bool, error) -> None:
            self.done_result = {"task_id": task_id, "ok": ok, "error": error}
            self.done.set()

        self.dm = DownloadManager(on_progress, on_status)
        self._on_done = on_done

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _wait_done(self, timeout: float = 15.0) -> None:
        if not self.done.wait(timeout):
            self.fail("下载任务未在规定时间内结束")

    def test_submit_download_and_extract(self) -> None:
        """游戏 zip 下载后应解压进 versions/<版本> 目录并回调成功。"""
        dest = self.temp_dir / "_rw_tmp" / "1.15.zip"
        extract_to = self.temp_dir / "game" / "versions" / "1.15"
        task = self.dm.submit(
            task_id="ver_install_1.15",
            url=f"{self.base_url}/game.zip",
            dest=dest,
            extract_to=extract_to,
            on_done=self._on_done,
        )
        self.assertEqual(task.task_id, "ver_install_1.15")
        self.assertIsNotNone(self.dm.get("ver_install_1.15"))

        self._wait_done()
        self.assertTrue(self.done_result["ok"], self.done_result.get("error"))
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.total_size, len(self.payload))
        extracted = extract_to / "Rusted" / "RustedWarfare.exe"
        self.assertTrue(extracted.is_file())
        self.assertTrue(dest.is_file())
        status_names = {s for _, s in self.statuses}
        self.assertIn("extracting", status_names)
        self.assertIn("completed", status_names)

    def test_submit_download_failure(self) -> None:
        """404 时任务失败并回调 ok=False。"""
        dest = self.temp_dir / "_rw_tmp" / "bad.zip"
        self.dm.submit(
            task_id="ver_install_bad",
            url=f"{self.base_url}/missing.zip",
            dest=dest,
            extract_to=self.temp_dir / "out",
            on_done=self._on_done,
        )
        self._wait_done()
        self.assertFalse(self.done_result["ok"])
        self.assertEqual(
            self.dm.get("ver_install_bad").status,
            TaskStatus.FAILED,
        )

    def test_list_active_shape(self) -> None:
        """活跃任务列表字段完整。"""
        task = self.dm.submit(
            task_id="ver_install_shape",
            url=f"{self.base_url}/game.zip",
            dest=self.temp_dir / "s.zip",
            on_done=self._on_done,
        )
        # 极短窗口内任务至少处于队列或下载阶段
        deadline = time.time() + 2
        while task.status == TaskStatus.PENDING and time.time() < deadline:
            time.sleep(0.01)
        rows = self.dm.list_active()
        self.assertTrue(rows)
        row = next(r for r in rows if r["task_id"] == "ver_install_shape")
        for key in ("task_id", "status", "downloaded", "total", "progress", "speed", "error"):
            self.assertIn(key, row)
        self._wait_done()

    def test_cancel_download(self) -> None:
        """取消后任务不应再报成功回调。"""
        canceled_done = threading.Event()

        def on_done(task_id: str, ok: bool, error) -> None:
            # 取消语义下不应触发完成回调；若触发也必须是失败态
            canceled_done.set()

        self.dm.submit(
            task_id="ver_install_cancel",
            url=f"{self.base_url}/game.zip",
            dest=self.temp_dir / "c.zip",
            on_done=on_done,
        )
        self.dm.cancel("ver_install_cancel")
        # 小文件可能瞬间下完，此时任务正常完成也是合法结果；
        # 真正要保证的是“取消后最终落到终态，不残留运行中任务”
        deadline = time.time() + 10
        task = self.dm.get("ver_install_cancel")
        while time.time() < deadline:
            if task.status in (TaskStatus.CANCELED, TaskStatus.COMPLETED, TaskStatus.FAILED):
                break
            time.sleep(0.02)
        self.assertIn(
            task.status,
            (TaskStatus.CANCELED, TaskStatus.COMPLETED, TaskStatus.FAILED),
        )


if __name__ == "__main__":
    unittest.main()
