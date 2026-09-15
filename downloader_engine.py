import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yt_dlp


def get_ffmpeg_path() -> Optional[str]:
    """尋找 FFmpeg 可執行檔路徑 (支援 PyInstaller 單檔解壓、程式同級目錄、bin 目錄與系統 PATH)"""
    # 1. 檢查 PyInstaller 單檔臨時解壓目錄
    if hasattr(sys, "_MEIPASS"):
        meipass_ffmpeg = Path(sys._MEIPASS) / "ffmpeg.exe"
        if meipass_ffmpeg.is_file():
            return str(meipass_ffmpeg.parent)

    # 2. 檢查程式所在目錄 (包含 PyInstaller onedir 模式下的 sys.executable 目錄)
    base_dirs = []
    if getattr(sys, "frozen", False):
        base_dirs.append(Path(sys.executable).resolve().parent)
    base_dirs.append(Path(__file__).resolve().parent)

    for b in base_dirs:
        if (b / "ffmpeg.exe").is_file():
            return str(b)
        if (b / "bin" / "ffmpeg.exe").is_file():
            return str(b / "bin")

    # 3. 檢查系統 PATH
    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg:
        return str(Path(which_ffmpeg).parent)

    return None


class DownloaderEngine:
    """多平台社群影音下載核心引擎"""

    def __init__(self):
        self.ffmpeg_dir = get_ffmpeg_path()
        self._is_cancelled = False

    def cancel(self):
        """設定取消標誌"""
        self._is_cancelled = True

    @staticmethod
    def detect_platform(url: str) -> Dict[str, Any]:
        """依據網址辨識社群平台資訊"""
        u = url.lower()
        if "youtube.com" in u or "youtu.be" in u:
            return {
                "name": "YouTube",
                "color": "#FF0000",
                "bg_color": "#FFE5E5",
                "text_color": "#CC0000",
                "has_subtitles": True,
                "supports_quality": True,
                "icon": "▶️",
            }
        elif "facebook.com" in u or "fb.watch" in u or "fb.com" in u:
            return {
                "name": "Facebook",
                "color": "#1877F2",
                "bg_color": "#E7F3FF",
                "text_color": "#1877F2",
                "has_subtitles": False,
                "supports_quality": True,
                "icon": "👥",
            }
        elif "instagram.com" in u:
            return {
                "name": "Instagram",
                "color": "#E1306C",
                "bg_color": "#FCE9F0",
                "text_color": "#C13584",
                "has_subtitles": False,
                "supports_quality": False,
                "icon": "📸",
            }
        elif "twitter.com" in u or "x.com" in u:
            return {
                "name": "X (Twitter)",
                "color": "#1DA1F2",
                "bg_color": "#E8F5FD",
                "text_color": "#0F1419",
                "has_subtitles": False,
                "supports_quality": True,
                "icon": "🐦",
            }
        elif "tiktok.com" in u or "douyin.com" in u:
            return {
                "name": "TikTok",
                "color": "#FE2C55",
                "bg_color": "#FFEBF0",
                "text_color": "#FE2C55",
                "has_subtitles": False,
                "supports_quality": False,
                "icon": "🎵",
            }
        elif "bilibili.com" in u or "b23.tv" in u:
            return {
                "name": "Bilibili",
                "color": "#00AEEC",
                "bg_color": "#E5F7FD",
                "text_color": "#00AEEC",
                "has_subtitles": True,
                "supports_quality": True,
                "icon": "📺",
            }
        elif "threads.net" in u or "threads.com" in u:
            return {
                "name": "Threads",
                "color": "#000000",
                "bg_color": "#F3F4F6",
                "text_color": "#111827",
                "has_subtitles": False,
                "supports_quality": False,
                "icon": "🧵",
            }
        else:
            return {
                "name": "通用平台",
                "color": "#4B5563",
                "bg_color": "#F3F4F6",
                "text_color": "#374151",
                "has_subtitles": False,
                "supports_quality": True,
                "icon": "🌐",
            }

    @staticmethod
    def format_duration(seconds: Any) -> str:
        """將秒數轉為 HH:MM:SS 或 MM:SS (相容 float 浮點數與 int 整數)"""
        try:
            if seconds is None:
                return "未知長度"
            sec = int(round(float(seconds)))
            if sec <= 0:
                return "未知長度"
            m, s = divmod(sec, 60)
            h, m = divmod(m, 60)
            if h > 0:
                return f"{h:02d}:{m:02d}:{s:02d}"
            return f"{m:02d}:{s:02d}"
        except Exception:
            return "未知長度"

    @staticmethod
    def apply_cookie_opts(opts: Dict[str, Any], cookie_source: Optional[str]) -> None:
        """套用 Cookie 設定 (支援瀏覽器名稱如 chrome/firefox，或 cookies.txt 檔案路徑)"""
        if not cookie_source or cookie_source.lower() == "none":
            # 自動檢查當前目錄是否有 cookies.txt
            local_cookie = Path.cwd() / "cookies.txt"
            if local_cookie.is_file():
                opts["cookiefile"] = str(local_cookie)
            return

        cs = cookie_source.strip()
        cp = Path(cs)
        if cp.is_file() or cs.lower().endswith(".txt") or cs.lower().endswith(".cookie"):
            if cp.is_file():
                opts["cookiefile"] = str(cp.resolve())
            else:
                raise FileNotFoundError(f"找不到指定的 Cookie 檔案: {cs}")
        elif cs.lower() in ("chrome", "edge", "firefox", "brave", "opera", "safari"):
            opts["cookiesfrombrowser"] = (cs.lower(),)

    def _extract_threads_info(self, url: str) -> Dict[str, Any]:
        """專用 Threads 解析器：直接從 Meta 網頁結構中提取 MP4 影片串流與中繼資料"""
        clean_url = url.split("?")[0].rstrip("/")
        if clean_url.endswith("/media"):
            clean_url = clean_url[:-6]
        clean_url = clean_url.replace("threads.com", "threads.net")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Site": "none",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        req = urllib.request.Request(clean_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            raise RuntimeError(f"連線至 Threads 失敗: {e}")

        # 1. 尋找影片串流 (多層容錯提取)
        clean_html = html.replace(r"\/", "/")
        direct_url = None

        # 優先方案 A: 尋找 Meta CDN 的 t16 影片串流 (最穩定)
        t16_matches = [m for m in re.findall(r'https://[^\s"\'<>]+\.mp4[^\s"\'<>]*', clean_html) if "/t16/" in m]
        if t16_matches:
            direct_url = t16_matches[0]

        # 備用方案 B: 從 video_versions 結構提取
        if not direct_url:
            vurls = re.findall(r'\"video_versions\":.*?\"url\":\"(https://[^\"]+)\"', clean_html, re.DOTALL)
            if vurls:
                direct_url = vurls[0]

        # 備用方案 C: 任何 scontent 或 cdninstagram 的 mp4 串流 (排除 rsrc 靜態檔)
        if not direct_url:
            for m in re.findall(r'https://[^\s"\'<>]+\.mp4[^\s"\'<>]*', clean_html):
                if ("scontent" in m or "cdninstagram" in m) and "rsrc.php" not in m:
                    direct_url = m
                    break

        if not direct_url:
            raise ValueError("此 Threads 貼文中未偵測到任何影片串流或可能已被刪除。")

        # 2. 尋找作者與貼文 ID
        user_match = re.search(r"/@([A-Za-z0-9_.-]+)", clean_url)
        username = user_match.group(1) if user_match else "threads_user"

        post_match = re.search(r"/post/([A-Za-z0-9_-]+)", clean_url)
        post_id = post_match.group(1) if post_match else "post"

        # 3. 尋找內文 / 標題
        caption_match = re.search(r'\"caption\":\{.*?\"text\":\"([^\"]+)\"', html)
        caption = caption_match.group(1) if caption_match else f"Threads 影片 (@{username})"
        try:
            caption = json.loads(f'"{caption}"')
        except Exception:
            pass
        caption_clean = re.sub(r'[\r\n\t\\/:*?"<>|]+', " ", caption).strip()
        title = f"Threads - @{username} - {caption_clean[:50]}" if caption_clean else f"Threads_@{username}_{post_id}"

        # 4. 尋找縮圖
        thumb = None
        thumb_match = re.search(r'<meta\s+property=[\"\']og:image[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html)
        if thumb_match:
            thumb = thumb_match.group(1)
        else:
            img_match = re.search(r'\"image_versions2\":\{.*?\"url\":\"([^\"]+)\"', html)
            if img_match:
                thumb = img_match.group(1).replace(r"\/", "/")

        return {
            "id": post_id,
            "title": title,
            "uploader": f"@{username}",
            "duration": None,
            "duration_str": "短影音",
            "thumbnail": thumb,
            "webpage_url": clean_url,
            "platform": self.detect_platform(url),
            "available_resolutions": [1080],
            "available_subtitles": [],
            "is_direct_stream": True,
            "direct_video_url": direct_url,
            "raw_info": {"title": title},
        }

    def extract_info(self, url: str, cookies_browser: Optional[str] = None) -> Dict[str, Any]:
        """抓取影片資訊 (非同步背景執行用)"""
        platform = self.detect_platform(url)

        # 若為 Threads 平台，使用專屬原生解析器
        if platform.get("name") == "Threads":
            return self._extract_threads_info(url)

        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
            "js_runtimes": {"node": {}},
        }
        self.apply_cookie_opts(opts, cookies_browser)
        if self.ffmpeg_dir:
            opts["ffmpeg_location"] = self.ffmpeg_dir

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            err = str(e)
            if "could not copy chrome cookie database" in err.lower() or "permission denied" in err.lower():
                raise RuntimeError("讀取瀏覽器 Cookie 失敗 (資料庫被鎖定)。請先關閉 Chrome/Edge，或改用 cookies.txt 檔案。")
            raise

        if not info:
            raise ValueError("無法解析影片中繼資料")

        # 處理可能的多格式與解析度
        formats = info.get("formats", [])
        heights = set()
        for f in formats:
            h = f.get("height")
            if h and isinstance(h, int) and h >= 240:
                heights.add(h)
        sorted_heights = sorted(list(heights), reverse=True)

        # 字幕語言偵測
        subtitles = list(info.get("subtitles", {}).keys())
        auto_subs = list(info.get("automatic_captions", {}).keys())
        all_subs = sorted(list(set(subtitles + auto_subs)))

        return {
            "id": info.get("id"),
            "title": info.get("title", "未命名影片"),
            "uploader": info.get("uploader") or info.get("channel") or "未知作者",
            "duration": info.get("duration"),
            "duration_str": self.format_duration(info.get("duration")),
            "thumbnail": info.get("thumbnail"),
            "webpage_url": info.get("webpage_url", url),
            "platform": platform,
            "available_resolutions": sorted_heights,
            "available_subtitles": all_subs,
            "raw_info": info,
        }

    @staticmethod
    def expand_caption_languages(langs: List[str]) -> List[str]:
        """擴充字幕代碼清單，優先納入 *-orig 原始字幕以避免觸發 YouTube 429 翻譯限速"""
        expanded = []
        for lang in langs:
            l = lang.strip().lower()
            if l in ("en", "english"):
                if "en-orig" not in expanded:
                    expanded.append("en-orig")
                if "en" not in expanded:
                    expanded.append("en")
            elif l in ("zh", "zh-tw", "zh-hant", "chinese"):
                for code in ("zh-TW", "zh-Hant", "zh-orig", "zh", "zh-Hans"):
                    if code not in expanded:
                        expanded.append(code)
            else:
                if lang not in expanded:
                    expanded.append(lang)
                orig_variant = f"{lang}-orig"
                if orig_variant not in expanded:
                    expanded.insert(0, orig_variant)
        return expanded

    def extract_audio_from_file(self, video_path: Path, audio_format: str = "mp3") -> Optional[Path]:
        """使用 FFmpeg 從 MP4 中擷取獨立音訊檔"""
        if not video_path.is_file():
            return None
        audio_path = video_path.with_suffix(f".{audio_format.lower()}")
        ffmpeg_cmd = "ffmpeg"
        if self.ffmpeg_dir:
            ffmpeg_cmd = str(Path(self.ffmpeg_dir) / "ffmpeg.exe")

        if audio_format.lower() in ("m4a", "aac"):
            cmd = [ffmpeg_cmd, "-y", "-i", str(video_path), "-vn", "-c:a", "copy", str(audio_path)]
        else:
            cmd = [ffmpeg_cmd, "-y", "-i", str(video_path), "-vn", "-q:a", "0", str(audio_path)]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return audio_path
        except Exception:
            return None

    def download(
        self,
        url: str,
        output_dir: Path,
        mode: str = "video",  # "video" or "audio"
        quality: str = "best",  # "best", "2160", "1440", "1080", "720", "480"
        keep_audio: bool = False,
        audio_format: str = "mp3",
        download_captions: bool = False,
        caption_langs: Optional[List[str]] = None,
        cookies_browser: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        執行多平台影音下載與轉檔

        :param url: 目標影片網址
        :param output_dir: 儲存目錄
        :param mode: "video" (視訊) 或 "audio" (純音訊)
        :param quality: 畫質限制
        :param keep_audio: 是否同時保留獨立音訊檔
        :param audio_format: 音訊副檔名 ("mp3", "m4a")
        :param download_captions: 是否下載字幕
        :param caption_langs: 字幕語言代碼
        :param cookies_browser: 瀏覽器 cookies
        :param progress_callback: 下載進度回呼
        :param log_callback: 文字日誌回呼
        """
        self._is_cancelled = False
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        def log(msg: str):
            if log_callback:
                log_callback(msg)

        def ydl_hook(d):
            if self._is_cancelled:
                raise Exception("使用者已取消下載")
            if progress_callback:
                progress_callback(d)

        platform_info = self.detect_platform(url)
        log(f"🎬 偵測平台: {platform_info['name']} ({platform_info['icon']})")
        log(f"📁 儲存目標: {output_dir}")

        target_dl_url = url
        custom_title = None

        if platform_info.get("name") == "Threads":
            log("🧵 正在提取 Threads 高畫質 MP4 影片串流...")
            t_info = self._extract_threads_info(url)
            target_dl_url = t_info["direct_video_url"]
            custom_title = t_info["title"]
            log(f"✅ 成功獲取串流，標題: {custom_title}")

        # 1. 字幕下載階段 (若支援且啟用)
        if download_captions and platform_info.get("has_subtitles", False):
            langs = self.expand_caption_languages(caption_langs or ["zh-TW", "zh", "en"])
            log(f"📝 正在下載 SRT 字幕: {', '.join(langs)}")
            sub_opts = {
                "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
                "windowsfilenames": True,
                "quiet": True,
                "no_warnings": True,
                "ignoreerrors": True,
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": langs,
                "js_runtimes": {"node": {}},
                "postprocessors": [
                    {
                        "key": "FFmpegSubtitlesConvertor",
                        "format": "srt",
                        "when": "before_dl",
                    }
                ],
            }
            self.apply_cookie_opts(sub_opts, cookies_browser)
            if self.ffmpeg_dir:
                sub_opts["ffmpeg_location"] = self.ffmpeg_dir

            try:
                with yt_dlp.YoutubeDL(sub_opts) as ydl_sub:
                    ydl_sub.download([url])
                log("✅ 字幕處理完成")
            except Exception as e:
                log(f"⚠️ 字幕下載略過: {e}")

        # 2. 視訊或純音訊下載
        if custom_title:
            outtmpl = str(output_dir / f"{custom_title}.%(ext)s")
        else:
            outtmpl = str(output_dir / "%(title)s.%(ext)s")

        common_opts = {
            "outtmpl": outtmpl,
            "windowsfilenames": True,
            "progress_hooks": [ydl_hook],
            "quiet": True,
            "no_warnings": False,
            "ignoreerrors": False,
            "js_runtimes": {"node": {}},
        }
        self.apply_cookie_opts(common_opts, cookies_browser)
        if self.ffmpeg_dir:
            common_opts["ffmpeg_location"] = self.ffmpeg_dir

        downloaded_file = None

        if mode == "video":
            # 建立格式規格
            if platform_info.get("name") == "Threads":
                fmt = "best"
            elif quality == "best":
                fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
            else:
                fmt = f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"

            common_opts["format"] = fmt
            common_opts["merge_output_format"] = "mp4"

            log(f"📹 開始下載視訊串流 (畫質規格: {quality})...")
            with yt_dlp.YoutubeDL(common_opts) as ydl:
                info = ydl.extract_info(target_dl_url, download=True)
                title = custom_title or info.get("title", "影片")
                log(f"✨ 視訊下載並合併完成: {title}")

                # 取得預計輸出路徑
                if custom_title:
                    expected_video_path = output_dir / f"{custom_title}.mp4"
                else:
                    expected_video_path = output_dir / f"{ydl.prepare_filename(info)}"
                    if expected_video_path.suffix != ".mp4":
                        expected_video_path = expected_video_path.with_suffix(".mp4")
                downloaded_file = expected_video_path

                # 若勾選額外抽取音訊
                if keep_audio and expected_video_path.is_file():
                    log(f"🎵 正在從 MP4 抽取獨立音訊檔 ({audio_format.upper()})...")
                    audio_res = self.extract_audio_from_file(expected_video_path, audio_format)
                    if audio_res:
                        log(f"✅ 獨立音訊檔已產出: {audio_res.name}")

        else:
            # 純音訊模式
            common_opts["format"] = "bestaudio/best"
            common_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": "0",
                }
            ]
            log(f"🎵 開始下載音訊並轉檔為 {audio_format.upper()}...")
            with yt_dlp.YoutubeDL(common_opts) as ydl:
                info = ydl.extract_info(target_dl_url, download=True)
                title = custom_title or info.get("title", "音訊")
                log(f"✨ 音訊處理完成: {title}")
                if custom_title:
                    expected_audio = output_dir / f"{custom_title}.{audio_format}"
                else:
                    expected_audio = output_dir / f"{Path(ydl.prepare_filename(info)).stem}.{audio_format}"
                downloaded_file = expected_audio

        log("🎉 所有下載與後製作業均已完成！")
        return {
            "status": "success",
            "file": str(downloaded_file) if downloaded_file else None,
            "title": title,
        }
