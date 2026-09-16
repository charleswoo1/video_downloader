import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


APP_DIR_NAME = "SocialVideoDownloader"


def get_default_config_path() -> Path:
    """Return a stable per-user config path.

    Windows: %LOCALAPPDATA%/SocialVideoDownloader/config.json
    Other platforms: ~/.config/SocialVideoDownloader/config.json
    """
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_DIR_NAME / "config.json"


class ConfigManager:
    """管理使用者設定檔 (config.json)。"""

    def __init__(self, config_file: Optional[str] = None):
        # Explicit paths/names remain relative to cwd for tests and advanced use.
        # Normal app usage stores settings in the user's application-data folder.
        self.config_path = Path.cwd() / config_file if config_file else get_default_config_path()
        self.legacy_config_path = Path.cwd() / "config.json" if config_file is None else None

        self.defaults: Dict[str, Any] = {
            "output_dir": str(Path.home() / "Downloads"),
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

    def _read_config_file(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("config root must be a JSON object")
            merged = self.defaults.copy()
            merged.update(data)
            return merged
        except Exception as e:
            print(f"[Config] Failed to read config ({path}); using defaults: {e}")
            return None

    def load_config(self) -> Dict[str, Any]:
        if self.config_path.is_file():
            loaded = self._read_config_file(self.config_path)
            if loaded is not None:
                return loaded

        # v1.0.0 stored config.json in the process working directory.
        # Migrate once to the stable per-user location without deleting the old file.
        if self.legacy_config_path and self.legacy_config_path.is_file():
            loaded = self._read_config_file(self.legacy_config_path)
            if loaded is not None:
                self.config = loaded
                self.save_config()
                print(f"[Config] Migrated legacy config to: {self.config_path}")
                return loaded

        self.config = self.defaults.copy()
        self.save_config()
        return self.config.copy()

    def save_config(self, new_config: Optional[Dict[str, Any]] = None) -> None:
        if new_config is not None:
            self.config = new_config
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with self.config_path.open("w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] Failed to save config: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, self.defaults.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self.config[key] = value
        self.save_config()
