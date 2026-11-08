"""VersionManager 单元测试（游戏版本清单 + 本地多版本目录）。"""
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from backend.version_manager import EditionInfo, VersionInfo, VersionManager


MANIFEST = {
    "editions": [
        {
            "name": "default",
            "latest_version": "1.15",
            "description": "正式版",
            "versions": [
                {
                    "version": "1.15",
                    "release_date": "2026-09-01",
                    "download_url": "https://example.com/1.15.zip",
                    "file_name": "rw-1.15.zip",
                    "info": "最新正式版",
                },
                {
                    "version": "1.14",
                    "release_date": "2026-05-10",
                    "download_url": "https://example.com/1.14.zip",
                    "info": "稳定版",
                },
            ],
        },
        {
            "name": "zhc",
            "latest_version": "1.15p11-ZHC",
            "versions": [
                {
                    "version": "1.15p11-ZHC",
                    "download_url": "https://example.com/zhc.zip",
                    "info": "简体中文增强版",
                }
            ],
        },
    ]
}


class TestVersionInfo(unittest.TestCase):
    """VersionInfo 数据类测试。"""

    def test_init_defaults(self) -> None:
        """新增字段都有安全默认值。"""
        vi = VersionInfo(version="1.15")
        self.assertEqual(vi.version, "1.15")
        self.assertEqual(vi.build_date, "")
        self.assertEqual(vi.file_size, 0)
        self.assertFalse(vi.is_installed)
        self.assertEqual(vi.install_path, "")
        self.assertEqual(vi.install_date, "")
        self.assertEqual(vi.edition_name, "")
        self.assertEqual(vi.file_name, "")

    def test_to_dict_covers_all_fields(self) -> None:
        """序列化必须包含前端依赖的全部字段。"""
        vi = VersionInfo(
            version="1.15",
            build_date="2026-09-01",
            file_size=1024,
            url="https://example.com/1.15.zip",
            description="正式版",
            file_name="rw.zip",
            edition_name="default",
        )
        data = vi.to_dict()
        self.assertEqual(data["version"], "1.15")
        self.assertEqual(data["build_date"], "2026-09-01")
        self.assertEqual(data["file_size"], 1024)
        self.assertEqual(data["url"], "https://example.com/1.15.zip")
        self.assertEqual(data["description"], "正式版")
        self.assertEqual(data["file_name"], "rw.zip")
        self.assertEqual(data["edition_name"], "default")
        self.assertFalse(data["is_installed"])

    def test_from_dict_aliases(self) -> None:
        """数据层别名：download_url -> url，info -> description。

        release_date 是清单解析层（_parse_editions）的别名，
        数据类本身只认 build_date。
        """
        vi = VersionInfo.from_dict(
            {
                "version": "1.15",
                "build_date": "2026-09-01",
                "file_size": "2048",
                "url": "https://example.com/x.zip",
                "info": "说明",
            }
        )
        self.assertEqual(vi.version, "1.15")
        self.assertEqual(vi.build_date, "2026-09-01")
        self.assertEqual(vi.url, "https://example.com/x.zip")
        self.assertEqual(vi.description, "说明")
        self.assertEqual(vi.file_size, 2048)

    def test_from_dict_empty(self) -> None:
        """空字典不应抛异常，统一回落到空字符串 / 0。"""
        vi = VersionInfo.from_dict({})
        self.assertEqual(vi.version, "")
        self.assertEqual(vi.build_date, "")
        self.assertEqual(vi.file_size, 0)
        self.assertEqual(vi.url, "")

    def test_equality(self) -> None:
        """dataclass 按字段相等比较。"""
        self.assertEqual(VersionInfo(version="1.15"), VersionInfo(version="1.15"))
        self.assertNotEqual(VersionInfo(version="1.15"), VersionInfo(version="1.14"))


class TestVersionManager(unittest.TestCase):
    """VersionManager 管理器测试。"""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.config_path = self.temp_dir / "config.json"
        self.game_root = self.temp_dir / "game"
        self.game_root.mkdir()
        config = {"game_version_list": {"url": "https://example.com/windows.json", "timeout": 5}}
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        self.vm = VersionManager(self.config_path, self.game_root)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_exe(self, version: str, *parts: str, exe: str = "RustedWarfare.exe") -> Path:
        d = self.vm.version_dir(version).joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        p = d / exe
        p.write_text("fake", encoding="utf-8")
        return p

    def test_paths(self) -> None:
        """versions 根与版本目录定位。"""
        self.assertEqual(self.vm.versions_root, self.game_root / "versions")
        self.assertEqual(self.vm.version_dir("1.15"), self.game_root / "versions" / "1.15")
        self.assertEqual(self.vm.game_root, self.game_root)

    def test_version_dir_sanitizes_name(self) -> None:
        """版本号中的非法路径字符要被替换。"""
        d = self.vm.version_dir("1.15 p11/ZHC:fix")
        self.assertNotIn(":", d.name)
        self.assertNotIn("/", d.name)
        self.assertNotIn("\\", d.name)
        self.assertTrue(d.name)

    def test_is_version_installed_empty(self) -> None:
        """目录不存在 / 空版本号都算未安装。"""
        self.assertFalse(self.vm.is_version_installed("9.9"))
        self.assertFalse(self.vm.is_version_installed(""))

    def test_is_version_installed_exe_at_root(self) -> None:
        """版本目录根部放游戏 exe 即视为已安装。"""
        self._make_exe("1.15")
        self.assertTrue(self.vm.is_version_installed("1.15"))

    def test_is_version_installed_exe_nested(self) -> None:
        """解压常见布局：exe 在版本目录的一层子目录里。"""
        self._make_exe("1.15", "Rusted")
        self.assertTrue(self.vm.is_version_installed("1.15"))

    def test_launcher_exe_name_must_look_like_game(self) -> None:
        """卸载器 / 启动器自身等无关 exe 不应让目录被判定为可启动。"""
        self._make_exe("1.15", exe="unins000.exe")
        self.assertFalse(self.vm.is_version_installed("1.15"))

    def test_java_jar_recognized(self) -> None:
        """Java 版入口 jar 也算可启动目标。"""
        d = self.vm.version_dir("1.15-zhc") / "Rusted Warfare"
        d.mkdir(parents=True, exist_ok=True)
        (d / "game-lib.jar").write_text("jar", encoding="utf-8")
        self.assertTrue(self.vm.is_version_installed("1.15-zhc"))

    def test_get_installed_versions(self) -> None:
        """只收录含游戏主程序的目录，按版本号降序，下划线临时目录跳过。"""
        self._make_exe("1.14")
        self._make_exe("1.15", "Rusted")
        # 空目录：不可启动，不收录
        (self.vm.versions_root / "1.16").mkdir(parents=True, exist_ok=True)
        # 临时下载目录：以下划线开头，跳过
        tmp = self.vm.versions_root / "_tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / "RustedWarfare.exe").write_text("x", encoding="utf-8")

        installed = self.vm.get_installed_versions()
        names = [v.version for v in installed]
        self.assertEqual(names, ["1.15", "1.14"])
        info = next(v for v in installed if v.version == "1.15")
        self.assertTrue(info.is_installed)
        self.assertTrue(info.install_path.endswith("1.15"))
        self.assertTrue(info.install_date)

    def test_uninstall_version(self) -> None:
        """卸载只删除 versions 内对应目录。"""
        target = self._make_exe("1.14")
        ok, err = self.vm.uninstall_version("1.14")
        self.assertTrue(ok, err)
        self.assertIsNone(err)
        self.assertFalse(target.parent.exists())
        self.assertFalse(self.vm.is_version_installed("1.14"))

    def test_uninstall_missing(self) -> None:
        ok, err = self.vm.uninstall_version("9.9")
        self.assertFalse(ok)
        self.assertIn("未安装", err)

    def test_compare_versions(self) -> None:
        cmp = VersionManager.compare_versions
        self.assertEqual(cmp("1.15", "1.15"), 0)
        self.assertEqual(cmp("1.14", "1.15"), -1)
        self.assertEqual(cmp("1.15", "1.14"), 1)
        self.assertEqual(cmp("1.15.2", "1.15.10"), -1)
        self.assertEqual(cmp("2.0", "1.99"), 1)

    def _patch_urlopen(self, payload: bytes):
        m = patch("backend.version_manager.urllib.request.urlopen")
        started = m.start()
        self.addCleanup(m.stop)
        resp = started.return_value.__enter__.return_value
        resp.read.return_value = payload
        return started

    def test_get_editions_editions_structure(self) -> None:
        started = self._patch_urlopen(json.dumps(MANIFEST).encode("utf-8"))
        editions = self.vm.get_editions()
        self.assertEqual([e.name for e in editions], ["default", "zhc"])
        default = editions[0]
        self.assertIsInstance(default, EditionInfo)
        self.assertEqual(default.latest_version, "1.15")
        self.assertEqual([v.version for v in default.versions], ["1.15", "1.14"])
        self.assertEqual(default.versions[0].build_date, "2026-09-01")
        self.assertEqual(default.versions[0].url, "https://example.com/1.15.zip")
        self.assertEqual(default.versions[0].file_name, "rw-1.15.zip")
        self.assertEqual(started.call_count, 1)

    def test_get_remote_versions_aggregated_and_filtered(self) -> None:
        self._patch_urlopen(json.dumps(MANIFEST).encode("utf-8"))
        all_versions = self.vm.get_remote_versions()
        self.assertEqual([v.version for v in all_versions], ["1.15p11-ZHC", "1.15", "1.14"])

        zhc = self.vm.get_remote_versions("zhc")
        self.assertEqual([v.version for v in zhc], ["1.15p11-ZHC"])
        self.assertEqual(self.vm.get_remote_versions("nope"), [])

    def test_parse_bare_versions_structure(self) -> None:
        """没有 editions 包裹时回落为 default 分支。"""
        payload = {
            "latest_version": "1.15",
            "versions": [
                {"version": "1.14", "download_url": "https://example.com/1.14.zip"},
                {"version": "1.15", "download_url": "https://example.com/1.15.zip"},
            ],
        }
        self._patch_urlopen(json.dumps(payload).encode("utf-8"))
        editions = self.vm.get_editions()
        self.assertEqual(len(editions), 1)
        self.assertEqual(editions[0].name, "default")
        self.assertEqual(editions[0].latest_version, "1.15")

    def test_live_manifest_object_structure(self) -> None:
        """CDN 实际格式：分支和版本都以名称为 key。"""
        payload = {"editions": {"default": {"latest_version": "1.15-build176", "versions": {
            "1.15-build176": {"download_url": "https://example.com/new.zip", "info": "简体中文版"},
            "1.15-ZHC-Fix3": {"download_url": "https://example.com/fix.zip"},
        }}}}
        self._patch_urlopen(json.dumps(payload).encode("utf-8"))
        editions = self.vm.get_editions()
        self.assertEqual(editions[0].name, "default")
        self.assertEqual({v.version for v in editions[0].versions},
                         {"1.15-build176", "1.15-ZHC-Fix3"})
        self.assertEqual(self.vm.find_remote_version("1.15-build176").url,
                         "https://example.com/new.zip")

    def test_empty_manifest_is_error(self) -> None:
        self._patch_urlopen(b'{"editions": {"default": {"versions": {}}}}')
        with self.assertRaisesRegex(RuntimeError, "没有可用版本"):
            self.vm.get_editions()

    def test_dns_error_has_actionable_message(self) -> None:
        import socket
        with patch("backend.version_manager.urllib.request.urlopen",
                   side_effect=urllib.error.URLError(socket.gaierror(11001, "host not found"))):
            with self.assertRaisesRegex(RuntimeError, "域名无法解析.*11001"):
                self.vm.get_editions()

    def test_latest_version_fallback_when_unmarked(self) -> None:
        payload = {"versions": [{"version": "1.14"}, {"version": "1.15"}]}
        self._patch_urlopen(json.dumps(payload).encode("utf-8"))
        self.assertEqual(self.vm.get_latest_version("default"), "1.15")

    def test_find_remote_version(self) -> None:
        self._patch_urlopen(json.dumps(MANIFEST).encode("utf-8"))
        hit = self.vm.find_remote_version("1.14")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.url, "https://example.com/1.14.zip")
        self.assertIsNone(self.vm.find_remote_version("9.9"))
        self.assertIsNone(self.vm.find_remote_version(""))

    def test_remote_cache_and_clear(self) -> None:
        started = self._patch_urlopen(json.dumps(MANIFEST).encode("utf-8"))
        self.vm.get_editions()
        self.vm.get_editions()
        self.assertEqual(started.call_count, 1)
        self.vm.clear_cache()
        self.vm.get_editions()
        self.assertEqual(started.call_count, 2)

    def test_missing_manifest_url_raises(self) -> None:
        self.config_path.write_text(json.dumps({"game_version_list": {}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.vm.get_editions()

    def test_missing_config_file_uses_default_manifest(self) -> None:
        from backend.config import DEFAULT_CONFIG
        self.config_path.unlink()
        self.assertEqual(self.vm._list_config(), DEFAULT_CONFIG["game_version_list"])

    def test_fetch_network_error_raises(self) -> None:
        m = patch(
            "backend.version_manager.urllib.request.urlopen",
            side_effect=urllib.error.URLError("boom"),
        )
        with m:
            with self.assertRaises(RuntimeError):
                self.vm.get_editions()

    def test_fetch_bad_json_raises(self) -> None:
        self._patch_urlopen(b"not-json")
        with self.assertRaises(RuntimeError):
            self.vm.get_editions()

    def test_fetch_non_object_raises(self) -> None:
        self._patch_urlopen(json.dumps([1, 2, 3]).encode("utf-8"))
        with self.assertRaises(RuntimeError):
            self.vm.get_editions()


if __name__ == "__main__":
    unittest.main()
