"""bridge.py 版本管理 API 测试。

覆盖方法：
get_editions / get_remote_versions / get_installed_versions /
get_version_details / get_version_install_path / is_version_installed /
get_current_version / switch_version / launch_version / quick_launch /
install_version / uninstall_version / get_available_installations /
clear_version_cache / check_version_manifest / compare_versions
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.bridge import Bridge
from backend.config import Config
from backend.version_manager import EditionInfo, VersionInfo


class TestVersionManagementAPI(unittest.TestCase):
    """版本管理桥接 API 测试。"""

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
        import shutil
        self.bridge._monitor.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_installed(self, version: str, *, nested: bool = True) -> Path:
        """在桥接器的 versions 根下造一个可启动的版本目录。"""
        base = self.vm.version_dir(version)
        d = base / "Rusted" if nested else base
        d.mkdir(parents=True, exist_ok=True)
        exe = d / "RustedWarfare.exe"
        exe.write_text("fake", encoding="utf-8")
        return exe

    # -------- 清单与列表 --------

    def test_get_editions(self) -> None:
        editions = [EditionInfo(name="default", latest_version="1.15")]
        with patch.object(self.vm, "get_editions", return_value=editions):
            result = self.bridge.get_editions()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "default")
        self.assertEqual(result[0]["latest_version"], "1.15")

    def test_get_editions_swallows_error(self) -> None:
        with patch.object(self.vm, "get_editions", side_effect=RuntimeError("x")):
            self.assertEqual(self.bridge.get_editions(), [])

    def test_get_remote_and_installed_versions(self) -> None:
        remote = [VersionInfo(version="1.15", url="https://x/1.15.zip")]
        installed = [VersionInfo(version="1.14", is_installed=True, install_path="p")]
        with patch.object(self.vm, "get_remote_versions", return_value=remote), \
             patch.object(self.vm, "get_installed_versions", return_value=installed):
            r = self.bridge.get_remote_versions()
            i = self.bridge.get_installed_versions()
        self.assertEqual(r[0]["version"], "1.15")
        self.assertEqual(i[0]["version"], "1.14")
        self.assertTrue(i[0]["is_installed"])

    def test_get_version_details(self) -> None:
        with patch.object(self.vm, "get_remote_versions", return_value=[VersionInfo(version="1.15")]):
            hit = self.bridge.get_version_details("1.15")
            miss = self.bridge.get_version_details("9.9")
        self.assertEqual(hit["version"], "1.15")
        self.assertEqual(miss, {})

    def test_get_version_install_path(self) -> None:
        self._make_installed("1.15", nested=False)
        p = self.bridge.get_version_install_path("1.15")
        self.assertIsNotNone(p)
        self.assertTrue(p.endswith("1.15"))
        self.assertIsNone(self.bridge.get_version_install_path("9.9"))

    def test_is_version_installed(self) -> None:
        self.assertFalse(self.bridge.is_version_installed("1.15"))
        self._make_installed("1.15")
        self.assertTrue(self.bridge.is_version_installed("1.15"))

    # -------- 当前版本与切换 --------

    def test_get_current_version_validation(self) -> None:
        # 未选择
        self.assertIsNone(self.bridge.get_current_version())
        # 选择了但目录不存在
        self.config.set("game_selected_version", "9.9")
        self.assertIsNone(self.bridge.get_current_version())
        # 已安装才返回
        self._make_installed("1.15")
        self.config.set("game_selected_version", "1.15")
        self.assertEqual(self.bridge.get_current_version(), "1.15")

    def test_switch_version_not_installed(self) -> None:
        res = self.bridge.switch_version("9.9")
        self.assertFalse(res["ok"])
        self.assertIsNone(res["version"])
        self.assertIn("未安装", res["error"])

    def test_switch_version_blocked_while_running(self) -> None:
        self._make_installed("1.15")
        self.bridge._monitor._active = True
        try:
            res = self.bridge.switch_version("1.15")
        finally:
            self.bridge._monitor._active = False
        self.assertFalse(res["ok"])
        self.assertIn("运行", res["error"])

    def test_switch_version_success(self) -> None:
        self._make_installed("1.15")
        res = self.bridge.switch_version("1.15")
        self.assertTrue(res["ok"], res.get("error"))
        self.assertEqual(res["current_version"], "1.15")
        self.assertEqual(self.config.get("game_selected_version"), "1.15")
        self.assertIn("1.15", res["install_path"])

    # -------- 启动 --------

    @patch("backend.launcher.subprocess.Popen")
    def test_launch_version_success(self, mock_popen) -> None:
        self._make_installed("1.15")
        mock_popen.return_value = MagicMock(pid=43210)
        with patch("backend.diagnoser.game_procs", return_value=[]):
            res = self.bridge.launch_version("1.15", "--windowed")
        self.assertTrue(res["ok"], res.get("error"))
        self.assertEqual(res["mode"], "exe")
        self.assertEqual(self.config.get("game_selected_version"), "1.15")
        mock_popen.assert_called_once()

    def test_launch_version_not_installed(self) -> None:
        with patch("backend.launcher.subprocess.Popen") as mock_popen:
            res = self.bridge.launch_version("9.9")
        self.assertFalse(res["ok"])
        mock_popen.assert_not_called()

    @patch("backend.launcher.subprocess.Popen")
    def test_quick_launch_uses_selected_version(self, mock_popen) -> None:
        self._make_installed("1.15")
        self.config.set("game_selected_version", "1.15")
        mock_popen.return_value = MagicMock(pid=43211)
        with patch("backend.diagnoser.game_procs", return_value=[]):
            res = self.bridge.quick_launch(None, "")
        self.assertTrue(res["ok"], res.get("error"))

    def test_quick_launch_without_selection(self) -> None:
        res = self.bridge.quick_launch()
        self.assertFalse(res["ok"])

    # -------- 安装任务化 --------

    def test_install_version_remote_missing(self) -> None:
        with patch.object(self.vm, "find_remote_version", return_value=None):
            res = self.bridge.install_version("9.9")
        self.assertFalse(res["ok"])
        self.assertIsNone(res["task_id"])

    def test_install_version_already_installed(self) -> None:
        info = VersionInfo(version="1.15", url="https://x/1.15.zip")
        with patch.object(self.vm, "find_remote_version", return_value=info), \
             patch.object(self.vm, "is_version_installed", return_value=True):
            res = self.bridge.install_version("1.15")
        self.assertTrue(res["ok"])
        self.assertTrue(res["already_installed"])
        self.assertIsNone(res["task_id"])

    def test_install_version_submits_task(self) -> None:
        info = VersionInfo(
            version="1.15",
            url="https://x/1.15.zip",
            file_size=4096,
            description="正式版",
        )
        with patch.object(self.vm, "find_remote_version", return_value=info), \
             patch.object(self.vm, "is_version_installed", return_value=False), \
             patch.object(self.bridge._downloader, "get", return_value=None), \
             patch.object(self.bridge._downloader, "submit") as mock_submit:
            res = self.bridge.install_version("1.15")
        self.assertTrue(res["ok"], res.get("error"))
        self.assertEqual(res["task_id"], "ver_install_1.15")
        self.assertEqual(res["file_size"], 4096)
        kwargs = mock_submit.call_args.kwargs
        self.assertEqual(kwargs["url"], "https://x/1.15.zip")
        self.assertEqual(kwargs["extract_to"], self.vm.version_dir("1.15"))

    def test_install_version_reuses_active_task(self) -> None:
        info = VersionInfo(version="1.15", url="https://x/1.15.zip")
        active = MagicMock()
        active.status = "downloading"
        with patch.object(self.vm, "find_remote_version", return_value=info), \
             patch.object(self.vm, "is_version_installed", return_value=False), \
             patch.object(self.bridge._downloader, "get", return_value=active):
            res = self.bridge.install_version("1.15")
        self.assertTrue(res["ok"])
        self.assertTrue(res["reused"])
        self.assertEqual(res["task_id"], "ver_install_1.15")

    # -------- 卸载 --------

    def test_uninstall_current_rejected(self) -> None:
        self._make_installed("1.15")
        self.config.set("game_selected_version", "1.15")
        res = self.bridge.uninstall_version("1.15")
        self.assertFalse(res["ok"])
        self.assertIn("正在使用", res["error"])

    def test_uninstall_success(self) -> None:
        target = self._make_installed("1.14")
        res = self.bridge.uninstall_version("1.14")
        self.assertTrue(res["ok"], res.get("error"))
        self.assertEqual(res["version"], "1.14")
        self.assertFalse(target.parent.exists())

    def test_uninstall_not_installed(self) -> None:
        res = self.bridge.uninstall_version("9.9")
        self.assertFalse(res["ok"])

    # -------- 其余版本 API --------

    def test_get_available_installations(self) -> None:
        with patch.object(
            self.vm,
            "get_installed_versions",
            return_value=[VersionInfo(version="1.15", install_path="p", install_date="d")],
        ), patch.object(self.bridge, "get_current_version", return_value="1.15"):
            res = self.bridge.get_available_installations()
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 1)
        self.assertTrue(res["installations"][0]["current"])

    def test_clear_version_cache(self) -> None:
        with patch.object(self.vm, "clear_cache") as mock_clear:
            res = self.bridge.clear_version_cache()
        self.assertTrue(res["ok"])
        mock_clear.assert_called_once()

    def test_check_version_manifest(self) -> None:
        with patch.object(self.vm, "get_editions", return_value=[EditionInfo(name="default")]):
            ok = self.bridge.check_version_manifest()
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["editions"], 1)

        with patch.object(self.vm, "get_editions", side_effect=RuntimeError("无法访问")):
            bad = self.bridge.check_version_manifest()
        self.assertFalse(bad["ok"])
        self.assertIn("无法访问", bad["error"])

    def test_compare_versions(self) -> None:
        res = self.bridge.compare_versions("1.15", "1.14")
        self.assertTrue(res["ok"])
        self.assertEqual(res["result"], 1)
        self.assertEqual(res["comparison"], "大于")
        self.assertEqual(self.bridge.compare_versions("1.14", "1.15")["result"], -1)
        self.assertEqual(self.bridge.compare_versions("1.15", "1.15")["result"], 0)


if __name__ == "__main__":
    unittest.main()
