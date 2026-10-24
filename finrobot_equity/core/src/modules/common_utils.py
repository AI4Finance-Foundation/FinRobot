#!/usr/bin/env python
# coding: utf-8

import argparse
import configparser
import os
from typing import Dict, Optional, Any

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.ini")

def load_config(config_path=None):
    """Loads configuration from an INI file."""
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}. Please create it from the template.")
    
    config = configparser.ConfigParser()
    config.read(config_path)
    return config

def get_api_key(config, section="API_KEYS", key="fmp_api_key"):
    """Retrieves a specific API key from the loaded configuration."""
    try:
        return config.get(section, key)
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        raise ValueError(f"Error retrieving API key '{key}' from section '{section}': {e}. Check your config file.")

def get_llm_config(config=None, service: Optional[str] = None, config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Retrieves LLM configuration from config file and environment variables.
    
    Supports: 'openai', 'nvidia', 'gemini'.
    
    Priority for service selection:
    1. Explicit `service` parameter
    2. Environment variables: `DEFAULT_SERVICE`, `LLM_SERVICE`, `DEFAULT_LLM_SERVICE`
    3. `default_service` or `llm_service` in [API_KEYS] section of config.ini
    4. Auto-detection based on available API keys (openai -> nvidia -> gemini)
    5. Default: 'openai'
    """
    if config is None:
        try:
            config = load_config(config_path)
        except Exception:
            config = None

    def _get_val(key: str, env_var: str, default: Optional[str] = None) -> Optional[str]:
        env_val = os.getenv(env_var)
        if env_val:
            return env_val.strip()
        if config and config.has_section("API_KEYS"):
            val = config.get("API_KEYS", key, fallback=default)
            return val.strip() if isinstance(val, str) else val
        return default

    # Determine default service
    selected_service = service
    if not selected_service:
        selected_service = os.getenv("DEFAULT_SERVICE") or os.getenv("LLM_SERVICE") or os.getenv("DEFAULT_LLM_SERVICE")
    if not selected_service and config and config.has_section("API_KEYS"):
        selected_service = (
            config.get("API_KEYS", "default_service", fallback=None) or
            config.get("API_KEYS", "llm_service", fallback=None) or
            config.get("API_KEYS", "default_provider", fallback=None)
        )

    services_config = {
        "openai": {
            "api_key": _get_val("openai_api_key", "OPENAI_API_KEY"),
            "base_url": _get_val("openai_base_url", "OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "model": _get_val("openai_model", "OPENAI_MODEL", "gpt-4.1-mini")
        },
        "nvidia": {
            "api_key": _get_val("nvidia_api_key", "NVIDIA_API_KEY"),
            "base_url": _get_val("nvidia_base_url", "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            "model": _get_val("nvidia_model", "NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
        },
        "gemini": {
            "api_key": _get_val("gemini_api_key", "GEMINI_API_KEY") or _get_val("gemini_api_key", "GOOGLE_API_KEY"),
            "base_url": _get_val("gemini_base_url", "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
            "model": _get_val("gemini_model", "GEMINI_MODEL", "gemini-2.5-flash")
        }
    }

    # Normalize service name
    if selected_service:
        selected_service = str(selected_service).strip().lower()
        if selected_service in ["google", "google_gemini", "gemini_ai"]:
            selected_service = "gemini"
        elif selected_service in ["nv", "nvidia_nim", "nim"]:
            selected_service = "nvidia"
    
    if not selected_service or selected_service not in services_config:
        # Auto-detect if valid key exists
        if services_config["openai"]["api_key"]:
            selected_service = "openai"
        elif services_config["nvidia"]["api_key"]:
            selected_service = "nvidia"
        elif services_config["gemini"]["api_key"]:
            selected_service = "gemini"
        else:
            selected_service = "openai"

    active_cfg = services_config.get(selected_service, services_config["openai"])
    return {
        "service": selected_service,
        "api_key": active_cfg["api_key"],
        "base_url": active_cfg["base_url"],
        "model": active_cfg["model"],
        "all_services": services_config
    }


if __name__ == "__main__":
    try:
        config = load_config()
        llm_cfg = get_llm_config(config)
        print(f"Loaded LLM Config: Service={llm_cfg['service']}, Model={llm_cfg['model']}")
    except Exception as e:
        print(f"Error in common_utils.py example: {e}")
