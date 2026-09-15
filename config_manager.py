import json
from pathlib import Path
from typing import Any, Dict


class ConfigManager:
    """管理使用者設定檔 (config.json)"""

    def __init__(self, config_file: str = "config.json"):
        # 優先在程式所在目錄尋找或建立設定檔
        self.config_path = Path.cwd() / config_file
        self.defaults: Dict[str, Any] = {
            "output_dir": str(Path.cwd() / "Downloads"),
            "theme": "Dark",
            "quality": "best",
            "download_mode": "video",  # "video" or "audio"
            "keep_audio": False,
            "audio_format": "mp3",
            "audio_quality": "320",
            "download_captions": True,
            "caption_langs": ["zh-TW", "zh-Hant", "zh-orig", "zh", "en-orig", "en"],
            "browser_cookies": "none",
        }
        self.config: Dict[str, Any] = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """從硬碟讀取設定檔，若不存在則回傳預設值並儲存"""
        if self.config_path.is_file():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 合併預設值避免新版欄位缺失
                    merged = self.defaults.copy()
                    merged.update(data)
                    return merged
            except Exception as e:
                print(f"[Config] 讀取設定檔失敗，將重置為預設: {e}")
        self.save_config(self.defaults)
        return self.defaults.copy()

    def save_config(self, new_config: Dict[str, Any] = None) -> None:
        """儲存設定檔到硬碟"""
        if new_config:
            self.config = new_config
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] 儲存設定檔失敗: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, self.defaults.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self.config[key] = value
        self.save_config()
