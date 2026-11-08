"""多版本定位与 GameLauncher 按版本启动测试。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.launcher import GameLauncher
from backend.version_manager import VersionManager


class TestVersionLocation(unittest.TestCase):
    """版本目录定位与多版本并存测试。"""

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
        """在 versions/<版本>/Rusted 下放置游戏 exe。"""
        d = self.vm.version_dir(version) / "Rusted"
        d.mkdir(parents=True, exist_ok=True)
        (d / "RustedWarfare.exe").write_text("fake", encoding="utf-8")
        return d

    def test_multiple_versions_coexist(self) -> None:
        """多版本并存：两个版本目录互不影响，切换定位不删除任何文件。"""
        dir_a = self._make_version("1.14")
        dir_b = self._make_version("1.15")
        self.assertTrue(self.vm.is_version_installed("1.14"))
        self.assertTrue(self.vm.is_version_installed("1.15"))

        # “切换”在数据层只是改变调用方拿到的目录，文件原样保留
        self.assertEqual(self.vm.version_dir("1.14").name, "1.14")
        self.assertEqual(self.vm.version_dir("1.15").name, "1.15")
        self.assertTrue((dir_a / "RustedWarfare.exe").exists())
        self.assertTrue((dir_b / "RustedWarfare.exe").exists())

    def test_installed_list_reflects_coexistence(self) -> None:
        self._make_version("1.14")
        self._make_version("1.15")
        self.assertEqual(
            [v.version for v in self.vm.get_installed_versions()],
            ["1.15", "1.14"],
        )


class TestLaunchByVersion(unittest.TestCase):
    """GameLauncher.launch_game_by_version 测试。"""

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
        # launch_game_by_version 是 GameLauncher 的实例方法，目录任意
        self.launcher = GameLauncher(self.game_root, "RustedWarfare.exe")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_version(self, version: str, *, nested: bool = True) -> None:
        base = self.vm.version_dir(version)
        d = base / "Rusted" if nested else base
        d.mkdir(parents=True, exist_ok=True)
        (d / "RustedWarfare.exe").write_text("fake", encoding="utf-8")

    @patch("backend.launcher.subprocess.Popen")
    def test_launch_installed_version_nested(self, mock_popen) -> None:
        """exe 在版本目录的一层子目录内时应智能定位并启动。"""
        self._make_version("1.15")
        ok = self.launcher.launch_game_by_version("1.15", "--windowed", self.vm)
        self.assertTrue(ok)
        mock_popen.assert_called_once()
        kwargs = mock_popen.call_args.kwargs
        self.assertIn(str(self.vm.version_dir("1.15")), kwargs.get("cwd", ""))

    @patch("backend.launcher.subprocess.Popen")
    def test_launch_installed_version_root(self, mock_popen) -> None:
        self._make_version("1.14", nested=False)
        ok = self.launcher.launch_game_by_version("1.14", "", self.vm)
        self.assertTrue(ok)
        mock_popen.assert_called_once()

    def test_launch_without_manager(self) -> None:
        self.assertFalse(self.launcher.launch_game_by_version("1.15", "", None))

    def test_launch_not_installed(self) -> None:
        with patch("backend.launcher.subprocess.Popen") as mock_popen:
            ok = self.launcher.launch_game_by_version("9.9", "", self.vm)
        self.assertFalse(ok)
        mock_popen.assert_not_called()

    @patch("backend.launcher.subprocess.Popen")
    def test_quick_launch_success(self, mock_popen) -> None:
        game = self.temp_dir / "quick"
        (game / "Rusted").mkdir(parents=True)
        (game / "Rusted" / "RustedWarfare.exe").write_text("x", encoding="utf-8")
        ok = self.launcher.quick_launch(game, "--map t")
        self.assertTrue(ok)
        mock_popen.assert_called_once()

    def test_quick_launch_missing_dir(self) -> None:
        with patch("backend.launcher.subprocess.Popen") as mock_popen:
            ok = self.launcher.quick_launch(self.temp_dir / "nope")
        self.assertFalse(ok)
        mock_popen.assert_not_called()

    def test_quick_launch_default_dir_without_game(self) -> None:
        """未指定目录时回落当前目录；在不含游戏的目录中应安全返回 False。"""
        empty = self.temp_dir / "empty_cwd"
        empty.mkdir()
        old_cwd = Path.cwd()
        os.chdir(empty)
        try:
            with patch("backend.launcher.subprocess.Popen") as mock_popen:
                ok = self.launcher.quick_launch(raw_args="")
        finally:
            os.chdir(old_cwd)
        self.assertFalse(ok)
        mock_popen.assert_not_called()

    def test_smart_root_resolution(self) -> None:
        """安装根不含 exe、一层子目录含 exe 时，game_root 指向子目录。"""
        game = self.temp_dir / "smart"
        sub = game / "Rusted"
        sub.mkdir(parents=True)
        exe = sub / "RustedWarfare.exe"
        exe.write_text("x", encoding="utf-8")
        gl = GameLauncher(game, "RustedWarfare.exe")
        self.assertTrue(gl.exists())
        self.assertTrue(gl.launchable())
        self.assertEqual(gl.exe_path, exe)
        self.assertEqual(gl.game_root, sub)


if __name__ == "__main__":
    unittest.main()
