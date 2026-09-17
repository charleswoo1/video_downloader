import html as html_lib
import json
import re
import urllib.request
from typing import Any, Dict, List, Optional

from downloader_engine_base import DownloaderEngine as _BaseDownloaderEngine
from downloader_engine_base import get_ffmpeg_path, get_node_path


_GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
_THREADS_MEDIA_KEYS = {"video_versions", "video_dash_manifest", "image_versions2", "carousel_media"}


class DownloaderEngine(_BaseDownloaderEngine):
    """下載引擎；Threads 使用 crawler SSR JSON 解析，其餘平台沿用既有核心。"""

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

    @classmethod
    def _collect_threads_posts(cls, obj: Any, out: List[Dict[str, Any]]) -> None:
        """遞迴收集帶 shortcode 與媒體欄位的 Threads post dict。"""
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
        """解析 Threads server-rendered application/json 區塊。"""
        posts: List[Dict[str, Any]] = []
        blocks = re.findall(
            r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
            webpage,
            re.IGNORECASE | re.DOTALL,
        )
        for block in blocks:
            try:
                data = json.loads(block)
            except (json.JSONDecodeError, TypeError):
                continue
            cls._collect_threads_posts(data, posts)
        return posts

    @staticmethod
    def _threads_video_urls(media: Dict[str, Any]) -> List[str]:
        """從單一 media dict 取得去重後的 progressive MP4 URL。"""
        urls: List[str] = []
        seen = set()
        for version in media.get("video_versions") or []:
            if not isinstance(version, dict):
                continue
            candidate = version.get("url")
            if not isinstance(candidate, str) or not candidate.startswith(("https://", "http://")):
                continue
            candidate = html_lib.unescape(candidate)
            key = candidate.split("?", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            urls.append(candidate)
        return urls

    @classmethod
    def _threads_post_video_urls(cls, post: Dict[str, Any]) -> List[str]:
        """支援單影片與 carousel；目前 GUI 下載第一個影片，但保留完整 URL 清單。"""
        urls = cls._threads_video_urls(post)
        carousel = post.get("carousel_media")
        if isinstance(carousel, list):
            for item in carousel:
                if isinstance(item, dict):
                    urls.extend(cls._threads_video_urls(item))

        deduped: List[str] = []
        seen = set()
        for candidate in urls:
            key = candidate.split("?", 1)[0]
            if key not in seen:
                seen.add(key)
                deduped.append(candidate)
        return deduped

    @staticmethod
    def _threads_thumbnail(post: Dict[str, Any]) -> Optional[str]:
        def first_candidate(media: Dict[str, Any]) -> Optional[str]:
            image_versions = media.get("image_versions2")
            if not isinstance(image_versions, dict):
                return None
            candidates = image_versions.get("candidates")
            if not isinstance(candidates, list):
                return None
            for candidate in candidates:
                if isinstance(candidate, dict):
                    value = candidate.get("url")
                    if isinstance(value, str) and value.startswith(("https://", "http://")):
                        return html_lib.unescape(value)
            return None

        thumb = first_candidate(post)
        if thumb:
            return thumb
        carousel = post.get("carousel_media")
        if isinstance(carousel, list):
            for item in carousel:
                if isinstance(item, dict):
                    thumb = first_candidate(item)
                    if thumb:
                        return thumb
        return None

    @staticmethod
    def _threads_resolutions(post: Dict[str, Any]) -> List[int]:
        heights = set()

        def collect(media: Dict[str, Any]) -> None:
            original_height = media.get("original_height")
            if isinstance(original_height, int) and original_height > 0:
                heights.add(original_height)
            for version in media.get("video_versions") or []:
                if isinstance(version, dict):
                    height = version.get("height")
                    if isinstance(height, int) and height > 0:
                        heights.add(height)

        collect(post)
        carousel = post.get("carousel_media")
        if isinstance(carousel, list):
            for item in carousel:
                if isinstance(item, dict):
                    collect(item)
        return sorted(heights, reverse=True)

    def _extract_threads_info(self, url: str) -> Dict[str, Any]:
        """以 crawler UA 取得 SSR JSON，並以 shortcode 精準解析目標 Threads 影片。"""
        clean_url = self._normalize_threads_url(url)
        post_match = re.search(r"/post/([A-Za-z0-9_-]+)", clean_url)
        if not post_match:
            raise ValueError("無法從 Threads 網址辨識貼文 ID；請使用 @使用者/post/<id> 形式的網址。")
        post_id = post_match.group(1)

        headers = {
            "User-Agent": _GOOGLEBOT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        request = urllib.request.Request(clean_url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                webpage = response.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            raise RuntimeError(f"連線至 Threads 失敗: {exc}") from exc

        posts = self._extract_threads_posts_from_html(webpage)
        target_post = next((post for post in posts if post.get("code") == post_id), None)
        if target_post is None:
            if not posts:
                raise ValueError(
                    "Threads 未回傳可解析的公開貼文資料；可能需要登入、貼文非公開，或 Threads 已變更頁面結構。"
                )
            raise ValueError(
                f"Threads 頁面已載入，但找不到目標貼文 {post_id} 的媒體資料；為避免抓到推薦影片，下載已中止。"
            )

        video_urls = self._threads_post_video_urls(target_post)
        if not video_urls:
            media_type = target_post.get("media_type")
            if media_type == 1:
                kind = "圖片貼文"
            elif media_type == 8:
                kind = "輪播貼文，但未找到影片項目"
            else:
                kind = "沒有可下載影片或影片資料結構已變更"
            raise ValueError(f"此 Threads 貼文存在，但{kind}。")

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
        resolutions = self._threads_resolutions(target_post)

        return {
            "id": post_id,
            "title": title,
            "uploader": f"@{username}",
            "duration": None,
            "duration_str": "短影音",
            "thumbnail": self._threads_thumbnail(target_post),
            "webpage_url": target_post.get("canonical_url") or clean_url,
            "platform": self.detect_platform(url),
            "available_resolutions": resolutions or [1080],
            "available_subtitles": [],
            "is_direct_stream": True,
            "direct_video_url": video_urls[0],
            "direct_video_urls": video_urls,
            "raw_info": {
                "title": title,
                "threads_parser": "crawler_ssr_json",
                "threads_post_id": post_id,
                "threads_video_count": len(video_urls),
            },
        }
