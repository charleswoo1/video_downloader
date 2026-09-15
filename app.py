import io
import os
import re
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Dict, Optional

import customtkinter as ctk
from PIL import Image

from config_manager import ConfigManager
from downloader_engine import DownloaderEngine, get_ffmpeg_path

# 設置 Windows UTF-8
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


class VideoDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # 初始化設定與下載引擎
        self.config = ConfigManager()
        self.engine = DownloaderEngine()
        self.current_info: Optional[Dict[str, Any]] = None
        self.is_downloading = False
        self.last_downloaded_file: Optional[str] = None

        # 視窗外觀與尺寸
        ctk.set_appearance_mode(self.config.get("theme", "Dark"))
        ctk.set_default_color_theme("blue")
        self.title("多平台社群影音下載器 v1.0")
        self.geometry("860x780")
        self.minsize(800, 700)

        # 設定視窗圖示
        base_path = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parent
        icon_path = base_path / "assets" / "icon.ico"
        if icon_path.is_file():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

        # 建立 UI 元件
        self._build_ui()
        self._check_environment()

    def _check_environment(self):
        """檢查 FFmpeg 環境並於狀態列提示"""
        ffmpeg_loc = get_ffmpeg_path()
        if not ffmpeg_loc:
            self.log("⚠️ 系統未偵測到 FFmpeg，部分格式合併與字幕轉檔可能受限。")
            self.status_label.configure(
                text="⚠️ 未找到 FFmpeg (建議安裝或將 ffmpeg.exe 放入 bin 資料夾)",
                text_color="#F59E0B",
            )
        else:
            self.log(f"✅ FFmpeg 環境就緒: {ffmpeg_loc}")

    def _build_ui(self):
        # 頂部導航列
        self.header_frame = ctk.CTkFrame(self, corner_radius=10)
        self.header_frame.pack(fill="x", padx=16, pady=(14, 8))

        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="🎬 多平台社群影片下載器",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.title_label.pack(side="left", padx=16, pady=12)

        self.theme_switch = ctk.CTkSwitch(
            self.header_frame,
            text="深色模式",
            command=self._toggle_theme,
            onvalue="Dark",
            offvalue="Light",
        )
        if self.config.get("theme", "Dark") == "Dark":
            self.theme_switch.select()
        else:
            self.theme_switch.deselect()
        self.theme_switch.pack(side="right", padx=16)

        # 滾動主區域 (避免不同解析度螢幕元件溢出)
        self.scroll_frame = ctk.CTkScrollableFrame(self, corner_radius=10)
        self.scroll_frame.pack(fill="both", expand=True, padx=16, pady=6)

        # --- 區塊 1: 網址輸入與解析 ---
        self.url_frame = ctk.CTkFrame(self.scroll_frame, corner_radius=8)
        self.url_frame.pack(fill="x", pady=6, padx=4)

        url_title = ctk.CTkLabel(
            self.url_frame,
            text="🔗 影片網址 (支援 YouTube / Facebook / Instagram / X / TikTok / Bilibili 等)",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        url_title.pack(anchor="w", padx=14, pady=(10, 4))

        url_input_box = ctk.CTkFrame(self.url_frame, fg_color="transparent")
        url_input_box.pack(fill="x", padx=14, pady=(2, 10))

        self.url_entry = ctk.CTkEntry(
            url_input_box,
            placeholder_text="在此貼上影片連結 (例如: https://www.youtube.com/watch?v=... 或 FB/IG/X)",
            height=38,
            font=ctk.CTkFont(size=13),
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.url_entry.bind("<KeyRelease>", self._on_url_typing)

        self.paste_btn = ctk.CTkButton(
            url_input_box,
            text="📋 貼上",
            width=70,
            height=38,
            command=self._paste_url,
        )
        self.paste_btn.pack(side="left", padx=(0, 6))

        self.analyze_btn = ctk.CTkButton(
            url_input_box,
            text="🔍 分析網址",
            width=90,
            height=38,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            command=self._start_analyze_thread,
        )
        self.analyze_btn.pack(side="left", padx=(0, 6))

        self.clear_btn = ctk.CTkButton(
            url_input_box,
            text="✖ 清除",
            width=60,
            height=38,
            fg_color="#4B5563",
            hover_color="#374151",
            command=self._clear_url,
        )
        self.clear_btn.pack(side="left")

        # --- 區塊 2: 影片中繼資訊預覽卡片 ---
        self.info_card = ctk.CTkFrame(self.scroll_frame, corner_radius=8)
        self.info_card.pack(fill="x", pady=6, padx=4)

        info_inner = ctk.CTkFrame(self.info_card, fg_color="transparent")
        info_inner.pack(fill="x", padx=14, pady=12)

        # 縮圖展示 (固定 220x124，16:9)
        self.thumb_label = ctk.CTkLabel(
            info_inner,
            text="暫無縮圖",
            width=220,
            height=124,
            corner_radius=6,
            fg_color="#1E293B",
        )
        self.thumb_label.pack(side="left", padx=(0, 16))

        # 詳細資訊
        info_text_frame = ctk.CTkFrame(info_inner, fg_color="transparent")
        info_text_frame.pack(side="left", fill="both", expand=True)

        badge_row = ctk.CTkFrame(info_text_frame, fg_color="transparent")
        badge_row.pack(fill="x", pady=(0, 4))

        self.platform_badge = ctk.CTkLabel(
            badge_row,
            text="🌐 待辨識平台",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#374151",
            text_color="#FFFFFF",
            corner_radius=6,
            padx=10,
            pady=3,
        )
        self.platform_badge.pack(side="left")

        self.duration_label = ctk.CTkLabel(
            badge_row,
            text="⏱️ 片長: --:--",
            font=ctk.CTkFont(size=12),
            text_color="#9CA3AF",
            padx=12,
        )
        self.duration_label.pack(side="left")

        self.video_title_label = ctk.CTkLabel(
            info_text_frame,
            text="請輸入影片網址並點選「分析網址」以取得影片資訊",
            font=ctk.CTkFont(size=14, weight="bold"),
            wraplength=480,
            justify="left",
            anchor="w",
        )
        self.video_title_label.pack(fill="x", pady=2)

        self.uploader_label = ctk.CTkLabel(
            info_text_frame,
            text="👤 作者 / 頻道: --",
            font=ctk.CTkFont(size=12),
            text_color="#9CA3AF",
            anchor="w",
        )
        self.uploader_label.pack(fill="x", pady=2)

        # --- 區塊 3: 下載選項設定 ---
        self.options_frame = ctk.CTkFrame(self.scroll_frame, corner_radius=8)
        self.options_frame.pack(fill="x", pady=6, padx=4)

        opt_title = ctk.CTkLabel(
            self.options_frame,
            text="⚙️ 下載選項設定",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        opt_title.pack(anchor="w", padx=14, pady=(10, 6))

        # 模式與畫質選擇
        row1 = ctk.CTkFrame(self.options_frame, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=4)

        mode_lbl = ctk.CTkLabel(row1, text="下載模式:", font=ctk.CTkFont(size=13))
        mode_lbl.pack(side="left", padx=(0, 10))

        self.mode_var = ctk.StringVar(value=self.config.get("download_mode", "video"))
        self.mode_seg = ctk.CTkSegmentedButton(
            row1,
            values=["🎬 影片 (MP4)", "🎵 純音訊 (MP3)"],
            command=self._on_mode_change,
        )
        self.mode_seg.set("🎬 影片 (MP4)" if self.mode_var.get() == "video" else "🎵 純音訊 (MP3)")
        self.mode_seg.pack(side="left", padx=(0, 20))

        self.quality_lbl = ctk.CTkLabel(row1, text="影片畫質:", font=ctk.CTkFont(size=13))
        self.quality_lbl.pack(side="left", padx=(0, 8))

        self.quality_menu = ctk.CTkOptionMenu(
            row1,
            values=["最佳畫質 (Best)", "1080p", "720p", "480p", "360p"],
            width=140,
            command=self._on_quality_change,
        )
        self.quality_menu.set("最佳畫質 (Best)")
        self.quality_menu.pack(side="left")

        # 音訊與字幕選項
        row2 = ctk.CTkFrame(self.options_frame, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=6)

        self.keep_audio_var = ctk.BooleanVar(value=self.config.get("keep_audio", False))
        self.keep_audio_check = ctk.CTkCheckBox(
            row2,
            text="下載影片時，同時另外產出獨立 MP3 音訊檔",
            variable=self.keep_audio_var,
            command=self._on_keep_audio_toggle,
        )
        self.keep_audio_check.pack(side="left", padx=(0, 20))

        # 字幕選項 (動態適配)
        row3 = ctk.CTkFrame(self.options_frame, fg_color="transparent")
        row3.pack(fill="x", padx=14, pady=6)

        self.sub_var = ctk.BooleanVar(value=self.config.get("download_captions", True))
        self.sub_check = ctk.CTkCheckBox(
            row3,
            text="下載字幕 (.srt 格式)",
            variable=self.sub_var,
            command=self._on_sub_toggle,
        )
        self.sub_check.pack(side="left", padx=(0, 10))

        self.sub_lang_menu = ctk.CTkOptionMenu(
            row3,
            values=["繁體中文優先 (zh-TW)", "英文優先 (en)", "全部常用 (中/英)"],
            width=160,
        )
        self.sub_lang_menu.set("繁體中文優先 (zh-TW)")
        self.sub_lang_menu.pack(side="left", padx=(0, 10))

        self.sub_hint_lbl = ctk.CTkLabel(
            row3,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#9CA3AF",
        )
        self.sub_hint_lbl.pack(side="left")

        # 儲存路徑
        row4 = ctk.CTkFrame(self.options_frame, fg_color="transparent")
        row4.pack(fill="x", padx=14, pady=(6, 12))

        dir_lbl = ctk.CTkLabel(row4, text="📁 儲存路徑:", font=ctk.CTkFont(size=13))
        dir_lbl.pack(side="left", padx=(0, 8))

        default_dir = self.config.get("output_dir", str(Path.cwd() / "Downloads"))
        self.dir_entry = ctk.CTkEntry(row4, height=32)
        self.dir_entry.insert(0, default_dir)
        self.dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.browse_btn = ctk.CTkButton(
            row4,
            text="瀏覽...",
            width=70,
            height=32,
            command=self._browse_dir,
        )
        self.browse_btn.pack(side="left", padx=(0, 6))

        self.open_dir_btn = ctk.CTkButton(
            row4,
            text="開啟",
            width=60,
            height=32,
            fg_color="#4B5563",
            hover_color="#374151",
            command=self._open_output_dir,
        )
        self.open_dir_btn.pack(side="left")

        # 進階 Cookie 選項
        row5 = ctk.CTkFrame(self.options_frame, fg_color="transparent")
        row5.pack(fill="x", padx=14, pady=(0, 10))

        cookie_lbl = ctk.CTkLabel(
            row5,
            text="🍪 瀏覽器登入憑證 (選用，遇到年齡/會員/私密影片時使用):",
            font=ctk.CTkFont(size=12),
            text_color="#9CA3AF",
        )
        cookie_lbl.pack(side="left", padx=(0, 8))

        self.cookie_menu = ctk.CTkOptionMenu(
            row5,
            values=["none", "chrome", "edge", "firefox", "brave"],
            width=100,
            height=28,
            command=lambda v: self.config.set("browser_cookies", v),
        )
        self.cookie_menu.set(self.config.get("browser_cookies", "none"))
        self.cookie_menu.pack(side="left")

        # --- 區塊 4: 底部進度與控制 ---
        self.bottom_frame = ctk.CTkFrame(self, corner_radius=10)
        self.bottom_frame.pack(fill="x", padx=16, pady=(6, 14))

        # 下載按鈕與狀態
        btn_box = ctk.CTkFrame(self.bottom_frame, fg_color="transparent")
        btn_box.pack(fill="x", padx=14, pady=(10, 4))

        self.download_btn = ctk.CTkButton(
            btn_box,
            text="🚀 開始下載 (Start Download)",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=44,
            fg_color="#10B981",
            hover_color="#059669",
            command=self._start_download_thread,
        )
        self.download_btn.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.open_file_btn = ctk.CTkButton(
            btn_box,
            text="🎥 播放檔案",
            height=44,
            width=110,
            state="disabled",
            fg_color="#3B82F6",
            command=self._play_downloaded_file,
        )
        self.open_file_btn.pack(side="left", padx=(0, 6))

        # 進度條
        self.progress_bar = ctk.CTkProgressBar(self.bottom_frame, height=14)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=14, pady=6)

        # 進度數據列
        prog_info_box = ctk.CTkFrame(self.bottom_frame, fg_color="transparent")
        prog_info_box.pack(fill="x", padx=14, pady=(0, 4))

        self.status_label = ctk.CTkLabel(
            prog_info_box,
            text="準備就緒，請貼上網址",
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        self.status_label.pack(side="left")

        self.speed_label = ctk.CTkLabel(
            prog_info_box,
            text="",
            font=ctk.CTkFont(size=12),
            anchor="e",
        )
        self.speed_label.pack(side="right")

        # 折疊日誌控制
        log_header = ctk.CTkFrame(self.bottom_frame, fg_color="transparent")
        log_header.pack(fill="x", padx=14, pady=(2, 2))

        self.toggle_log_btn = ctk.CTkButton(
            log_header,
            text="📝 顯示詳細記錄 ▼",
            width=120,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            hover_color="#374151",
            anchor="w",
            command=self._toggle_log_console,
        )
        self.toggle_log_btn.pack(side="left")

        self.log_console = ctk.CTkTextbox(self.bottom_frame, height=90, font=ctk.CTkFont(family="Consolas", size=11))
        # 預設不 pack log_console，點擊展開

    # ==================== 事件與邏輯處理 ====================

    def log(self, message: str):
        """將訊息推入日誌視窗與終端"""
        def _append():
            self.log_console.insert("end", message + "\n")
            self.log_console.see("end")
        self.after(0, _append)

    def _toggle_log_console(self):
        """展開或隱藏詳細日誌"""
        if self.log_console.winfo_ismapped():
            self.log_console.pack_forget()
            self.toggle_log_btn.configure(text="📝 顯示詳細記錄 ▼")
        else:
            self.log_console.pack(fill="x", padx=14, pady=(0, 8))
            self.toggle_log_btn.configure(text="📝 隱藏詳細記錄 ▲")

    def _toggle_theme(self):
        """切換深色 / 淺色外觀"""
        mode = self.theme_switch.get()
        ctk.set_appearance_mode(mode)
        self.config.set("theme", mode)

    def _on_url_typing(self, event=None):
        """當網址輸入框改變時，即時更新平台標籤色彩"""
        url = self.url_entry.get().strip()
        if not url:
            self.platform_badge.configure(text="🌐 待辨識平台", fg_color="#374151")
            return
        platform = DownloaderEngine.detect_platform(url)
        self.platform_badge.configure(
            text=f"{platform['icon']} {platform['name']}",
            fg_color=platform["color"],
        )
        # 動態調整字幕提示
        if not platform.get("has_subtitles", False):
            self.sub_check.configure(state="disabled")
            self.sub_hint_lbl.configure(text=f"({platform['name']} 通常不具備獨立字幕檔)")
        else:
            self.sub_check.configure(state="normal")
            self.sub_hint_lbl.configure(text="")

    def _paste_url(self):
        """從剪貼簿貼上網址並自動觸發分析"""
        try:
            clipboard_text = self.clipboard_get().strip()
            if clipboard_text:
                self.url_entry.delete(0, "end")
                self.url_entry.insert(0, clipboard_text)
                self._on_url_typing()
                self._start_analyze_thread()
        except Exception:
            pass

    def _clear_url(self):
        """清空網址與資訊卡片"""
        self.url_entry.delete(0, "end")
        self._on_url_typing()
        self.video_title_label.configure(text="請輸入影片網址並點選「分析網址」以取得影片資訊")
        self.uploader_label.configure(text="👤 作者 / 頻道: --")
        self.duration_label.configure(text="⏱️ 片長: --:--")
        self.thumb_label.configure(image=None, text="暫無縮圖")
        self.current_info = None

    def _on_mode_change(self, value):
        """切換影片 / 純音訊模式"""
        is_video = "影片" in value
        self.mode_var.set("video" if is_video else "audio")
        self.config.set("download_mode", self.mode_var.get())

        if is_video:
            self.quality_menu.configure(state="normal")
            self.keep_audio_check.configure(state="normal")
        else:
            self.quality_menu.configure(state="disabled")
            self.keep_audio_check.configure(state="disabled")

    def _on_quality_change(self, value):
        self.config.set("quality", value)

    def _on_keep_audio_toggle(self):
        self.config.set("keep_audio", self.keep_audio_var.get())

    def _on_sub_toggle(self):
        self.config.set("download_captions", self.sub_var.get())

    def _browse_dir(self):
        """選擇輸出路徑"""
        current = self.dir_entry.get().strip()
        chosen = filedialog.askdirectory(initialdir=current)
        if chosen:
            self.dir_entry.delete(0, "end")
            self.dir_entry.insert(0, chosen)
            self.config.set("output_dir", chosen)

    def _open_output_dir(self):
        """在檔案總管中開啟輸出路徑"""
        target = Path(self.dir_entry.get().strip())
        target.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(target))
        else:
            subprocess.run(["xdg-open", str(target)])

    # ==================== 非同步背景線程：解析 ====================

    def _start_analyze_thread(self):
        url = self.url_entry.get().strip()
        if not url or not url.startswith("http"):
            messagebox.showwarning("提示", "請先輸入有效的網址 (需包含 http:// 或 https://)")
            return

        self.analyze_btn.configure(state="disabled", text="解析中...")
        self.status_label.configure(text="⏳ 正在連線解析影片中繼資料...", text_color="#3B82F6")
        self.log(f"\n🔍 開始解析: {url}")

        threading.Thread(target=self._analyze_worker, args=(url,), daemon=True).start()

    def _analyze_worker(self, url: str):
        cookies = self.cookie_menu.get()
        try:
            info = self.engine.extract_info(url, cookies_browser=cookies)
            self.after(0, self._on_analyze_success, info)
        except Exception as e:
            self.after(0, self._on_analyze_error, str(e))

    def _on_analyze_success(self, info: Dict[str, Any]):
        self.current_info = info
        self.analyze_btn.configure(state="normal", text="🔍 分析網址")
        self.status_label.configure(text="✅ 解析完成，請設定下載選項後點選開始下載", text_color="#10B981")

        # 更新卡片內容
        self.video_title_label.configure(text=info.get("title", "未命名影片"))
        self.uploader_label.configure(text=f"👤 作者 / 頻道: {info.get('uploader')}")
        self.duration_label.configure(text=f"⏱️ 片長: {info.get('duration_str')}")

        platform = info.get("platform", {})
        self.platform_badge.configure(
            text=f"{platform.get('icon', '🎬')} {platform.get('name', '影片')}",
            fg_color=platform.get("color", "#2563EB"),
        )

        # 動態更新解析度清單
        resolutions = info.get("available_resolutions", [])
        if resolutions:
            res_items = ["最佳畫質 (Best)"] + [f"{h}p" for h in resolutions]
            self.quality_menu.configure(values=res_items)
            self.quality_menu.set("最佳畫質 (Best)")

        # 動態處理字幕
        subs = info.get("available_subtitles", [])
        if platform.get("has_subtitles", False) and subs:
            self.sub_check.configure(state="normal")
            self.sub_hint_lbl.configure(text=f"(共找到 {len(subs)} 種字幕語言)")
        else:
            self.sub_hint_lbl.configure(text="(該影片未偵測到獨立字幕)")

        # 非同步加載封面縮圖
        thumb_url = info.get("thumbnail")
        if thumb_url:
            threading.Thread(target=self._load_thumbnail_worker, args=(thumb_url,), daemon=True).start()

        self.log(f"✅ 解析成功: {info.get('title')} (長度: {info.get('duration_str')})")

    def _on_analyze_error(self, err_msg: str):
        self.analyze_btn.configure(state="normal", text="🔍 分析網址")
        self.status_label.configure(text=f"❌ 解析失敗: {err_msg[:40]}...", text_color="#EF4444")
        self.log(f"❌ 解析錯誤: {err_msg}")
        messagebox.showerror("解析失敗", f"無法讀取影片中繼資料：\n{err_msg}")

    def _load_thumbnail_worker(self, thumb_url: str):
        try:
            req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            pil_img = Image.open(io.BytesIO(data))
            pil_img = pil_img.resize((220, 124), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(220, 124))

            def _update_img():
                self.thumb_label.configure(image=ctk_img, text="")
            self.after(0, _update_img)
        except Exception as e:
            self.log(f"⚠️ 縮圖加載失敗: {e}")

    # ==================== 非同步背景線程：下載 ====================

    def _start_download_thread(self):
        if self.is_downloading:
            # 取消下載
            self.engine.cancel()
            self.status_label.configure(text="⏳ 正在取消下載作業...", text_color="#F59E0B")
            self.download_btn.configure(state="disabled")
            return

        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("提示", "請輸入要下載的影片網址！")
            return

        out_dir = self.dir_entry.get().strip()
        if not out_dir:
            messagebox.showwarning("提示", "請設定有效的輸出目錄！")
            return

        # 讀取介面選項
        mode = "video" if "影片" in self.mode_seg.get() else "audio"
        quality_str = self.quality_menu.get()
        if "Best" in quality_str or "最佳" in quality_str:
            quality = "best"
        else:
            match = re.search(r"(\d+)", quality_str)
            quality = match.group(1) if match else "best"

        keep_audio = self.keep_audio_var.get()
        download_subs = self.sub_var.get()
        cookies = self.cookie_menu.get()

        # 解析字幕偏好
        lang_sel = self.sub_lang_menu.get()
        if "繁體" in lang_sel:
            caption_langs = ["zh-TW", "zh-Hant", "zh-orig", "zh", "en"]
        elif "英文" in lang_sel:
            caption_langs = ["en-orig", "en", "zh-TW"]
        else:
            caption_langs = ["zh-TW", "zh-Hant", "zh-orig", "zh", "en-orig", "en", "ja"]

        self.is_downloading = True
        self.open_file_btn.configure(state="disabled")
        self.download_btn.configure(
            text="🛑 取消下載 (Cancel)",
            fg_color="#EF4444",
            hover_color="#DC2626",
        )
        self.progress_bar.set(0)
        self.status_label.configure(text="🚀 下載任務啟動中...", text_color="#3B82F6")
        self.speed_label.configure(text="")

        threading.Thread(
            target=self._download_worker,
            args=(
                url,
                Path(out_dir),
                mode,
                quality,
                keep_audio,
                download_subs,
                caption_langs,
                cookies,
            ),
            daemon=True,
        ).start()

    def _download_worker(
        self,
        url: str,
        out_dir: Path,
        mode: str,
        quality: str,
        keep_audio: bool,
        download_subs: bool,
        caption_langs: list,
        cookies: str,
    ):
        def progress_callback(d):
            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                fraction = (downloaded / total) if total > 0 else 0.0

                percent_str = d.get("_percent_str", f"{fraction * 100:.1f}%")
                speed_str = d.get("_speed_str", "-- KiB/s")
                eta_str = d.get("_eta_str", "--:--")

                def _update_ui():
                    self.progress_bar.set(fraction)
                    self.status_label.configure(
                        text=f"正在下載中: {percent_str}",
                        text_color="#3B82F6",
                    )
                    self.speed_label.configure(text=f"⚡ {speed_str} | ⏱️ 剩餘 {eta_str}")

                self.after(0, _update_ui)

            elif status == "finished":
                def _update_finish():
                    self.progress_bar.set(1.0)
                    self.status_label.configure(
                        text="⚙️ 下載完畢，正在合併/轉檔中...",
                        text_color="#F59E0B",
                    )
                self.after(0, _update_finish)

        try:
            res = self.engine.download(
                url=url,
                output_dir=out_dir,
                mode=mode,
                quality=quality,
                keep_audio=keep_audio,
                audio_format="mp3",
                download_captions=download_subs,
                caption_langs=caption_langs,
                cookies_browser=cookies,
                progress_callback=progress_callback,
                log_callback=self.log,
            )
            self.after(0, self._on_download_success, res)
        except Exception as e:
            self.after(0, self._on_download_error, str(e))

    def _on_download_success(self, res: Dict[str, Any]):
        self.is_downloading = False
        self.download_btn.configure(
            state="normal",
            text="🚀 開始下載 (Start Download)",
            fg_color="#10B981",
            hover_color="#059669",
        )
        self.progress_bar.set(1.0)
        self.status_label.configure(text="🎉 全部下載與轉檔程序已完成！", text_color="#10B981")
        self.speed_label.configure(text="✅ 完成")

        self.last_downloaded_file = res.get("file")
        if self.last_downloaded_file and Path(self.last_downloaded_file).is_file():
            self.open_file_btn.configure(state="normal")

        self.log(f"\n🎉 任務完成！檔案位置: {self.last_downloaded_file}")

    def _on_download_error(self, err_msg: str):
        self.is_downloading = False
        self.download_btn.configure(
            state="normal",
            text="🚀 開始下載 (Start Download)",
            fg_color="#10B981",
            hover_color="#059669",
        )
        self.status_label.configure(text=f"❌ 下載終止: {err_msg[:30]}", text_color="#EF4444")
        self.speed_label.configure(text="")
        self.log(f"\n❌ 下載失敗: {err_msg}")
        if "取消" not in err_msg:
            messagebox.showerror("下載錯誤", f"影音下載時發生錯誤：\n{err_msg}")

    def _play_downloaded_file(self):
        """呼叫預設播放器播放剛剛下載完成的影音檔案"""
        if self.last_downloaded_file and Path(self.last_downloaded_file).is_file():
            if sys.platform == "win32":
                os.startfile(self.last_downloaded_file)
            else:
                subprocess.run(["xdg-open", self.last_downloaded_file])


if __name__ == "__main__":
    app = VideoDownloaderApp()
    app.mainloop()
