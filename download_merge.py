import argparse
from pathlib import Path
import subprocess
import sys
from typing import List, Optional

import yt_dlp

# 確保 Windows 終端機正確輸出 UTF-8 編碼與表情符號
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

# ========= 可修改預設設定 =========
# 預設 YouTube 影片網址
DEFAULT_VIDEO_URL = "https://www.youtube.com/watch?v=Xj4pTYsVSWQ"

# 是否下載最高畫質影片 + 音訊並合併為 MP4
DOWNLOAD_VIDEO = True

# 是否單獨保留獨立音訊檔 (MP3 或 M4A)
KEEP_AUDIO = False

# 獨立音訊格式 ("mp3" 或 "m4a")
AUDIO_FORMAT = "mp3"

# 是否下載字幕檔（自動轉為 .srt）
DOWNLOAD_CAPTIONS = True

# 字幕語言偏好清單（優先下載清單中的字幕，如繁中、簡中、英文）
DEFAULT_CAPTION_LANGS = ["zh-TW", "zh-Hant", "zh-orig", "zh", "en-orig", "en"]

# 預設下載目錄
OUTPUT_DIR = Path.cwd()
# ==================================


def expand_caption_languages(langs: List[str]) -> List[str]:
    """擴充字幕代碼清單，優先納入 *-orig 原始字幕以避免觸發 YouTube 429 翻譯限速。"""
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


def extract_audio_from_video(video_path: Path, audio_format: str = "mp3") -> Optional[Path]:
    """使用 FFmpeg 從已下載的 MP4 視訊中快速無損/高音質抽取出獨立音訊檔。"""
    if not video_path.is_file():
        return None

    audio_path = video_path.with_suffix(f".{audio_format.lower()}")
    print(f"\n🎵 正在擷取獨立音訊檔 ({audio_format.upper()}): {audio_path.name} ...")

    if audio_format.lower() in ("m4a", "aac"):
        # 直接無損複製 AAC 軌道，極速完成
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-c:a",
            "copy",
            str(audio_path),
        ]
    else:
        # 轉檔為高品質 MP3 (VBR 最佳音質 -q:a 0)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-q:a",
            "0",
            str(audio_path),
        ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"✅ 獨立音訊檔已儲存: {audio_path}")
        return audio_path
    except Exception as e:
        print(f"⚠️ 音訊擷取失敗: {e}")
        return None


def download_subtitles_phase(
    url: str,
    out_dir: Path,
    caption_langs: List[str],
    cookies_browser: Optional[str] = None,
) -> None:
    """獨立進行字幕下載與轉檔，防止字幕 429 錯誤中斷視訊主下載。"""
    langs = expand_caption_languages(caption_langs)
    sub_opts = {
        "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
        "windowsfilenames": True,
        "quiet": False,
        "no_warnings": False,
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
    if cookies_browser:
        sub_opts["cookiesfrombrowser"] = (cookies_browser,)

    print(f"📝 正在下載與轉換 SRT 字幕 (偏好語言: {', '.join(langs)}) ...")
    try:
        with yt_dlp.YoutubeDL(sub_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"⚠️ 字幕下載略過或部分失敗: {e}")


def download(
    url: str,
    output_dir: Optional[Path] = None,
    download_video: bool = True,
    keep_audio: bool = False,
    audio_format: str = "mp3",
    download_captions: bool = True,
    caption_langs: Optional[List[str]] = None,
    cookies_browser: Optional[str] = None,
) -> None:
    """
    使用 yt-dlp 下載 YouTube 影片、獨立音訊與字幕。

    :param url: YouTube 影片網址
    :param output_dir: 下載檔案存放目錄
    :param download_video: 是否下載影片+音訊並合併為 MP4
    :param keep_audio: 是否額外獨立保留一份音訊檔 (MP3/M4A)
    :param audio_format: 獨立音訊格式 ('mp3' 或 'm4a')
    :param download_captions: 是否下載字幕 (SRT)
    :param caption_langs: 字幕語言代碼清單
    :param cookies_browser: 瀏覽器名稱 (例如 'chrome', 'edge')，用於會員/年齡限制影片
    """
    out_dir = (output_dir or OUTPUT_DIR).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n==========================================")
    print(f"🎬 開始處理 YouTube 影片")
    print(f"🔗 網址: {url}")
    print(f"📁 儲存路徑: {out_dir}")
    print(f"📹 下載視訊: {'是' if download_video else '否'}")
    print(f"🎵 獨立音訊: {'是 (' + audio_format.upper() + ')' if keep_audio else '否'}")
    print(f"📝 下載字幕: {'是' if download_captions else '否'}")
    print(f"==========================================\n")

    # 1. 獨立字幕下載階段（若有開啟）
    if download_captions:
        raw_langs = caption_langs or DEFAULT_CAPTION_LANGS
        download_subtitles_phase(url, out_dir, raw_langs, cookies_browser)

    # 2. 視訊與音訊下載階段
    if download_video:
        ydl_video_opts = {
            "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
            "windowsfilenames": True,
            "quiet": False,
            "no_warnings": False,
            "ignoreerrors": False,
            "js_runtimes": {"node": {}},
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
        }
        if cookies_browser:
            ydl_video_opts["cookiesfrombrowser"] = (cookies_browser,)

        print(f"\n📹 正在下載最高畫質視訊與音訊串流並自動合併...")
        with yt_dlp.YoutubeDL(ydl_video_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                title = info.get("title", "未知名稱")
                print(f"\n✨ 視訊合併完成: {title}")

                # 若需要獨立音訊，從下載完成的 MP4 快速抽取
                if keep_audio:
                    expected_video_path = out_dir / f"{ydl.prepare_filename(info)}"
                    if not expected_video_path.suffix == ".mp4":
                        expected_video_path = expected_video_path.with_suffix(".mp4")
                    extract_audio_from_video(expected_video_path, audio_format=audio_format)
    elif keep_audio:
        # 僅需純音訊時
        ydl_audio_opts = {
            "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
            "windowsfilenames": True,
            "quiet": False,
            "no_warnings": False,
            "ignoreerrors": False,
            "js_runtimes": {"node": {}},
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": "0",
                }
            ],
        }
        if cookies_browser:
            ydl_audio_opts["cookiesfrombrowser"] = (cookies_browser,)

        print(f"\n🎵 正在下載音訊串流並轉檔為 {audio_format.upper()}...")
        with yt_dlp.YoutubeDL(ydl_audio_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                title = info.get("title", "未知名稱")
                print(f"\n✨ 音訊下載完成: {title}")

    print("\n🎉 全部下載與轉檔程序已完成！")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="YouTube 高畫質影片與字幕下載工具 (基於 yt-dlp + FFmpeg)"
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_VIDEO_URL,
        help="YouTube 影片網址（留空時使用預設網址）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=str(OUTPUT_DIR),
        help="指定輸出資料夾路徑 (預設當前目錄)",
    )
    parser.add_argument(
        "--no-video",
        action="store_true",
        help="不下載影片本體",
    )
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="額外獨立保留一份音訊檔案 (MP3/M4A)",
    )
    parser.add_argument(
        "--audio-format",
        type=str,
        default=AUDIO_FORMAT,
        choices=["mp3", "m4a", "aac", "wav", "flac"],
        help="獨立音訊格式 (預設 mp3)",
    )
    parser.add_argument(
        "--no-captions",
        action="store_true",
        help="不下載字幕，僅下載影片",
    )
    parser.add_argument(
        "--langs",
        nargs="+",
        default=DEFAULT_CAPTION_LANGS,
        help="指定字幕語言代碼清單 (例如 zh-TW en ja)",
    )
    parser.add_argument(
        "--cookies-from-browser",
        type=str,
        default=None,
        help="指定瀏覽器帶入登入 Cookie (例如 chrome, edge, firefox)",
    )

    args = parser.parse_args()

    target_url = args.url.strip()
    if not target_url:
        print("❌ 請提供有效的 YouTube 影片網址。")
        sys.exit(1)

    download(
        url=target_url,
        output_dir=Path(args.output),
        download_video=not args.no_video and DOWNLOAD_VIDEO,
        keep_audio=args.keep_audio or KEEP_AUDIO,
        audio_format=args.audio_format,
        download_captions=not args.no_captions and DOWNLOAD_CAPTIONS,
        caption_langs=args.langs,
        cookies_browser=args.cookies_from_browser,
    )


if __name__ == "__main__":
    main()
