import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def find_ffmpeg_binaries():
    """尋找 ffmpeg.exe 與 ffprobe.exe。

    解析順序：
    1. FFMPEG_BIN_DIR（供 CI / GitHub Actions 指定真實可執行檔目錄）
    2. 系統 PATH
    3. WinGet 預設安裝目錄
    """
    env_dir = os.environ.get("FFMPEG_BIN_DIR")
    if env_dir:
        env_path = Path(env_dir)
        env_ffmpeg = env_path / "ffmpeg.exe"
        env_ffprobe = env_path / "ffprobe.exe"
        if env_ffmpeg.is_file():
            ffmpeg_path = str(env_ffmpeg)
            ffprobe_path = str(env_ffprobe) if env_ffprobe.is_file() else None
            return ffmpeg_path, ffprobe_path

    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")

    if not ffmpeg_path or not ffprobe_path:
        winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        if winget_base.is_dir():
            if not ffmpeg_path:
                for p in winget_base.glob("**/ffmpeg.exe"):
                    ffmpeg_path = str(p)
                    break
            if not ffprobe_path:
                for p in winget_base.glob("**/ffprobe.exe"):
                    ffprobe_path = str(p)
                    break

    return ffmpeg_path, ffprobe_path


def find_node_binary():
    """尋找本機 node.exe"""
    node_path = shutil.which("node")
    if not node_path:
        winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        if winget_base.is_dir():
            for p in winget_base.glob("**/node.exe"):
                node_path = str(p)
                break
    if not node_path:
        try:
            import nodejs_wheel.executable as ne

            candidate = Path(ne.ROOT_DIR) / "node.exe"
            if candidate.is_file():
                node_path = str(candidate)
        except Exception:
            pass
    return node_path


def build(onefile: bool = False):
    print("==================================================")
    print("🔨 開始進行多平台社群影片下載器 EXE 打包")
    print(f"📦 打包模式: {'單一檔案 (--onefile)' if onefile else '免安裝目錄 (--onedir, 推薦)'}")
    print("==================================================")

    project_dir = Path(__file__).resolve().parent
    dist_dir = project_dir / "dist"
    icon_file = project_dir / "assets" / "icon.ico"

    ffmpeg_exe, ffprobe_exe = find_ffmpeg_binaries()
    if ffmpeg_exe:
        print(f"🎬 尋獲 FFmpeg: {ffmpeg_exe}")
    else:
        print("⚠️ 未找到 FFmpeg，部分影片合併與轉檔功能將無法使用。")

    if ffprobe_exe:
        print(f"🔎 尋獲 FFprobe: {ffprobe_exe}")
    else:
        print("⚠️ 未找到 FFprobe，部分媒體偵測流程可能受限。")

    node_exe = find_node_binary()
    if node_exe:
        print(f"⚡ 尋獲 Node.js: {node_exe}")
    else:
        print("ℹ️ 未找到本地 Node.js，部分 YouTube JavaScript challenge 解析可能受限。")

    app_name = "SocialVideoDownloader_Standalone" if onefile else "SocialVideoDownloader"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        f"--name={app_name}",
        "--noconsole",
        "-y",
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
        if ffprobe_exe and Path(ffprobe_exe).is_file():
            cmd.append(f"--add-binary={ffprobe_exe}{os.pathsep}.")
        if node_exe and Path(node_exe).is_file():
            cmd.append(f"--add-binary={node_exe}{os.pathsep}bin")
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
        if node_exe and Path(node_exe).is_file():
            shutil.copy2(node_exe, bin_dir / "node.exe")
            print(f"📋 已隨附複製: {bin_dir / 'node.exe'}")

        print("\n🎉 免安裝綠色版本打包完成！")
        print(f"📁 執行檔位置: {target_app_dir / 'SocialVideoDownloader.exe'}")
    else:
        print("\n🎉 單檔 EXE 打包完成！")
        print(f"📁 執行檔位置: {dist_dir / f'{app_name}.exe'}")

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="社群影片下載器 EXE 打包工具")
    parser.add_argument("--onefile", action="store_true", help="打包為單一 EXE 檔案")
    args = parser.parse_args()
    success = build(onefile=args.onefile)
    raise SystemExit(0 if success else 1)
