import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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

    @staticmethod
    def _threads_page_data():
        return {
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

    @staticmethod
    def _mock_page_response(page_data):
        webpage = (
            '<html><body><script type="application/json" data-sjs>'
            + json.dumps(page_data)
            + "</script></body></html>"
        )
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = webpage.encode("utf-8")
        return response

    def test_threads_authenticated_navigation_selects_requested_post(self):
        response = self._mock_page_response(self._threads_page_data())

        engine = DownloaderEngine()
        with mock.patch.object(engine, "_threads_cookie_header", return_value="sessionid=abc"), mock.patch(
            "downloader_engine.urllib.request.urlopen", return_value=response
        ) as urlopen:
            info = engine._extract_threads_info(
                "https://www.threads.com/@cuqhytr/post/DdRLvLZE-Rr/media",
                "firefox",
            )

        request = urlopen.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(request.full_url, "https://www.threads.com/@cuqhytr/post/DdRLvLZE-Rr")
        self.assertEqual(headers.get("cookie"), "sessionid=abc")
        self.assertEqual(headers.get("sec-fetch-dest"), "document")
        self.assertEqual(headers.get("sec-fetch-mode"), "navigate")
        self.assertNotIn("Googlebot", headers.get("user-agent", ""))
        self.assertEqual(info["id"], "DdRLvLZE-Rr")
        self.assertEqual(info["uploader"], "@cuqhytr")
        self.assertEqual(info["direct_video_url"], "https://scontent.example/target.mp4?sig=correct")
        self.assertNotIn("recommended.mp4", info["direct_video_url"])
        self.assertEqual(info["available_resolutions"], [1080])
        self.assertEqual(info["raw_info"]["threads_parser"], "authenticated_recursive_media")
        self.assertEqual(info["threads_stream_kind"], "progressive")
        self.assertTrue(info["raw_info"]["threads_authenticated"])

    def test_threads_quote_post_resolves_nested_video(self):
        page_data = {
            "payload": {
                "recommended": {
                    "code": "OtherPost123",
                    "video_versions": [{"url": "https://scontent.example/wrong.mp4"}],
                },
                "requested": {
                    "code": "QuoteFacade1",
                    "user": {"username": "outer_user"},
                    "caption": {"text": "Quoted video"},
                    "media_type": 1,
                    "text_post_app_info": {
                        "share_info": {
                            "quoted_post": {
                                "code": "QuotedSource1",
                                "media_type": 2,
                                "video_versions": [
                                    {"url": "https://scontent.example/quoted.mp4?sig=ok", "height": 1080}
                                ],
                            }
                        }
                    },
                },
            }
        }
        response = self._mock_page_response(page_data)
        engine = DownloaderEngine()
        with mock.patch.object(engine, "_threads_cookie_header", return_value="sessionid=abc"), mock.patch(
            "downloader_engine.urllib.request.urlopen", return_value=response
        ):
            info = engine._extract_threads_info(
                "https://www.threads.com/@outer_user/post/QuoteFacade1",
                "firefox",
            )

        self.assertEqual(info["id"], "QuoteFacade1")
        self.assertEqual(info["direct_video_url"], "https://scontent.example/quoted.mp4?sig=ok")
        self.assertNotIn("wrong.mp4", info["direct_video_url"])

    def test_threads_repost_and_nested_wrapper_resolve_video(self):
        post = {
            "code": "RepostFacade1",
            "text_post_app_info": {
                "share_info": {
                    "reposted_post": {
                        "code": "RepostedSource1",
                        "wrapper": {
                            "children": [
                                {
                                    "media": {
                                        "video_versions": [
                                            {"url": "https://scontent.example/repost.mp4", "height": 720}
                                        ]
                                    }
                                }
                            ]
                        },
                    }
                }
            },
        }
        urls = DownloaderEngine._threads_post_video_urls(post)
        self.assertEqual(urls, ["https://scontent.example/repost.mp4"])

    def test_threads_dash_only_manifest_selects_best_video_and_audio(self):
        manifest = """
        <MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
          <Period>
            <AdaptationSet mimeType="video/mp4" contentType="video">
              <Representation id="v720" width="1280" height="720" bandwidth="1500000" codecs="avc1.64001f">
                <BaseURL>https://scontent.example/video720.mp4?x=1&amp;y=2</BaseURL>
              </Representation>
              <Representation id="v1080" width="1920" height="1080" bandwidth="3000000" codecs="avc1.640028">
                <BaseURL>https://scontent.example/video1080.mp4?x=1&amp;y=2</BaseURL>
              </Representation>
            </AdaptationSet>
            <AdaptationSet mimeType="audio/mp4" contentType="audio">
              <Representation id="a1" bandwidth="128000" codecs="mp4a.40.2">
                <BaseURL>https://scontent.example/audio.mp4?x=1&amp;y=2</BaseURL>
              </Representation>
            </AdaptationSet>
          </Period>
        </MPD>
        """
        page_data = {
            "payload": {
                "requested": {
                    "code": "DashOnly1",
                    "user": {"username": "dash_user"},
                    "caption": {"text": "DASH only"},
                    "media_type": 2,
                    "video_dash_manifest": manifest,
                }
            }
        }
        response = self._mock_page_response(page_data)
        engine = DownloaderEngine()
        with mock.patch.object(engine, "_threads_cookie_header", return_value="sessionid=abc"), mock.patch(
            "downloader_engine.urllib.request.urlopen", return_value=response
        ):
            info = engine._extract_threads_info(
                "https://www.threads.com/@dash_user/post/DashOnly1",
                "firefox",
            )

        self.assertEqual(info["threads_stream_kind"], "dash")
        self.assertEqual(info["direct_video_url"], "https://scontent.example/video1080.mp4?x=1&y=2")
        self.assertEqual(info["direct_audio_url"], "https://scontent.example/audio.mp4?x=1&y=2")
        self.assertIn(1080, info["available_resolutions"])
        self.assertTrue(info["raw_info"]["threads_dash_audio"])

    def test_threads_escaped_payload_is_parsed(self):
        escaped_payload = json.dumps(json.dumps(self._threads_page_data()))
        webpage = f"<html><script>window.__payload = {escaped_payload};</script></html>"
        engine = DownloaderEngine()

        target = engine._find_threads_post_in_embedded_payload(webpage, "DdRLvLZE-Rr")

        self.assertIsNotNone(target)
        self.assertEqual(target["code"], "DdRLvLZE-Rr")
        self.assertEqual(
            engine._threads_post_video_urls(target)[0],
            "https://scontent.example/target.mp4?sig=correct",
        )

    def test_threads_cookie_loader_filters_non_threads_domains(self):
        fake_jar = [
            SimpleNamespace(domain=".threads.com", name="sessionid", value="threads-session"),
            SimpleNamespace(domain=".threads.net", name="csrftoken", value="csrf-token"),
            SimpleNamespace(domain=".youtube.com", name="SID", value="must-not-leak"),
        ]
        fake_ydl = mock.MagicMock()
        fake_ydl.__enter__.return_value = fake_ydl
        fake_ydl.__exit__.return_value = False
        fake_ydl.cookiejar = fake_jar

        engine = DownloaderEngine()
        with mock.patch("downloader_engine.yt_dlp.YoutubeDL", return_value=fake_ydl) as ydl_cls:
            header = engine._threads_cookie_header("firefox")

        opts = ydl_cls.call_args.args[0]
        self.assertEqual(opts["cookiesfrombrowser"], ("firefox",))
        self.assertIn("sessionid=threads-session", header)
        self.assertIn("csrftoken=csrf-token", header)
        self.assertNotIn("must-not-leak", header)

    def test_threads_public_extract_info_forwards_cookie_source(self):
        engine = DownloaderEngine()
        expected = {"id": "DdRLvLZE-Rr"}
        url = "https://www.threads.com/@cuqhytr/post/DdRLvLZE-Rr/media"

        with mock.patch.object(engine, "_extract_threads_info", return_value=expected) as extractor:
            result = engine.extract_info(url, cookies_browser="edge")

        self.assertEqual(result, expected)
        extractor.assert_called_once_with(url, "edge")

    def test_threads_missing_target_does_not_fall_back_to_other_video(self):
        page_data = {
            "recommended": {
                "code": "OtherPost123",
                "video_versions": [{"url": "https://scontent.example/recommended.mp4"}],
            }
        }
        response = self._mock_page_response(page_data)

        engine = DownloaderEngine()
        with mock.patch.object(engine, "_threads_cookie_header", return_value="sessionid=abc"), mock.patch(
            "downloader_engine.urllib.request.urlopen", return_value=response
        ):
            with self.assertRaisesRegex(ValueError, "為避免誤抓推薦影片"):
                engine._extract_threads_info(
                    "https://www.threads.com/@cuqhytr/post/DdRLvLZE-Rr/media",
                    "firefox",
                )

    def test_threads_without_login_explains_auth_requirement(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = b"<html><body>empty shell</body></html>"

        engine = DownloaderEngine()
        with mock.patch.object(engine, "_threads_cookie_header", return_value=""), mock.patch(
            "downloader_engine.urllib.request.urlopen", return_value=response
        ):
            with self.assertRaisesRegex(ValueError, "登入憑證"):
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
