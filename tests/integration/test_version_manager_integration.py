"""版本管理集成测试。

覆盖新架构下的完整链路：
1. 远程清单拉取解析 -> 本地 versions 目录扫描
2. bridge 切换 / 启动 / 卸载串联
3. 并发读取清单缓存
4. 异常清单的错误降级
5. 长版本号任务 ID 规约
"""
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.bridge import Bridge
from backend.config import Config
from backend.version_manager import EditionInfo, VersionInfo, VersionManager


MANIFEST = {
    "editions": [
        {
            "name": "default",
            "latest_version": "1.15",
            "versions": [
                {"version": "1.15", "download_url": "https://example.com/1.15.zip",
                 "release_date": "2026-09-01", "info": "正式版"},
                {"version": "1.14", "download_url": "https://example.com/1.14.zip",
                 "release_date": "2026-05-10", "info": "稳定版"},
            ],
        }
    ]
}


class TestVersionManagerIntegration(unittest.TestCase):
    """版本管理与桥接器集成测试。"""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.config_path = self.temp_dir / "config.json"
        self.game_root = self.temp_dir / "game"
        self.game_root.mkdir()
        self.config_path.write_text(
            json.dumps(
                {
                    "game_install_path": str(self.game_root),
                    "game_exe_name": "RustedWarfare.exe",
                    "game_selected_version": "",
                    "game_version_list": {"url": "https://example.com/windows.json"},
                }
            ),
            encoding="utf-8",
        )
        self.config = Config(self.config_path)
        self.bridge = Bridge(self.config)
        self.vm = self.bridge._version_manager

    def tearDown(self) -> None:
        self.bridge._monitor.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _patch_manifest(self) -> MagicMock:
        m = patch("backend.version_manager.urllib.request.urlopen")
        started = m.start()
        self.addCleanup(m.stop)
        resp = started.return_value.__enter__.return_value
        resp.read.return_value = json.dumps(MANIFEST).encode("utf-8")
        return started

    def _install_local_version(self, version: str) -> Path:
        d = self.vm.version_dir(version) / "Rusted"
        d.mkdir(parents=True, exist_ok=True)
        exe = d / "RustedWarfare.exe"
        exe.write_text("fake", encoding="utf-8")
        return exe

    def test_bridge_exposes_new_version_api(self) -> None:
        """旧版启动器 exe 语义的方法应已下线，新方法齐备。"""
        for name in (
            "get_editions",
            "get_remote_versions",
            "get_installed_versions",
            "get_version_details",
            "get_current_version",
            "switch_version",
            "launch_version",
            "install_version",
            "uninstall_version",
            "get_available_installations",
            "clear_version_cache",
            "check_version_manifest",
            "compare_versions",
        ):
            self.assertTrue(callable(getattr(self.bridge, name)), name)
        for removed in ("download_version", "get_version_info"):
            self.assertFalse(hasattr(self.bridge, removed), removed)

    def test_full_manifest_to_switch_workflow(self) -> None:
        """清单拉取 -> 本地扫描 -> 切换 -> 启动 -> 卸载 全链路。"""
        started = self._patch_manifest()

        # 远程清单
        editions = self.vm.get_editions()
        self.assertEqual([v.version for v in editions[0].versions], ["1.15", "1.14"])
        remote = self.bridge.get_remote_versions()
        self.assertEqual([v["version"] for v in remote], ["1.15", "1.14"])

        # 第二次读取命中缓存
        self.vm.get_editions()
        self.assertEqual(started.call_count, 1)

        # 本地装两个版本
        self._install_local_version("1.14")
        self._install_local_version("1.15")
        installed = self.bridge.get_installed_versions()
        self.assertEqual([v["version"] for v in installed], ["1.15", "1.14"])

        # 切换到 1.14（不是最新也允许）
        res = self.bridge.switch_version("1.14")
        self.assertTrue(res["ok"], res.get("error"))
        self.assertEqual(self.bridge.get_current_version(), "1.14")

        # 启动当前选中版本
        with patch("backend.launcher.subprocess.Popen") as mock_popen, \
             patch("backend.diagnoser.game_procs", return_value=[]):
            mock_popen.return_value = MagicMock(pid=1)
            launch = self.bridge.quick_launch()
        self.assertTrue(launch["ok"], launch.get("error"))
        self.assertEqual(launch["version"], "1.14")

        # 模拟游戏已退出，监听复位后才允许切换
        self.bridge._monitor.stop()

        # 当前版本禁止卸载
        blocked = self.bridge.uninstall_version("1.14")
        self.assertFalse(blocked["ok"])

        # 切到 1.15 后再卸载 1.14
        self.assertTrue(self.bridge.switch_version("1.15")["ok"])
        removed = self.bridge.uninstall_version("1.14")
        self.assertTrue(removed["ok"], removed.get("error"))
        self.assertFalse(self.vm.is_version_installed("1.14"))
        self.assertTrue(self.vm.is_version_installed("1.15"))

    def test_concurrent_manifest_reads(self) -> None:
        """多线程并发读取清单不应抛异常。"""
        self._patch_manifest()
        errors: list[Exception] = []
        results: list[int] = []

        def worker() -> None:
            try:
                for _ in range(3):
                    results.append(len(self.vm.get_remote_versions()))
            except Exception as e:  # noqa: BLE001 - 测试需要收集任何异常
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 15)
        self.assertTrue(all(n == 2 for n in results))

    def test_invalid_manifest_degrades_gracefully(self) -> None:
        """清单不是 JSON：管理器抛错，桥接层降级为空列表。"""
        m = patch("backend.version_manager.urllib.request.urlopen")
        started = m.start()
        self.addCleanup(m.stop)
        started.return_value.__enter__.return_value.read.return_value = b"<html>error</html>"

        with self.assertRaises(RuntimeError):
            self.vm.get_editions(use_cache=False)
        self.assertEqual(self.bridge.get_editions(), [])
        self.assertEqual(self.bridge.get_remote_versions(), [])

        # 连通性检查要把错误透传给设置页
        check = self.bridge.check_version_manifest()
        self.assertFalse(check["ok"])
        self.assertTrue(check["error"])

    def test_check_manifest_counts_editions(self) -> None:
        with patch.object(
            self.vm,
            "get_editions",
            return_value=[EditionInfo(name="default"), EditionInfo(name="zhc")],
        ):
            res = self.bridge.check_version_manifest()
        self.assertTrue(res["ok"])
        self.assertEqual(res["editions"], 2)

    def test_long_version_task_id_is_shortened(self) -> None:
        """超长版本号的任务 ID 改用 md5 前 12 位，保证长度受限。"""
        long_version = "1.15p11-ZHC-Fix3-very-long-version-name-2026-special-build"
        info = VersionInfo(version=long_version, url="https://example.com/x.zip")
        with patch.object(self.vm, "find_remote_version", return_value=info), \
             patch.object(self.vm, "is_version_installed", return_value=False), \
             patch.object(self.bridge._downloader, "get", return_value=None), \
             patch.object(self.bridge._downloader, "submit") as mock_submit:
            res = self.bridge.install_version(long_version)
        self.assertTrue(res["ok"], res.get("error"))
        task_id = res["task_id"]
        self.assertTrue(task_id.startswith("ver_install_"))
        self.assertLessEqual(len(task_id), 60)


if __name__ == "__main__":
    unittest.main()
