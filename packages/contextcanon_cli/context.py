"""Shared CLI context: locate config, open services."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from contextcanon_config import ensure_dirs, load_config, resolve_paths
from profile_core import ProfileService, ProfileStore
from registry_core import RegistryService, RegistryStore


def repo_root() -> str:
    """<repo>/packages/contextcanon_cli -> <repo>"""
    assets = os.path.join(os.path.dirname(__file__), "_assets")
    if os.path.isdir(assets):
        return assets
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def default_config_candidates() -> list:
    root = repo_root()
    return [
        os.path.join(os.getcwd(), "contextcanon.json"),
        os.path.join(root, "contextcanon.json"),
        os.path.join(root, "examples", "configs", "contextcanon.example.json"),
    ]


class Context:
    def __init__(self, config_path: Optional[str] = None):
        path = config_path
        if not path:
            for candidate in default_config_candidates():
                if os.path.exists(candidate):
                    path = candidate
                    break
        self.config_path = path
        self.config: Dict[str, Any] = load_config(path)
        # Relative paths resolve against the current working directory, so a
        # user who clones into ~/tmp/contextcanon-demo gets their own ./data.
        resolve_paths(self.config, os.getcwd())
        ensure_dirs(self.config)
        self.root = repo_root()

    @property
    def profile_service(self) -> ProfileService:
        return ProfileService(ProfileStore(self.config["profile"]["database"]), actor="cli")

    @property
    def registry_service(self) -> RegistryService:
        service = RegistryService(
            RegistryStore(self.config["registry"]["shared_store"]),
            device_id=self.config["registry"]["device_id"],
            device_role=self.config["registry"]["device_role"],
        )
        service.ensure_device()
        return service

    def dump(self) -> Dict[str, Any]:
        return {
            "config_path": self.config_path or "(built-in defaults)",
            "cwd": os.getcwd(),
            "config": self.config,
        }
