#!/usr/bin/env python
# coding: utf-8

import argparse
import configparser
import os

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
        raise ValueError(f"Error retrieving API key 	'{key}' from section '{section}': {e}. Check your config file.")

# Example of how to add argument parsing setup if needed for common arguments,
# but typically each script will define its own specific arguments.

if __name__ == "__main__":
    # Example usage (can be removed or kept for testing this module)
    try:
        # Create a dummy config.ini for testing if it doesn't exist
        dummy_config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "config")
        dummy_config_path = os.path.join(dummy_config_dir, "config.ini")
        if not os.path.exists(dummy_config_path):
            os.makedirs(dummy_config_dir, exist_ok=True)
            with open(dummy_config_path, "w") as f:
                f.write("[API_KEYS]\n")
                f.write("fmp_api_key = TEST_KEY\n")
            print(f"Created dummy config for testing: {dummy_config_path}")

        config = load_config(dummy_config_path)
        api_key = get_api_key(config)
        print(f"Successfully loaded FMP API Key: {api_key}")
        
        # Clean up dummy config if created by this test
        # if os.path.exists(dummy_config_path) and "TEST_KEY" in api_key:
        #     os.remove(dummy_config_path)
        #     print(f"Cleaned up dummy config: {dummy_config_path}")

    except Exception as e:
        print(f"Error in common_utils.py example: {e}")

