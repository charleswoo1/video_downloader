import html as html_lib
import json
import re
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

import yt_dlp

from downloader_engine_base import DownloaderEngine as _BaseDownloaderEngine
from downloader_engine_base import get_ffmpeg_path, get_node_path


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
_THREADS_MEDIA_KEYS = {
    "video_versions",
    "video_dash_manifest",
    "image_versions2",
    "carousel_media",
    "text_post_app_info",
    "share_info",
    "quoted_post",
    "reposted_post",
    "children",
}
_THREADS_DOMAINS = ("threads.com", "threads.net")
_THREADS_RECURSIVE_KEYS = {
    "carousel_media",
    "text_post_app_info",
    "share_info",
    "quoted_post",
    "reposted_post",
    "children",
    "child_media",
    "media",
    "media_items",
    "media_wrapper",
    "attachments",
    "attachment",
    "sidecar",
    "wrapper",
    "container",
}
_THREADS_RECURSION_BLOCKED_TOKENS = ("recommended", "recommendation", "related", "suggested", "suggestion")
_THREADS_MAX_DEPTH = 24
_THREADS_MAX_NODES = 800


class DownloaderEngine(_BaseDownloaderEngine):
    """下載引擎；Threads 使用已登入瀏覽器 session 解析，其餘平台沿用既有核心。"""

    def __init__(self):
        super().__init__()
        self._last_threads_diagnostics: Optional[Dict[str, Any]] = None

    @staticmethod
    def _normalize_threads_url(url: str) -> str:
        """正規化 Threads URL，移除 /media、query/fragment 並統一到 threads.com。"""
        clean_url = url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
        if clean_url.endswith("/media"):
            clean_url = clean_url[:-6].rstrip("/")
        clean_url = clean_url.replace("://www.threads.net/", "://www.threads.com/")
        clean_url = clean_url.replace("://threads.net/", "://www.threads.com/")
        clean_url = clean_url.replace("://threads.com/", "://www.threads.com/")
        return clean_url

    @staticmethod
    def _decode_threads_url(value: str) -> str:
        return (
            html_lib.unescape(value)
            .replace(r"\u0026", "&")
            .replace(r"\u003d", "=")
            .replace(r"\/", "/")
        )

    @classmethod
    def _collect_threads_posts(cls, obj: Any, out: List[Dict[str, Any]]) -> None:
        """遞迴收集帶 shortcode 與媒體/分享 wrapper 的 Threads post dict。"""
        if isinstance(obj, dict):
            if obj.get("code") and (set(obj.keys()) & _THREADS_MEDIA_KEYS):
                out.append(obj)
            for value in obj.values():
                cls._collect_threads_posts(value, out)
        elif isinstance(obj, list):
            for value in obj:
                cls._collect_threads_posts(value, out)

    @classmethod
    def _extract_threads_posts_from_html(cls, webpage: str) -> List[Dict[str, Any]]:
        """先解析標準 application/json 區塊。"""
        posts: List[Dict[str, Any]] = []
        blocks = re.findall(
            r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
            webpage,
            re.IGNORECASE | re.DOTALL,
        )
        for block in blocks:
            try:
                data = json.loads(html_lib.unescape(block))
            except (json.JSONDecodeError, TypeError):
                continue
            cls._collect_threads_posts(data, posts)
        return posts

    @classmethod
    def _find_threads_post_in_embedded_payload(
        cls,
        webpage: str,
        post_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Threads 登入頁常把貼文 JSON 當成 escaped 字串內嵌在 HTML。
        從目標 shortcode 附近嘗試 raw JSON decode，避免全頁掃到推薦影片。
        """
        base = (
            html_lib.unescape(webpage)
            .replace(r"\u0026", "&")
            .replace(r"\/", "/")
        )
        variants = [base]
        quote_unescaped = base.replace(r'\"', '"')
        if quote_unescaped != base:
            variants.append(quote_unescaped)

        decoder = json.JSONDecoder()
        marker = re.compile(rf'"code"\s*:\s*"{re.escape(post_id)}"')

        for text in variants:
            for match in marker.finditer(text):
                window_start = max(0, match.start() - 150_000)
                starts = [
                    window_start + item.start()
                    for item in re.finditer(r"\{", text[window_start : match.start() + 1])
                ]
                for start in reversed(starts[-400:]):
                    try:
                        obj, _ = decoder.raw_decode(text[start:])
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(obj, dict):
                        continue

                    candidates: List[Dict[str, Any]] = []
                    cls._collect_threads_posts(obj, candidates)
                    for candidate in candidates:
                        if candidate.get("code") == post_id:
                            return candidate

                    if obj.get("code") == post_id and (set(obj.keys()) & _THREADS_MEDIA_KEYS):
                        return obj
        return None

    @staticmethod
    def _threads_url_key(url: Optional[str]) -> str:
        if not isinstance(url, str):
            return ""
        return url.split("?", 1)[0]

    @classmethod
    def _should_follow_threads_media_key(cls, key: Any) -> bool:
        if not isinstance(key, str):
            return False
        lowered = key.lower()
        if lowered in {"video_versions", "video_dash_manifest", "image_versions2"}:
            return False
        if any(token in lowered for token in _THREADS_RECURSION_BLOCKED_TOKENS):
            return False
        if lowered in _THREADS_RECURSIVE_KEYS:
            return True
        return any(token in lowered for token in ("media", "child", "wrapper", "container", "attachment"))

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @classmethod
    def _threads_video_urls(cls, media: Dict[str, Any]) -> List[str]:
        """從單一 media dict 取得去重後的 progressive MP4 URL。"""
        urls: List[str] = []
        seen = set()
        for version in media.get("video_versions") or []:
            if not isinstance(version, dict):
                continue
            candidate = version.get("url")
            if not isinstance(candidate, str):
                continue
            candidate = cls._decode_threads_url(candidate)
            if not candidate.startswith(("https://", "http://")):
                continue
            key = cls._threads_url_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            urls.append(candidate)
        return urls

    @classmethod
    def _parse_threads_dash_manifest(
        cls,
        manifest: str,
        base_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """解析 Meta inline MPD，回傳最佳 video/audio Representation 的 BaseURL。"""
        if not isinstance(manifest, str) or not manifest.strip():
            return None

        xml_text = manifest.strip()
        xml_text = (
            xml_text.replace(r"\u003c", "<")
            .replace(r"\u003e", ">")
            .replace(r"\u0026", "&")
            .replace(r"\/", "/")
        )
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None

        def local_name(element: ET.Element) -> str:
            return element.tag.rsplit("}", 1)[-1]

        def direct_base(element: ET.Element, inherited: str) -> str:
            for child in list(element):
                if local_name(child) == "BaseURL" and isinstance(child.text, str) and child.text.strip():
                    return urljoin(inherited, cls._decode_threads_url(child.text.strip()))
            return inherited

        inherited_root = base_url or ""
        root_base = direct_base(root, inherited_root)
        videos: List[Dict[str, Any]] = []
        audios: List[Dict[str, Any]] = []

        for period in (child for child in list(root) if local_name(child) == "Period"):
            period_base = direct_base(period, root_base)
            for adaptation in (child for child in list(period) if local_name(child) == "AdaptationSet"):
                adaptation_base = direct_base(adaptation, period_base)
                adaptation_type = str(adaptation.attrib.get("contentType") or "").lower()
                adaptation_mime = str(adaptation.attrib.get("mimeType") or "").lower()

                for representation in (
                    child for child in list(adaptation) if local_name(child) == "Representation"
                ):
                    rep_base = direct_base(representation, adaptation_base)
                    if not rep_base.startswith(("https://", "http://")):
                        continue

                    mime_type = str(representation.attrib.get("mimeType") or adaptation_mime).lower()
                    content_type = adaptation_type
                    if not content_type:
                        if mime_type.startswith("video/"):
                            content_type = "video"
                        elif mime_type.startswith("audio/"):
                            content_type = "audio"

                    item = {
                        "url": cls._decode_threads_url(rep_base),
                        "height": cls._safe_int(representation.attrib.get("height")),
                        "width": cls._safe_int(representation.attrib.get("width")),
                        "bandwidth": cls._safe_int(representation.attrib.get("bandwidth")) or 0,
                    }
                    if content_type == "video" or mime_type.startswith("video/"):
                        videos.append(item)
                    elif content_type == "audio" or mime_type.startswith("audio/"):
                        audios.append(item)

        if not videos:
            return None

        best_video = max(
            videos,
            key=lambda item: (
                item.get("height") or 0,
                item.get("width") or 0,
                item.get("bandwidth") or 0,
            ),
        )
        best_audio = max(audios, key=lambda item: item.get("bandwidth") or 0) if audios else None
        return {
            "video_url": best_video["url"],
            "audio_url": best_audio["url"] if best_audio else None,
            "height": best_video.get("height"),
        }

    @classmethod
    def resolve_threads_media(
        cls,
        post: Dict[str, Any],
        base_url: Optional[str] = None,
        max_depth: int = _THREADS_MAX_DEPTH,
        max_nodes: int = _THREADS_MAX_NODES,
    ) -> Dict[str, Any]:
        """
        僅從已鎖定 shortcode 的 target-post subtree 遞迴解析媒體。
        不會回到頁面根節點，也會跳過 recommendation/related/suggested wrapper。
        """
        candidates: List[Dict[str, Any]] = []
        seen_candidates = set()
        seen_containers = set()
        paths_examined: List[str] = []
        heights = set()
        first_thumbnail: Optional[str] = None
        flags = {"quoted_post": False, "reposted_post": False}
        stats = {
            "node_count": 0,
            "loop_skips": 0,
            "max_depth_reached": 0,
            "truncated": False,
            "dash_parse_errors": 0,
        }

        def add_candidate(candidate: Dict[str, Any]) -> None:
            video_key = cls._threads_url_key(candidate.get("video_url"))
            audio_key = cls._threads_url_key(candidate.get("audio_url"))
            if not video_key:
                return
            dedupe_key = (candidate.get("kind"), video_key, audio_key)
            if dedupe_key in seen_candidates:
                return
            seen_candidates.add(dedupe_key)
            candidates.append(candidate)
            height = candidate.get("height")
            if isinstance(height, int) and height > 0:
                heights.add(height)

        def walk(value: Any, path: str, depth: int) -> None:
            nonlocal first_thumbnail
            stats["max_depth_reached"] = max(stats["max_depth_reached"], depth)
            if depth > max_depth or stats["node_count"] >= max_nodes:
                stats["truncated"] = True
                return
            if not isinstance(value, (dict, list)):
                return

            identity = id(value)
            if identity in seen_containers:
                stats["loop_skips"] += 1
                return
            seen_containers.add(identity)
            stats["node_count"] += 1

            if isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, f"{path}[{index}]", depth + 1)
                return

            if len(paths_examined) < 80:
                paths_examined.append(path)

            original_height = cls._safe_int(value.get("original_height"))
            if original_height:
                heights.add(original_height)

            if first_thumbnail is None:
                image_versions = value.get("image_versions2")
                if isinstance(image_versions, dict):
                    image_candidates = image_versions.get("candidates")
                    if isinstance(image_candidates, list):
                        for image in image_candidates:
                            if not isinstance(image, dict):
                                continue
                            image_url = image.get("url")
                            if isinstance(image_url, str):
                                image_url = cls._decode_threads_url(image_url)
                                if image_url.startswith(("https://", "http://")):
                                    first_thumbnail = image_url
                                    break

            versions = value.get("video_versions")
            if isinstance(versions, list):
                progressive: List[Dict[str, Any]] = []
                for index, version in enumerate(versions):
                    if not isinstance(version, dict):
                        continue
                    video_url = version.get("url")
                    if not isinstance(video_url, str):
                        continue
                    video_url = cls._decode_threads_url(video_url)
                    if not video_url.startswith(("https://", "http://")):
                        continue
                    height = cls._safe_int(version.get("height")) or original_height
                    if height:
                        heights.add(height)
                    progressive.append(
                        {
                            "kind": "progressive",
                            "video_url": video_url,
                            "audio_url": None,
                            "manifest": None,
                            "source_path": f"{path}.video_versions[{index}]",
                            "height": height,
                        }
                    )
                progressive.sort(key=lambda item: item.get("height") or 0, reverse=True)
                for item in progressive:
                    add_candidate(item)

            manifest = value.get("video_dash_manifest")
            if isinstance(manifest, str) and manifest.strip():
                dash = cls._parse_threads_dash_manifest(manifest, base_url=base_url)
                if dash:
                    add_candidate(
                        {
                            "kind": "dash",
                            "video_url": dash["video_url"],
                            "audio_url": dash.get("audio_url"),
                            "manifest": manifest,
                            "source_path": f"{path}.video_dash_manifest",
                            "height": dash.get("height") or original_height,
                        }
                    )
                else:
                    stats["dash_parse_errors"] += 1

            for key, child in value.items():
                lowered = str(key).lower()
                if lowered == "quoted_post":
                    flags["quoted_post"] = True
                elif lowered == "reposted_post":
                    flags["reposted_post"] = True
                if cls._should_follow_threads_media_key(key):
                    walk(child, f"{path}.{key}", depth + 1)

        walk(post, "$", 0)
        return {
            "candidates": candidates,
            "thumbnail": first_thumbnail,
            "heights": sorted(heights, reverse=True),
            "paths_examined": paths_examined,
            "flags": flags,
            **stats,
        }

    @classmethod
    def _threads_post_video_urls(cls, post: Dict[str, Any]) -> List[str]:
        """相容舊呼叫：回傳 recursive resolver 找到的 progressive MP4 URL。"""
        resolved = cls.resolve_threads_media(post)
        return [
            candidate["video_url"]
            for candidate in resolved["candidates"]
            if candidate.get("kind") == "progressive"
        ]

    @classmethod
    def _threads_diagnostics(
        cls,
        post_id: str,
        post: Dict[str, Any],
        resolved: Dict[str, Any],
    ) -> Dict[str, Any]:
        direct_versions = post.get("video_versions")
        carousel = post.get("carousel_media")
        candidates = resolved.get("candidates") or []
        progressive_count = sum(1 for item in candidates if item.get("kind") == "progressive")
        dash_count = sum(1 for item in candidates if item.get("kind") == "dash")
        nested_count = sum(1 for item in candidates if not str(item.get("source_path") or "").startswith("$.video_"))
        return {
            "post_id": post_id,
            "media_type": post.get("media_type"),
            "direct_video_versions_count": len(direct_versions) if isinstance(direct_versions, list) else 0,
            "video_dash_manifest_present": isinstance(post.get("video_dash_manifest"), str)
            and bool(post.get("video_dash_manifest", "").strip()),
            "carousel_count": len(carousel) if isinstance(carousel, list) else 0,
            "quoted_post_present": bool((resolved.get("flags") or {}).get("quoted_post")),
            "reposted_post_present": bool((resolved.get("flags") or {}).get("reposted_post")),
            "candidate_count": len(candidates),
            "progressive_candidates": progressive_count,
            "dash_candidates": dash_count,
            "nested_candidates_count": nested_count,
            "resolver_paths_examined": list(resolved.get("paths_examined") or []),
            "resolver_node_count": resolved.get("node_count", 0),
            "resolver_max_depth": resolved.get("max_depth_reached", 0),
            "resolver_loop_skips": resolved.get("loop_skips", 0),
            "resolver_truncated": bool(resolved.get("truncated")),
            "dash_parse_errors": resolved.get("dash_parse_errors", 0),
        }

    @staticmethod
    def _is_threads_cookie(cookie: Any) -> bool:
        domain = str(getattr(cookie, "domain", "") or "").lstrip(".").lower()
        return any(domain == item or domain.endswith(f".{item}") for item in _THREADS_DOMAINS)

    def _threads_cookie_header(self, cookie_source: Optional[str]) -> str:
        """沿用 yt-dlp 的 Cookie loader，但只送出 Threads 網域 Cookie。"""
        opts: Dict[str, Any] = {"quiet": True, "no_warnings": True}
        self.apply_cookie_opts(opts, cookie_source)

        if "cookiefile" not in opts and "cookiesfrombrowser" not in opts:
            return ""

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                jar = ydl.cookiejar
                selected = {}
                for cookie in jar:
                    if self._is_threads_cookie(cookie):
                        name = str(getattr(cookie, "name", "") or "")
                        value = str(getattr(cookie, "value", "") or "")
                        if name and value:
                            selected[name] = value
        except Exception as exc:
            source = cookie_source or "cookies.txt"
            raise RuntimeError(
                f"讀取 Threads 登入 Cookie 失敗 ({source})。"
                "若使用 Chrome/Edge，請先完全關閉瀏覽器後重試，"
                "或改用 cookies.txt。"
            ) from exc

        if not selected:
            raise ValueError(
                "選取的登入憑證中找不到 Threads Cookie。"
                "請先在該瀏覽器登入 threads.com，或匯入由 Threads 登入工作階段匯出的 cookies.txt。"
            )
        return "; ".join(f"{name}={value}" for name, value in selected.items())

    def _fetch_threads_page(
        self,
        clean_url: str,
        cookie_source: Optional[str],
    ) -> tuple[str, bool]:
        cookie_header = self._threads_cookie_header(cookie_source)
        headers = {
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        if cookie_header:
            headers["Cookie"] = cookie_header

        request = urllib.request.Request(clean_url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                webpage = response.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            raise RuntimeError(f"連線至 Threads 失敗: {exc}") from exc
        return webpage, bool(cookie_header)

    def _extract_threads_info(
        self,
        url: str,
        cookies_browser: Optional[str] = None,
    ) -> Dict[str, Any]:
        """使用 browser-like navigation + 可選登入 Cookie 取得目標 Threads 影片。"""
        clean_url = self._normalize_threads_url(url)
        post_match = re.search(r"/post/([A-Za-z0-9_-]+)", clean_url)
        if not post_match:
            raise ValueError("無法從 Threads 網址辨識貼文 ID；請使用 @使用者/post/<id> 形式的網址。")
        post_id = post_match.group(1)
        self._last_threads_diagnostics = None

        webpage, authenticated = self._fetch_threads_page(clean_url, cookies_browser)

        posts = self._extract_threads_posts_from_html(webpage)
        target_post = next((post for post in posts if post.get("code") == post_id), None)
        if target_post is None:
            target_post = self._find_threads_post_in_embedded_payload(webpage, post_id)

        if target_post is None:
            if not authenticated:
                raise ValueError(
                    "Threads 未回傳可解析的影片資料。"
                    "請在「登入憑證」選擇已登入 Threads 的 Chrome / Edge / Firefox，"
                    "或匯入 cookies.txt 後再試。"
                )
            raise ValueError(
                f"已使用 Threads 登入 Cookie，但頁面中仍找不到目標貼文 {post_id} 的媒體資料。"
                "登入可能已失效，或 Threads 已變更頁面結構；為避免誤抓推薦影片，下載已中止。"
            )

        resolved = self.resolve_threads_media(target_post, base_url=clean_url)
        diagnostics = self._threads_diagnostics(post_id, target_post, resolved)
        self._last_threads_diagnostics = diagnostics
        candidates = resolved["candidates"]
        selected = next((item for item in candidates if item.get("kind") == "progressive"), None)
        if selected is None:
            selected = next((item for item in candidates if item.get("kind") == "dash"), None)

        if selected is None:
            media_type = target_post.get("media_type")
            if media_type == 1:
                kind = "圖片貼文"
            elif media_type == 8:
                kind = "輪播貼文，但未找到影片項目"
            else:
                kind = "沒有可下載影片或影片資料結構已變更"
            summary = (
                f"post_id={post_id}, media_type={media_type}, "
                f"direct_video_versions={diagnostics['direct_video_versions_count']}, "
                f"dash_manifest={diagnostics['video_dash_manifest_present']}, "
                f"carousel={diagnostics['carousel_count']}, "
                f"quoted={diagnostics['quoted_post_present']}, reposted={diagnostics['reposted_post_present']}, "
                f"nested_candidates={diagnostics['nested_candidates_count']}, "
                f"paths={len(diagnostics['resolver_paths_examined'])}"
            )
            raise ValueError(f"此 Threads 貼文存在，但{kind}。診斷: {summary}")

        user = target_post.get("user") if isinstance(target_post.get("user"), dict) else {}
        username = user.get("username")
        if not username:
            user_match = re.search(r"/@([A-Za-z0-9_.-]+)", clean_url)
            username = user_match.group(1) if user_match else "threads_user"

        caption_obj = target_post.get("caption")
        caption = caption_obj.get("text") if isinstance(caption_obj, dict) else None
        if not isinstance(caption, str) or not caption.strip():
            caption = target_post.get("accessibility_caption")
        if not isinstance(caption, str) or not caption.strip():
            caption = f"Threads 影片 (@{username})"

        caption_clean = re.sub(r'[\r\n\t\\/:*?"<>|]+', " ", caption).strip()
        title = f"Threads - @{username} - {caption_clean[:50]}" if caption_clean else f"Threads_@{username}_{post_id}"
        progressive_urls = [
            item["video_url"] for item in candidates if item.get("kind") == "progressive"
        ]
        direct_urls = progressive_urls or [
            item["video_url"] for item in candidates if item.get("kind") == "dash"
        ]

        return {
            "id": post_id,
            "title": title,
            "uploader": f"@{username}",
            "duration": None,
            "duration_str": "短影音",
            "thumbnail": resolved.get("thumbnail"),
            "webpage_url": target_post.get("canonical_url") or clean_url,
            "platform": self.detect_platform(url),
            "available_resolutions": resolved.get("heights") or [selected.get("height") or 1080],
            "available_subtitles": [],
            "is_direct_stream": True,
            "direct_video_url": selected["video_url"],
            "direct_audio_url": selected.get("audio_url"),
            "direct_video_urls": direct_urls,
            "threads_media_kind": selected["kind"],
            "threads_media_source_path": selected.get("source_path"),
            "http_headers": {
                "User-Agent": _BROWSER_UA,
                "Referer": clean_url,
            },
            "raw_info": {
                "title": title,
                "threads_parser": "authenticated_browser_html_recursive",
                "threads_post_id": post_id,
                "threads_media_kind": selected["kind"],
                "threads_media_source_path": selected.get("source_path"),
                "threads_video_count": len(direct_urls),
                "threads_candidate_count": len(candidates),
                "threads_authenticated": authenticated,
                "threads_diagnostics": diagnostics,
            },
        }

    def extract_info(self, url: str, cookies_browser: Optional[str] = None) -> Dict[str, Any]:
        if self.detect_platform(url).get("name") == "Threads":
            return self._extract_threads_info(url, cookies_browser)
        return super().extract_info(url, cookies_browser=cookies_browser)

    def _download_threads_stream(
        self,
        source_url: str,
        destination: Path,
        headers: Dict[str, str],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> None:
        request = urllib.request.Request(source_url, headers=headers)
        part = destination.with_suffix(destination.suffix + ".part")
        started = time.time()

        try:
            with urllib.request.urlopen(request, timeout=60) as response, open(part, "wb") as fh:
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                while True:
                    if self._is_cancelled:
                        raise RuntimeError("使用者已取消下載")
                    chunk = response.read(512 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        elapsed = max(time.time() - started, 0.001)
                        speed = downloaded / elapsed
                        eta = int((total - downloaded) / speed) if total and speed else None
                        progress_callback(
                            {
                                "status": "downloading",
                                "downloaded_bytes": downloaded,
                                "total_bytes": total or None,
                                "_percent_str": f"{(downloaded / total * 100):.1f}%" if total else "--%",
                                "_speed_str": f"{speed / 1024 / 1024:.1f} MiB/s",
                                "_eta_str": str(eta) if eta is not None else "--:--",
                            }
                        )
            part.replace(destination)
        except Exception:
            try:
                part.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        if progress_callback:
            progress_callback({"status": "finished", "filename": str(destination)})

    def _threads_ffmpeg_executable(self) -> str:
        if self.ffmpeg_dir:
            directory = Path(self.ffmpeg_dir)
            for name in ("ffmpeg.exe", "ffmpeg"):
                candidate = directory / name
                if candidate.is_file():
                    return str(candidate)
            return str(directory / "ffmpeg.exe")
        return "ffmpeg"

    def _merge_threads_dash(
        self,
        video_path: Path,
        audio_path: Optional[Path],
        destination: Path,
    ) -> None:
        cmd = [self._threads_ffmpeg_executable(), "-y", "-i", str(video_path)]
        if audio_path is not None:
            cmd.extend(["-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0?"])
        else:
            cmd.extend(["-map", "0:v:0"])
        cmd.extend(["-c", "copy", "-movflags", "+faststart", str(destination)])
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise RuntimeError("Threads DASH 串流已下載，但 FFmpeg 合併/封裝失敗。") from exc

    def _download_threads_dash(
        self,
        video_url: str,
        audio_url: Optional[str],
        destination: Path,
        headers: Dict[str, str],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> None:
        video_part = destination.with_name(f"{destination.stem}.threads-video.mp4")
        audio_part = destination.with_name(f"{destination.stem}.threads-audio.m4a") if audio_url else None
        try:
            self._download_threads_stream(video_url, video_part, headers, progress_callback)
            if audio_url and audio_part is not None:
                self._download_threads_stream(audio_url, audio_part, headers, None)
            self._merge_threads_dash(video_part, audio_part, destination)
        finally:
            video_part.unlink(missing_ok=True)
            video_part.with_suffix(video_part.suffix + ".part").unlink(missing_ok=True)
            if audio_part is not None:
                audio_part.unlink(missing_ok=True)
                audio_part.with_suffix(audio_part.suffix + ".part").unlink(missing_ok=True)

    def download(
        self,
        url: str,
        output_dir: Path,
        mode: str = "video",
        quality: str = "best",
        keep_audio: bool = False,
        audio_format: str = "mp3",
        download_captions: bool = False,
        caption_langs: Optional[List[str]] = None,
        cookies_browser: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        if self.detect_platform(url).get("name") != "Threads":
            return super().download(
                url=url,
                output_dir=output_dir,
                mode=mode,
                quality=quality,
                keep_audio=keep_audio,
                audio_format=audio_format,
                download_captions=download_captions,
                caption_langs=caption_langs,
                cookies_browser=cookies_browser,
                progress_callback=progress_callback,
                log_callback=log_callback,
            )

        self._is_cancelled = False
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        def log(message: str) -> None:
            if log_callback:
                log_callback(message)

        log("🧵 正在使用 Threads 登入工作階段取得影片串流...")
        try:
            info = self._extract_threads_info(url, cookies_browser)
        except Exception:
            if self._last_threads_diagnostics:
                log(
                    "Threads resolver diagnostics: "
                    + json.dumps(self._last_threads_diagnostics, ensure_ascii=False, separators=(",", ":"))
                )
            raise

        title = info["title"]
        safe_title = re.sub(r'[\r\n\t\\/:*?"<>|]+', " ", title).strip().rstrip(". ")
        safe_title = safe_title[:140] or f"Threads_{info['id']}"

        video_path = output_dir / f"{safe_title}.mp4"
        media_kind = info.get("threads_media_kind") or "progressive"
        log(f"✅ 已取得目標貼文串流: {title}")
        if media_kind == "dash":
            log("📹 找到 Threads DASH 串流，開始下載並用 FFmpeg 合併/封裝...")
            self._download_threads_dash(
                info["direct_video_url"],
                info.get("direct_audio_url"),
                video_path,
                info["http_headers"],
                progress_callback,
            )
        else:
            log("📹 開始下載 Threads progressive MP4...")
            self._download_threads_stream(
                info["direct_video_url"],
                video_path,
                info["http_headers"],
                progress_callback,
            )

        downloaded_file: Path = video_path
        if mode == "audio":
            log(f"🎵 正在轉換為 {audio_format.upper()}...")
            audio_path = self.extract_audio_from_file(video_path, audio_format)
            if not audio_path:
                raise RuntimeError("Threads 影片已下載，但音訊轉檔失敗。")
            video_path.unlink(missing_ok=True)
            downloaded_file = audio_path
        elif keep_audio:
            log(f"🎵 正在另外產出 {audio_format.upper()} 音訊...")
            self.extract_audio_from_file(video_path, audio_format)

        log("🎉 Threads 下載完成！")
        return {
            "status": "success",
            "file": str(downloaded_file),
            "title": title,
        }
