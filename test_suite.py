import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config_manager import ConfigManager, get_default_config_path
from downloader_engine import DownloaderEngine, get_ffmpeg_path
from version import __version__


class TestVideoDownloader(unittest.TestCase):
    def test_platform_detection(self):
        cases = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "YouTube", True),
            ("https://youtu.be/dQw4w9WgXcQ", "YouTube", True),
            ("https://www.facebook.com/watch/?v=123456", "Facebook", False),
            ("https://fb.watch/xyz/", "Facebook", False),
            ("https://www.instagram.com/reel/C3_abc/", "Instagram", False),
            ("https://twitter.com/OpenAI/status/123", "X (Twitter)", False),
            ("https://x.com/elonmusk/status/456", "X (Twitter)", False),
            ("https://www.tiktok.com/@user/video/789", "TikTok", False),
            ("https://www.bilibili.com/video/BV1xx411c7mD", "Bilibili", True),
            ("https://www.threads.net/@zuck/post/abc", "Threads", False),
            ("https://vimeo.com/12345678", "通用平台", False),
        ]
        for url, expected_name, expected_subs in cases:
            res = DownloaderEngine.detect_platform(url)
            self.assertEqual(res["name"], expected_name, f"Failed for {url}")
            self.assertEqual(res["has_subtitles"], expected_subs, f"Subtitles flag mismatch for {url}")

    def test_threads_media_url_normalization(self):
        url = "https://www.threads.com/@cuqhytr/post/DdRLvLZE-Rr/media?x=1#fragment"
        self.assertEqual(
            DownloaderEngine._normalize_threads_url(url),
            "https://www.threads.com/@cuqhytr/post/DdRLvLZE-Rr",
        )

    def test_threads_crawler_selects_requested_post_not_recommendation(self):
        page_data = {
            "payload": {
                "recommended": {
                    "code": "OtherPost123",
                    "video_versions": [
                        {"url": "https://scontent.example/recommended.mp4?sig=wrong", "height": 720}
                    ],
                },
                "requested": {
                    "code": "DdRLvLZE-Rr",
                    "canonical_url": "https://www.threads.com/@cuqhytr/post/DdRLvLZE-Rr",
                    "user": {"username": "cuqhytr"},
                    "caption": {"text": "Regression target video"},
                    "original_height": 1080,
                    "video_versions": [
                        {"url": "https://scontent.example/target.mp4?sig=correct", "height": 1080},
                        {"url": "https://scontent.example/target.mp4?sig=alternate", "height": 1080},
                    ],
                    "image_versions2": {
                        "candidates": [
                            {"url": "https://scontent.example/thumb.jpg", "width": 1080, "height": 1920}
                        ]
                    },
                },
            }
        }
        webpage = (
            '<html><body><script type="application/json" data-sjs>'
            + json.dumps(page_data)
            + "</script></body></html>"
        )

        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = webpage.encode("utf-8")

        engine = DownloaderEngine()
        with mock.patch("downloader_engine.urllib.request.urlopen", return_value=response) as urlopen:
            info = engine._extract_threads_info(
                "https://www.threads.com/@cuqhytr/post/DdRLvLZE-Rr/media"
            )

        request = urlopen.call_args.args[0]
        self.assertIn("Googlebot", request.get_header("User-agent"))
        self.assertEqual(request.full_url, "https://www.threads.com/@cuqhytr/post/DdRLvLZE-Rr")
        self.assertEqual(info["id"], "DdRLvLZE-Rr")
        self.assertEqual(info["uploader"], "@cuqhytr")
        self.assertEqual(info["direct_video_url"], "https://scontent.example/target.mp4?sig=correct")
        self.assertNotIn("recommended.mp4", info["direct_video_url"])
        self.assertEqual(info["available_resolutions"], [1080])
        self.assertEqual(info["raw_info"]["threads_parser"], "crawler_ssr_json")

    def test_threads_missing_target_does_not_fall_back_to_other_video(self):
        page_data = {
            "recommended": {
                "code": "OtherPost123",
                "video_versions": [{"url": "https://scontent.example/recommended.mp4"}],
            }
        }
        webpage = '<script type="application/json">' + json.dumps(page_data) + "</script>"
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = webpage.encode("utf-8")

        engine = DownloaderEngine()
        with mock.patch("downloader_engine.urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "為避免抓到推薦影片"):
                engine._extract_threads_info(
                    "https://www.threads.com/@cuqhytr/post/DdRLvLZE-Rr/media"
                )

    def test_config_manager_explicit_test_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("pathlib.Path.cwd", return_value=Path(tmp)):
                cfg = ConfigManager("test_config.json")
                cfg.set("quality", "1080p")
                self.assertEqual(cfg.get("quality"), "1080p")
                self.assertTrue((Path(tmp) / "test_config.json").is_file())

    @unittest.skipUnless(os.name == "nt", "Windows-specific config path")
    def test_default_config_path_on_windows(self):
        fake_local = Path("C:/Users/Test/AppData/Local")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(fake_local)}, clear=False):
            self.assertEqual(
                get_default_config_path(),
                fake_local / "SocialVideoDownloader" / "config.json",
            )

    def test_legacy_config_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "config.json"
            legacy.write_text(json.dumps({"quality": "720p"}), encoding="utf-8")
            new_path = root / "appdata" / "SocialVideoDownloader" / "config.json"

            with mock.patch("pathlib.Path.cwd", return_value=root), mock.patch(
                "config_manager.get_default_config_path", return_value=new_path
            ):
                cfg = ConfigManager()
                self.assertEqual(cfg.get("quality"), "720p")
                self.assertTrue(new_path.is_file())
                self.assertTrue(legacy.is_file())

    def test_duration_format(self):
        self.assertEqual(DownloaderEngine.format_duration(65), "01:05")
        self.assertEqual(DownloaderEngine.format_duration(3665), "01:01:05")
        self.assertEqual(DownloaderEngine.format_duration(24.635), "00:25")
        self.assertEqual(DownloaderEngine.format_duration(30.033), "00:30")
        self.assertEqual(DownloaderEngine.format_duration(None), "未知長度")
        self.assertEqual(DownloaderEngine.format_duration(0), "未知長度")

    def test_cookie_opts(self):
        opts = {}
        DownloaderEngine.apply_cookie_opts(opts, "firefox")
        self.assertEqual(opts.get("cookiesfrombrowser"), ("firefox",))

    def test_ffmpeg_detection(self):
        ffmpeg_dir = get_ffmpeg_path()
        self.assertIsNotNone(ffmpeg_dir, "FFmpeg should be detected on the system")

    def test_caption_expansion(self):
        expanded = DownloaderEngine.expand_caption_languages(["zh-TW", "en"])
        self.assertIn("zh-orig", expanded)
        self.assertIn("en-orig", expanded)

    def test_version_is_semver(self):
        parts = __version__.split(".")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(part.isdigit() for part in parts))


if __name__ == "__main__":
    unittest.main()
