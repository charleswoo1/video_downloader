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
    @staticmethod
    def _threads_dash_manifest():
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">'
            '<Period>'
            '<AdaptationSet contentType="video">'
            '<Representation bandwidth="600000" mimeType="video/mp4" width="720" height="1280">'
            '<BaseURL>https://scontent.example/video-720.mp4?sig=one&amp;x=1</BaseURL>'
            '</Representation>'
            '<Representation bandwidth="900000" mimeType="video/mp4" width="1080" height="1920">'
            '<BaseURL>https://scontent.example/video-1080.mp4?sig=two</BaseURL>'
            '</Representation>'
            '</AdaptationSet>'
            '<AdaptationSet contentType="audio">'
            '<Representation bandwidth="64000" mimeType="audio/mp4">'
            '<BaseURL>https://scontent.example/audio-low.mp4?sig=low</BaseURL>'
            '</Representation>'
            '<Representation bandwidth="128000" mimeType="audio/mp4">'
            '<BaseURL>https://scontent.example/audio-high.mp4?sig=high</BaseURL>'
            '</Representation>'
            '</AdaptationSet>'
            '</Period>'
            '</MPD>'
        )

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

    def test_threads_authenticated_navigation_selects_requested_post(self):
        webpage = (
            '<html><body><script type="application/json" data-sjs>'
            + json.dumps(self._threads_page_data())
            + "</script></body></html>"
        )
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = webpage.encode("utf-8")

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
        self.assertEqual(info["raw_info"]["threads_parser"], "authenticated_browser_html_recursive")
        self.assertEqual(info["threads_media_kind"], "progressive")
        self.assertTrue(info["raw_info"]["threads_authenticated"])

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

    def test_threads_direct_video_versions_resolver(self):
        post = {
            "code": "Direct1",
            "video_versions": [
                {"url": "https://scontent.example/480.mp4", "height": 480},
                {"url": "https://scontent.example/1080.mp4", "height": 1080},
            ],
        }
        resolved = DownloaderEngine.resolve_threads_media(post)
        self.assertEqual(resolved["candidates"][0]["kind"], "progressive")
        self.assertEqual(resolved["candidates"][0]["video_url"], "https://scontent.example/1080.mp4")
        self.assertEqual(resolved["candidates"][0]["height"], 1080)

    def test_threads_dash_only_manifest_resolver(self):
        post = {
            "code": "DashOnly1",
            "video_dash_manifest": self._threads_dash_manifest(),
        }
        resolved = DownloaderEngine.resolve_threads_media(
            post,
            base_url="https://www.threads.com/@test/post/DashOnly1",
        )
        candidate = resolved["candidates"][0]
        self.assertEqual(candidate["kind"], "dash")
        self.assertEqual(candidate["video_url"], "https://scontent.example/video-1080.mp4?sig=two")
        self.assertEqual(candidate["audio_url"], "https://scontent.example/audio-high.mp4?sig=high")
        self.assertEqual(candidate["height"], 1920)

    def test_threads_progressive_is_preferred_over_dash(self):
        post = {
            "code": "Both1",
            "video_dash_manifest": self._threads_dash_manifest(),
            "children": [
                {
                    "video_versions": [
                        {"url": "https://scontent.example/progressive.mp4", "height": 720}
                    ]
                }
            ],
        }
        resolved = DownloaderEngine.resolve_threads_media(post)
        selected = next((item for item in resolved["candidates"] if item["kind"] == "progressive"), None)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["video_url"], "https://scontent.example/progressive.mp4")

    def test_threads_quote_post_recursive_resolver(self):
        post = {
            "code": "Quote1",
            "text_post_app_info": {
                "share_info": {
                    "quoted_post": {
                        "video_versions": [
                            {"url": "https://scontent.example/quoted.mp4", "height": 720}
                        ]
                    }
                }
            },
        }
        resolved = DownloaderEngine.resolve_threads_media(post)
        self.assertEqual(resolved["candidates"][0]["video_url"], "https://scontent.example/quoted.mp4")
        self.assertIn("quoted_post", resolved["candidates"][0]["source_path"])
        self.assertTrue(resolved["flags"]["quoted_post"])

    def test_threads_repost_recursive_resolver(self):
        post = {
            "code": "Repost1",
            "text_post_app_info": {
                "share_info": {
                    "reposted_post": {
                        "video_versions": [
                            {"url": "https://scontent.example/reposted.mp4", "height": 720}
                        ]
                    }
                }
            },
        }
        resolved = DownloaderEngine.resolve_threads_media(post)
        self.assertEqual(resolved["candidates"][0]["video_url"], "https://scontent.example/reposted.mp4")
        self.assertTrue(resolved["flags"]["reposted_post"])

    def test_threads_carousel_mixed_image_video(self):
        post = {
            "code": "Carousel1",
            "carousel_media": [
                {"media_type": 1, "image_versions2": {"candidates": [{"url": "https://img.example/a.jpg"}]}},
                {
                    "media_type": 2,
                    "video_versions": [
                        {"url": "https://scontent.example/carousel-video.mp4", "height": 1080}
                    ],
                },
            ],
        }
        resolved = DownloaderEngine.resolve_threads_media(post)
        self.assertEqual(len(resolved["candidates"]), 1)
        self.assertEqual(resolved["candidates"][0]["video_url"], "https://scontent.example/carousel-video.mp4")

    def test_threads_nested_child_media_resolver(self):
        post = {
            "code": "Nested1",
            "children": [
                {
                    "media_wrapper": {
                        "child_media": {
                            "video_versions": [
                                {"url": "https://scontent.example/nested.mp4", "height": 540}
                            ]
                        }
                    }
                }
            ],
        }
        resolved = DownloaderEngine.resolve_threads_media(post)
        self.assertEqual(resolved["candidates"][0]["video_url"], "https://scontent.example/nested.mp4")
        self.assertIn("child_media", resolved["candidates"][0]["source_path"])

    def test_threads_recommendation_isolation_inside_target_subtree(self):
        post = {
            "code": "TargetNoVideo",
            "recommended_media": {
                "video_versions": [
                    {"url": "https://scontent.example/must-not-download.mp4", "height": 1080}
                ]
            },
        }
        resolved = DownloaderEngine.resolve_threads_media(post)
        self.assertEqual(resolved["candidates"], [])

    def test_threads_duplicate_candidate_dedupe(self):
        post = {
            "code": "Dedupe1",
            "video_versions": [
                {"url": "https://scontent.example/same.mp4?sig=one", "height": 1080},
                {"url": "https://scontent.example/same.mp4?sig=two", "height": 1080},
            ],
            "children": [
                {
                    "video_versions": [
                        {"url": "https://scontent.example/same.mp4?sig=three", "height": 1080}
                    ]
                }
            ],
        }
        resolved = DownloaderEngine.resolve_threads_media(post)
        self.assertEqual(len(resolved["candidates"]), 1)

    def test_threads_recursive_loop_and_depth_protection(self):
        post = {"code": "Loop1"}
        post["children"] = [post]
        resolved = DownloaderEngine.resolve_threads_media(post)
        self.assertGreaterEqual(resolved["loop_skips"], 1)

        deep = {"code": "Deep1"}
        cursor = deep
        for _ in range(30):
            child = {}
            cursor["children"] = [child]
            cursor = child
        deep_resolved = DownloaderEngine.resolve_threads_media(deep, max_depth=8)
        self.assertTrue(deep_resolved["truncated"])

    def test_threads_diagnostic_output_is_safe_and_structured(self):
        page_data = {
            "requested": {
                "code": "Diag1",
                "media_type": 8,
                "carousel_media": [{"media_type": 1}],
                "text_post_app_info": {"share_info": {"quoted_post": {"media_type": 1}}},
            }
        }
        webpage = '<script type="application/json">' + json.dumps(page_data) + "</script>"
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = webpage.encode("utf-8")

        engine = DownloaderEngine()
        with mock.patch.object(engine, "_threads_cookie_header", return_value="sessionid=secret-value"), mock.patch(
            "downloader_engine.urllib.request.urlopen", return_value=response
        ):
            with self.assertRaisesRegex(ValueError, "post_id=Diag1") as raised:
                engine._extract_threads_info("https://www.threads.com/@test/post/Diag1", "firefox")

        self.assertNotIn("secret-value", str(raised.exception))
        diagnostics = engine._last_threads_diagnostics
        self.assertEqual(diagnostics["post_id"], "Diag1")
        self.assertEqual(diagnostics["media_type"], 8)
        self.assertEqual(diagnostics["carousel_count"], 1)
        self.assertTrue(diagnostics["quoted_post_present"])
        self.assertEqual(diagnostics["candidate_count"], 0)
        self.assertGreater(len(diagnostics["resolver_paths_examined"]), 0)

    def test_threads_dash_merge_uses_ffmpeg_copy(self):
        engine = DownloaderEngine()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "video.mp4"
            audio = root / "audio.m4a"
            output = root / "merged.mp4"
            video.write_bytes(b"video")
            audio.write_bytes(b"audio")
            with mock.patch("downloader_engine.subprocess.run") as run:
                engine._merge_threads_dash(video, audio, output)
        cmd = run.call_args.args[0]
        self.assertIn("-c", cmd)
        self.assertIn("copy", cmd)
        self.assertIn(str(video), cmd)
        self.assertIn(str(audio), cmd)
        self.assertEqual(cmd[-1], str(output))

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
        webpage = '<script type="application/json">' + json.dumps(page_data) + "</script>"
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = webpage.encode("utf-8")

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
