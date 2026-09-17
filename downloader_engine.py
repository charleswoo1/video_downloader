import html as html_lib
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yt_dlp

from downloader_engine_base import DownloaderEngine as _BaseDownloaderEngine
from downloader_engine_base import get_ffmpeg_path, get_node_path


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
_THREADS_MEDIA_KEYS = {"video_versions", "video_dash_manifest", "image_versions2", "carousel_media"}
_THREADS_DOMAINS = ("threads.com", "threads.net")


class DownloaderEngine(_BaseDownloaderEngine):
    """下載引擎；Threads 使用已登入瀏覽器 session 解析，其餘平台沿用既有核心。"""

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
            .replace(r"\/", "/")
        )

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
    def _threads_video_urls(media: Dict[str, Any]) -> List[str]:
        """從單一 media dict 取得去重後的 progressive MP4 URL。"""
        urls: List[str] = []
        seen = set()
        for version in media.get("video_versions") or []:
            if not isinstance(version, dict):
                continue
            candidate = version.get("url")
            if not isinstance(candidate, str):
                continue
            candidate = DownloaderEngine._decode_threads_url(candidate)
            if not candidate.startswith(("https://", "http://")):
                continue
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
                    if isinstance(value, str):
                        value = DownloaderEngine._decode_threads_url(value)
                        if value.startswith(("https://", "http://")):
                            return value
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
            "http_headers": {
                "User-Agent": _BROWSER_UA,
                "Referer": clean_url,
            },
            "raw_info": {
                "title": title,
                "threads_parser": "authenticated_browser_html",
                "threads_post_id": post_id,
                "threads_video_count": len(video_urls),
                "threads_authenticated": authenticated,
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
        info = self._extract_threads_info(url, cookies_browser)
        title = info["title"]
        safe_title = re.sub(r'[\r\n\t\\/:*?"<>|]+', " ", title).strip().rstrip(". ")
        safe_title = safe_title[:140] or f"Threads_{info['id']}"

        video_path = output_dir / f"{safe_title}.mp4"
        log(f"✅ 已取得目標貼文串流: {title}")
        log("📹 開始下載 Threads MP4...")
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
