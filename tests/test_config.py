"""配置迁移单元测试"""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from config.config_manager import ConfigManager, LEGACY_REGION_MAP


def test_legacy_region_migration():
    tmp = tempfile.mkdtemp()
    try:
        cfg_path = os.path.join(tmp, "config.yaml")
        default_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config",
            "default_config.yaml",
        )
        with open(default_path, "r", encoding="utf-8") as f:
            base = yaml.safe_load(f)
        base["mouse_regions"] = {"m": {"x": 10, "y": 20}, "h": {"x": 30, "y": 40}}
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(base, f)

        cm = ConfigManager(config_path=cfg_path)
        assert cm.get_mouse_region("record")["x"] == 10
        assert cm.get_mouse_region("play")["x"] == 30
    finally:
        shutil.rmtree(tmp)
