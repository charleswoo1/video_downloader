# 🎬 多平台社群影片下載器 (Social Video Downloader)

一套專為 Windows 打造的現代化多平台社群影音下載桌面應用程式，採用 **CustomTkinter** 打造精緻深色 UI 介面，底層整合 **yt-dlp** 與 **FFmpeg**，支援一鍵智慧分析與下載各大主流社群平台的影片、獨立音訊與字幕。

---

## ✨ 核心特色

- 🌐 **多平台智慧支援**：支援 **YouTube**、**Facebook**、**Instagram**、**X (Twitter)**、**TikTok**、**Bilibili** 及千種通用網站。
- 🔍 **一鍵智慧分析**：貼上網址自動識別所屬社群平台，非同步抓取影片標題、時長、作者與高畫質縮圖。
- 🎬 **多畫質彈性選擇**：支援最高畫質 (4K/1080p/720p/480p) 影片下載，並自動透過 FFmpeg 無損/高品質合併為 MP4。
- 🎵 **獨立高音質音訊**：可直接下載 MP3 純音樂，或在下載影片的同時額外抽取一份 MP3。
- 📝 **SRT 字幕下載**：支援 YouTube / Bilibili 多語言字幕下載（自動擴充原生 `-orig` 代碼，避開 YouTube 429 速率限制），並自動轉為標準 `.srt` 檔案。
- ⚡ **極速非同步處理**：所有解析與下載均在背景執行緒運作，介面流暢不卡死，具備即時進度條、傳輸速度、預估時間與日誌控制台。
- 📦 **本地 EXE 打包**：提供一鍵本地打包工具，隨附完整 FFmpeg 執行檔，打包後免安裝環境即可在任何 Windows 電腦上「雙擊即用」。

---

## 🚀 支援社群軟體一覽表

| 社群平台 | 影片下載 (MP4) | 音訊擷取 (MP3) | 字幕下載 (SRT) | 備註說明 |
| :--- | :---: | :---: | :---: | :--- |
| **YouTube** | ✅ 最高畫質合併 | ✅ 支援抽取 | ✅ 繁中/英/原生字幕 | 支援 Shorts 與長影片 |
| **Facebook** | ✅ 支援 HD/SD | ✅ 支援抽取 | ❌ (多無獨立字幕) | 支援公開貼文、Reels、Watch |
| **Instagram** | ✅ 支援最佳畫質 | ✅ 支援抽取 | ❌ (無獨立字幕) | 支援貼文影片、Reels |
| **X (Twitter)** | ✅ 支援多解析度 | ✅ 支援抽取 | ❌ (無獨立字幕) | 支援推文內嵌影片 |
| **TikTok** | ✅ 垂直高畫質 | ✅ 支援原聲抽取 | ⚠️ 視來源而定 | 支援短影音直接下載 |
| **Bilibili** | ✅ 支援高畫質 | ✅ 支援抽取 | ✅ 支援字幕與轉檔 | 支援各大分 P 影片 |
| **通用模式** | ✅ 支援 | ✅ 支援 | 視該平台而定 | 支援 Vimeo, Twitch, Reddit 等千種網站 |

---

## 🛠️ 開發與環境安裝

### 系統需求
- Windows 10 / 11
- Python 3.10+
- FFmpeg（本地開發需配置環境變數，或置於 `bin/` 目錄）

### 安裝依賴套件
```bash
pip install -r requirements.txt
```

### 啟動應用程式
```bash
python app.py
```

---

## 🔨 本地 EXE 打包指南 (無需 GitHub Actions)

本專案完全採用**本地端打包方案**，無需且不使用任何 GitHub Actions 雲端工作流，安全且完全掌控建置過程。

### 1. 免安裝綠色目錄版 (推薦，秒開且易維護)
```bash
python build_exe.py
```
- 打包產物位於：`dist/SocialVideoDownloader/`
- 程式會自動將本機 `ffmpeg.exe` 隨附複製至輸出目錄的 `bin/` 資料夾內，使用者雙擊 `SocialVideoDownloader.exe` 即可獨立運行。

### 2. 單一單檔 EXE 版
```bash
python build_exe.py --onefile
```
- 打包產物位於：`dist/SocialVideoDownloader.exe`
- 將所有依賴與 FFmpeg 打包進單一執行檔。

---

## 📁 專案架構說明

```
├── app.py                  # CustomTkinter GUI 視覺主程式
├── downloader_engine.py    # 多平台核心下載引擎 (yt-dlp + FFmpeg 整合封裝)
├── config_manager.py       # 本地使用者設定管理模組 (config.json)
├── build_exe.py            # 本地 PyInstaller 自動化編譯與依賴隨附腳本
├── test_suite.py           # 自動化單元測試腳本
├── assets/                 # 應用程式 Logo 圖示 (icon.ico / icon.png)
├── requirements.txt        # Python 依賴清單
├── .gitignore              # Git 忽略設定 (過濾影音大檔與建置暫存)
└── README.md               # 專案中文說明文件
```

---

## 📄 開源協議與聲明
本專案僅供個人學術研究、離線備份與合法教學用途使用。請遵守各大社群平台之服務條款與相關著作權規範。
