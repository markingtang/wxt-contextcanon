"""Configuration loader for WXT ContextCanon.

Design rule: every value that used to be a hard-coded private constant is data.
Nothing in this file knows about any real person, device, host or path.

Configuration precedence (highest wins):
    1. environment variables (WXT_CONTEXTCANON_*)
    2. explicit config file (JSON)
    3. built-in DEFAULTS (all local, all synthetic)
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Dict, Optional

# All defaults are localhost / relative / synthetic. Safe to publish.
DEFAULTS: Dict[str, Dict[str, Any]] = {
    "profile": {
        "host": "127.0.0.1",
        "port": 8611,
        "database": "./data/profile.db",
        "data_dir": "./data",
    },
    "registry": {
        "device_id": "demo-device",
        "device_role": "primary",
        "registry_home": "./data/registry",
        "shared_store": "./data/registry/shared.db",
    },
    "deploy": {
        "project_name": "wxt-contextcanon",
        "compose_binary": "docker compose",
        "compose_files": ["deploy/docker/docker-compose.yml"],
        "services": ["contextcanon-api"],
        "lock_path": "./data/deploy.lock",
        "backup_command": "",
        "migration_test_command": "",
        "smoke_command": "",
        "deploy_command": "",
        "health_endpoints": [],
        "transport": "local-shell",
        "ssh": {"host_alias": "", "workdir": ""},
    },
    "server": {
        "name": "wxt-contextcanon",
        "version": "0.1.1",
    },
}

# Flat environment-variable overrides. Kept intentionally small and generic.
ENV_MAP = {
    "WXT_CONTEXTCANON_PROFILE_HOST": ("profile", "host"),
    "WXT_CONTEXTCANON_PROFILE_PORT": ("profile", "port"),
    "WXT_CONTEXTCANON_PROFILE_DATABASE": ("profile", "database"),
    "WXT_CONTEXTCANON_PROFILE_DATA_DIR": ("profile", "data_dir"),
    "WXT_CONTEXTCANON_REGISTRY_DEVICE_ID": ("registry", "device_id"),
    "WXT_CONTEXTCANON_REGISTRY_HOME": ("registry", "registry_home"),
    "WXT_CONTEXTCANON_REGISTRY_SHARED_STORE": ("registry", "shared_store"),
    "WXT_CONTEXTCANON_REGISTRY_DEVICE_ROLE": ("registry", "device_role"),
    "WXT_CONTEXTCANON_DEPLOY_PROJECT_NAME": ("deploy", "project_name"),
    "WXT_CONTEXTCANON_DEPLOY_LOCK_PATH": ("deploy", "lock_path"),
    "WXT_CONTEXTCANON_DEPLOY_TRANSPORT": ("deploy", "transport"),
}


def _coerce(section: str, key: str, value: Any) -> Any:
    default = DEFAULTS.get(section, {}).get(key)
    if isinstance(default, bool):
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int) and not isinstance(value, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    return value


def load_config(path: Optional[str] = None, root: Optional[str] = None) -> Dict[str, Any]:
    """Load config from defaults + optional JSON file + environment overrides."""
    cfg = deepcopy(DEFAULTS)

    if path:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise ValueError("config file must contain a JSON object")
        for section, values in raw.items():
            if section.startswith("_"):
                continue  # documentation keys such as "_comment"
            if not isinstance(values, dict):
                raise ValueError("config section '%s' must be an object" % section)
            cfg.setdefault(section, {})
            cfg[section].update(values)

    for env_name, (section, key) in ENV_MAP.items():
        if env_name in os.environ and os.environ[env_name] != "":
            cfg[section][key] = _coerce(section, key, os.environ[env_name])

    if root:
        resolve_paths(cfg, root)
    return cfg


def resolve_paths(cfg: Dict[str, Any], root: str) -> Dict[str, Any]:
    """Make relative paths absolute against the project root, and create dirs."""
    path_keys = {
        "profile": ("database", "data_dir"),
        "registry": ("registry_home", "shared_store"),
        "deploy": ("lock_path",),
    }
    for section, keys in path_keys.items():
        for key in keys:
            value = cfg.get(section, {}).get(key)
            if isinstance(value, str) and value:
                if not os.path.isabs(value):
                    cfg[section][key] = os.path.normpath(os.path.join(root, value))
    return cfg


def ensure_dirs(cfg: Dict[str, Any]) -> None:
    """Create data directories idempotently (safe on a clean machine)."""
    for path in (
        cfg["profile"]["data_dir"],
        cfg["registry"]["registry_home"],
        os.path.dirname(cfg["profile"]["database"]),
        os.path.dirname(cfg["registry"]["shared_store"]),
    ):
        if path:
            os.makedirs(path, exist_ok=True)


def write_example_config(path: str) -> None:
    """Write the shipped example config (used by `contextcanon config init`)."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(DEFAULTS, handle, indent=2, sort_keys=True)
        handle.write("\n")
