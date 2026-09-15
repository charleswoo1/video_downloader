import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_ffmpeg_binaries():
    """尋找本機 ffmpeg.exe 與 ffprobe.exe"""
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")

    if not ffmpeg_path:
        # 搜尋使用者 winget 預設路徑
        winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        for p in winget_base.glob("**/ffmpeg.exe"):
            ffmpeg_path = str(p)
            break
        for p in winget_base.glob("**/ffprobe.exe"):
            ffprobe_path = str(p)
            break

    return ffmpeg_path, ffprobe_path


def build(onefile: bool = False):
    print("==================================================")
    print("🔨 開始進行多平台社群影片下載器 本地 EXE 打包")
    print(f"📦 打包模式: {'單一檔案 (--onefile)' if onefile else '免安裝目錄 (--onedir, 推薦)'}")
    print("==================================================")

    project_dir = Path(__file__).resolve().parent
    dist_dir = project_dir / "dist"
    build_dir = project_dir / "build"
    icon_file = project_dir / "assets" / "icon.ico"

    ffmpeg_exe, ffprobe_exe = find_ffmpeg_binaries()
    if ffmpeg_exe:
        print(f"🎬 尋獲 FFmpeg: {ffmpeg_exe}")
    else:
        print("⚠️ 未找到 FFmpeg，建議打包後手動將 ffmpeg.exe 複製進輸出資料夾。")

    app_name = "SocialVideoDownloader_Standalone" if onefile else "SocialVideoDownloader"

    # 基本 PyInstaller 參數
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        f"--name={app_name}",
        "--noconsole",
        "--clean",
        "--collect-all=customtkinter",
        "--collect-all=yt_dlp",
        "--collect-all=PIL",
        f"--add-data={project_dir / 'assets'}{os.pathsep}assets",
    ]

    if icon_file.is_file():
        cmd.append(f"--icon={icon_file}")

    if onefile:
        cmd.append("--onefile")
        if ffmpeg_exe and Path(ffmpeg_exe).is_file():
            cmd.append(f"--add-binary={ffmpeg_exe}{os.pathsep}.")
    else:
        cmd.append("--onedir")

    cmd.append(str(project_dir / "app.py"))

    print("\n🚀 正在執行 PyInstaller 編譯命令...")
    print(" ".join(cmd))
    res = subprocess.run(cmd, cwd=str(project_dir))

    if res.returncode != 0:
        print(f"\n❌ 打包失敗，PyInstaller 回傳代碼: {res.returncode}")
        return False

    print("\n✅ PyInstaller 主程式編譯完成！")

    # 若是 onedir 模式，將 ffmpeg 與 ffprobe 複製進輸出目錄
    if not onefile:
        target_app_dir = dist_dir / "SocialVideoDownloader"
        bin_dir = target_app_dir / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)

        if ffmpeg_exe and Path(ffmpeg_exe).is_file():
            shutil.copy2(ffmpeg_exe, bin_dir / "ffmpeg.exe")
            print(f"📋 已隨附複製: {bin_dir / 'ffmpeg.exe'}")
        if ffprobe_exe and Path(ffprobe_exe).is_file():
            shutil.copy2(ffprobe_exe, bin_dir / "ffprobe.exe")
            print(f"📋 已隨附複製: {bin_dir / 'ffprobe.exe'}")

        print(f"\n🎉 免安裝綠色版本打包完成！")
        print(f"📁 執行檔位置: {target_app_dir / 'SocialVideoDownloader.exe'}")
    else:
        print(f"\n🎉 單檔 EXE 打包完成！")
        print(f"📁 執行檔位置: {dist_dir / f'{app_name}.exe'}")

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="社群影片下載器 EXE 打包工具")
    parser.add_argument("--onefile", action="store_true", help="打包為單一 EXE 檔案")
    args = parser.parse_args()
    build(onefile=args.onefile)
