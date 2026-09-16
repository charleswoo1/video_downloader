# Social Video Downloader｜多平台社群影音下載器

[![CI](https://github.com/charleswoo1/video_downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/charleswoo1/video_downloader/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/charleswoo1/video_downloader?display_name=tag)](https://github.com/charleswoo1/video_downloader/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-blue)](https://github.com/charleswoo1/video_downloader)

一套給 Windows 使用者的桌面影音下載工具。介面使用 **CustomTkinter**，下載核心使用 **yt-dlp**，並整合 **FFmpeg / FFprobe** 與 **Node.js**，可處理常見社群平台的影片、音訊與字幕下載。

> 目前主要支援 Windows 10 / 11 x64。網站端規則經常變動，因此各平台實際可用功能仍取決於 yt-dlp、網站狀態、帳號權限與來源內容。

## 下載最新版

一般使用者不需要安裝 Python。

**Windows 單檔版：**

[下載最新版本 SocialVideoDownloader_Standalone.exe](https://github.com/charleswoo1/video_downloader/releases/latest/download/SocialVideoDownloader_Standalone.exe)

也可以前往 [Releases](https://github.com/charleswoo1/video_downloader/releases) 查看歷史版本、更新說明與 SHA-256 驗證碼。

### Windows SmartScreen 提示

目前 Release 執行檔尚未使用商業程式碼簽章憑證簽署，因此 Windows 可能顯示「未知發行者」或 SmartScreen 提示。若你是從本專案官方 GitHub Releases 下載，可搭配同一個 Release 內的 `SHA256SUMS.txt` 核對檔案雜湊。

---

## 主要功能

- 支援 **YouTube、Facebook、Instagram、Threads、X、TikTok、Bilibili**，以及其他 yt-dlp 可解析的網站。
- 可下載影片並選擇最佳畫質、1080p、720p、480p、360p。
- 可下載純音訊，或在下載影片後額外保留音訊檔。
- 可下載支援平台提供的字幕並轉成 SRT。
- 可選擇瀏覽器 Cookie，處理需要登入才能存取的內容。
- 深色 / 淺色介面。
- Windows Release 單檔版會隨附 FFmpeg、FFprobe 與 Node.js，不需要另外安裝執行環境。

## 支援概況

| 平台 | 影片 | 音訊 | 字幕 | 備註 |
| --- | :---: | :---: | :---: | --- |
| YouTube | ✅ | ✅ | ✅ | 支援 Shorts 與一般影片；部分內容可能需要 Cookie |
| Facebook | ✅ | ✅ | 視來源 | 公開貼文、Reels、Watch 依來源狀態而定 |
| Instagram | ✅ | ✅ | 視來源 | Reels / 貼文影片；登入限制依平台而定 |
| Threads | ✅ | ✅ | — | 使用專屬解析流程處理公開影片貼文 |
| X (Twitter) | ✅ | ✅ | 視來源 | 依貼文與媒體存取權限而定 |
| TikTok | ✅ | ✅ | 視來源 | 依來源與地區限制而定 |
| Bilibili | ✅ | ✅ | ✅ | 畫質與字幕依來源權限而定 |
| 其他網站 | 視 yt-dlp 支援 | 視來源 | 視來源 | 不保證所有網站皆可使用 |

本工具不提供 DRM 繞過功能，也無法保證私人、付費、區域限制或平台已禁止下載的內容可以取得。

---

## 使用方式

1. 啟動 `SocialVideoDownloader_Standalone.exe`。
2. 將影片網址貼到上方輸入框。
3. 點選 **「分析網址」**，確認標題、平台與可用資訊。
4. 選擇下載模式：
   - **影片（MP4）**
   - **純音訊（MP3）**
5. 視需要設定畫質、字幕、是否保留額外音訊，以及 Cookie 來源。
6. 選擇儲存資料夾後開始下載。
7. 完成後可直接從程式開啟下載位置。

### Cookie 使用注意事項

部分 YouTube 或其他平台內容需要登入狀態。程式可讀取瀏覽器 Cookie，但請注意：

- 建議只在自己的電腦上使用自己的帳號資料。
- 若瀏覽器 Cookie 資料庫被鎖定，可先完全關閉該瀏覽器再重試。
- **不要把 cookies.txt、瀏覽器 Cookie、帳號 Token 或登入資料上傳到 GitHub Issue。**
- Cookie 能否使用仍受網站登入狀態與平台限制影響。

---

## 從原始碼執行

### 需求

- Windows 10 / 11
- Python 3.10+
- FFmpeg + FFprobe
- Node.js
- Git（僅 clone 專案時需要）

### 安裝

```powershell
git clone https://github.com/charleswoo1/video_downloader.git
cd video_downloader

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

若系統 PATH 找不到 FFmpeg，可把 `ffmpeg.exe` 與 `ffprobe.exe` 放在程式可找到的位置，或在建置時使用 `FFMPEG_BIN_DIR` 指定它們所在的資料夾。

---

## 自行打包 Windows EXE

### 免安裝目錄版

```powershell
python build_exe.py
```

輸出位置：

```text
dist/SocialVideoDownloader/
```

### 單一 EXE

```powershell
python build_exe.py --onefile
```

輸出位置：

```text
dist/SocialVideoDownloader_Standalone.exe
```

打包程式會嘗試尋找本機的 FFmpeg、FFprobe 與 Node.js。若要明確指定 FFmpeg 所在目錄：

```powershell
$env:FFMPEG_BIN_DIR = "C:\path\to\ffmpeg\bin"
python build_exe.py --onefile
```

---

## GitHub Actions

本專案在 Public repository 上使用 GitHub-hosted **standard runners**。

### CI

`.github/workflows/ci.yml`

在以下情況執行 Windows 測試：

- Push 到 `main`
- 對 `main` 建立或更新 Pull Request

CI 會安裝依賴、確認 Node.js / FFmpeg 環境、執行 `test_suite.py`，並做一次單檔 EXE 打包 smoke test。

### 自動建立 GitHub Release

`.github/workflows/release.yml`

Release workflow 會：

1. 使用 `windows-latest` 建置。
2. 安裝 Python 依賴與 FFmpeg。
3. 執行單元測試。
4. 以 PyInstaller 建立 `SocialVideoDownloader_Standalone.exe`。
5. 把 FFmpeg、FFprobe 與 Node.js 一起打包。
6. 產生 `SHA256SUMS.txt`。
7. 建立 GitHub Release 並直接附上可下載 EXE。

有兩種觸發方式。

#### 方法 A：Git tag

```powershell
git tag v1.0.0
git push origin v1.0.0
```

任何 `v*` tag 都會啟動 Release workflow；正式版本建議使用 SemVer，例如 `v1.0.0`、`v1.1.0`。

#### 方法 B：GitHub 網頁手動發佈

1. 打開 repository 的 **Actions**。
2. 選擇 **Build & Release Windows EXE**。
3. 點 **Run workflow**。
4. 輸入版本，例如 `v1.0.0`。
5. workflow 成功後會自動建立對應的 GitHub Release。

---

## 專案結構

```text
.
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── release.yml
├── assets/
│   ├── icon.ico
│   └── icon.png
├── app.py
├── build_exe.py
├── config_manager.py
├── download_merge.py
├── downloader_engine.py
├── requirements.txt
├── test_suite.py
└── README.md
```

主要模組：

- `app.py`：桌面 GUI。
- `downloader_engine.py`：平台辨識、yt-dlp、FFmpeg、字幕、Cookie 與下載流程。
- `config_manager.py`：本機設定。
- `build_exe.py`：PyInstaller Windows 打包。
- `test_suite.py`：基礎單元測試。

---

## 常見問題

### 為什麼昨天可以下載，今天卻失敗？

影音網站會頻繁修改 API、驗證機制與播放器流程。先更新到最新 Release；若仍失敗，再確認 yt-dlp 是否已有相應修正。

### 為什麼 YouTube 要 Node.js？

新版 YouTube 的部分播放器驗證會使用 JavaScript challenge。專案會把 Node.js 提供給 yt-dlp 使用；官方 Release 單檔版會隨附 Node.js。

### 為什麼需要 FFmpeg / FFprobe？

高畫質影音通常分成獨立視訊與音訊串流。FFmpeg 負責合併、轉檔與音訊擷取；FFprobe 用於媒體資訊偵測。

### 可以下載付費或 DRM 影片嗎？

本專案不提供 DRM 繞過，也不以破解付費、私人或受保護內容為目的。

---

## 問題回報

若遇到問題，請在 GitHub Issues 提供：

- Windows 版本
- App / Release 版本
- 來源平台
- 可公開分享的網址（若可以）
- 錯誤訊息或畫面
- 是否有使用 Cookie

請先移除帳號、Cookie、Token、本機路徑與其他個人資訊。

## 使用與授權提醒

本工具僅應用於你有權下載、備份或處理的內容。請遵守來源網站服務條款、著作權法規與所在地法律。

目前 repository 尚未附加獨立 `LICENSE` 檔案；**公開可見不等同於授權任意修改或再散布原始碼**。若本專案之後要正式接受外部貢獻或允許再散布，建議另行加入明確的開源授權。
