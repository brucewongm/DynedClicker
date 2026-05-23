"""YAML 配置读写"""
from __future__ import annotations

import copy
import os
from datetime import datetime, timedelta
from typing import Any, Dict

import yaml


class ConfigManager:
    def __init__(self, config_path: str | None = None):
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

    def load(self) -> None:
        if not os.path.exists(self.config_path):
            self._create_default_config()
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}
        self._ensure_auto_exit_default()
        try:
            from core.workflow_coords import ensure_reference_coord_defaults

            if ensure_reference_coord_defaults(self):
                self.save()
        except Exception:
            pass

    def _create_default_config(self) -> None:
        os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
        if not os.path.exists(self.default_config_path):
            raise FileNotFoundError(f"默认配置不存在: {self.default_config_path}")
        with open(self.default_config_path, "r", encoding="utf-8") as f:
            default_config = yaml.safe_load(f)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(default_config, f, allow_unicode=True, default_flow_style=False)

    def _ensure_auto_exit_default(self) -> None:
        ae = self.config.setdefault("auto_exit", {})
        if not isinstance(ae, dict):
            return
        if ae.get("at") in (None, ""):
            default_at = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
            ae.setdefault("enabled", True)
            ae["at"] = default_at

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(copy.deepcopy(self.config), f, allow_unicode=True, default_flow_style=False)

    def reload(self) -> None:
        self.load()

    def get(self, key: str, default=None):
        parts = key.split(".")
        cur: Any = self.config
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        return cur

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        cur = self.config
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value
