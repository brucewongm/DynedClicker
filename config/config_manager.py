"""
配置管理：读写 YAML，鼠标区域，旧键名迁移
"""
import os
from typing import Any, Dict, List

import yaml

# Dy 按钮区域（需求文档）
BUTTON_REGIONS = ("continue", "repeat", "record", "play")
# 旧版键名 → 新键名
LEGACY_REGION_MAP = {
    "m": "record",
    "h": "play",
    "brackets": "continue",
}


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_path: str = None):
        self.config_dir = os.path.dirname(os.path.abspath(__file__))
        self.project_root = os.path.dirname(self.config_dir)

        if config_path is None:
            self.config_path = os.path.join(self.config_dir, "config.yaml")
        elif not os.path.isabs(config_path):
            self.config_path = os.path.join(self.project_root, config_path)
        else:
            self.config_path = config_path

        self.default_config_path = os.path.join(self.config_dir, "default_config.yaml")
        self.config: Dict[str, Any] = {}
        self.load()

    def load(self):
        if not os.path.exists(self.config_path):
            self._create_default_config()

        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}

        self._migrate_legacy_regions()

    def _create_default_config(self):
        config_dir = os.path.dirname(self.config_path)
        if config_dir:
            os.makedirs(config_dir, exist_ok=True)
        if not os.path.exists(self.default_config_path):
            raise FileNotFoundError(f"默认配置不存在: {self.default_config_path}")
        with open(self.default_config_path, "r", encoding="utf-8") as f:
            default_config = yaml.safe_load(f)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(default_config, f, allow_unicode=True, default_flow_style=False)

    def _migrate_legacy_regions(self):
        regions = self.config.setdefault("mouse_regions", {})
        changed = False
        for old, new in LEGACY_REGION_MAP.items():
            if old in regions and new not in regions:
                regions[new] = regions[old]
                changed = True
        if changed:
            self.save()

    def save(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)

    def get(self, key: str, default=None):
        keys = key.split(".")
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    def set(self, key: str, value: Any):
        keys = key.split(".")
        config = self.config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
        self.save()

    def get_mouse_region(self, region_name: str) -> Dict[str, int]:
        return self.get(f"mouse_regions.{region_name}", {"x": 0, "y": 0})

    def update_mouse_region(self, region_name: str, x: int, y: int):
        self.set(f"mouse_regions.{region_name}", {"x": x, "y": y})

    def list_unconfigured_regions(self) -> List[str]:
        missing = []
        for name in BUTTON_REGIONS:
            c = self.get_mouse_region(name)
            if c.get("x", 0) == 0 and c.get("y", 0) == 0:
                missing.append(name)
        return missing
