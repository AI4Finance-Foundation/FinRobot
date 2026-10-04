#!/usr/bin/env python
# coding: utf-8
"""
Unit tests for multi-service LLM configuration and generation (OpenAI, NVIDIA, Gemini).
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add src to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from modules.common_utils import load_config, get_llm_config
from modules.text_generator_agents import generate_text_section, _get_fallback_text, _call_gemini_rest_api
from modules.enhanced_text_generator import EnhancedTextGenerator, create_enhanced_text_generator


class TestLLMServiceConfiguration(unittest.TestCase):
    
    def setUp(self):
        self.config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.ini")
        self.config = load_config(self.config_path)

    def test_default_service_from_config(self):
        """Test default_service loading from config.ini"""
        llm_cfg = get_llm_config(self.config)
        self.assertIn(llm_cfg["service"], ["openai", "nvidia", "gemini"])
        self.assertIsNotNone(llm_cfg["model"])

    def test_openai_service_resolution(self):
        """Test explicit OpenAI service configuration resolution"""
        llm_cfg = get_llm_config(self.config, service="openai")
        self.assertEqual(llm_cfg["service"], "openai")
        self.assertIsNotNone(llm_cfg["api_key"])
        self.assertIn("gpt", llm_cfg["model"].lower())
        self.assertIn("openai.com", llm_cfg["base_url"])

    def test_nvidia_service_resolution(self):
        """Test explicit NVIDIA service configuration resolution"""
        llm_cfg = get_llm_config(self.config, service="nvidia")
        self.assertEqual(llm_cfg["service"], "nvidia")
        self.assertIsNotNone(llm_cfg["api_key"])
        self.assertIn("nvidia", llm_cfg["model"].lower())
        self.assertIn("nvidia.com", llm_cfg["base_url"])

    def test_gemini_service_resolution(self):
        """Test explicit Gemini service configuration resolution"""
        llm_cfg = get_llm_config(self.config, service="gemini")
        self.assertEqual(llm_cfg["service"], "gemini")
        self.assertIsNotNone(llm_cfg["api_key"])
        self.assertIn("gemini", llm_cfg["model"].lower())
        self.assertIn("googleapis.com", llm_cfg["base_url"])

    def test_env_var_override(self):
        """Test DEFAULT_SERVICE environment variable override"""
        with patch.dict(os.environ, {"DEFAULT_SERVICE": "gemini"}):
            llm_cfg = get_llm_config(self.config)
            self.assertEqual(llm_cfg["service"], "gemini")

        with patch.dict(os.environ, {"DEFAULT_SERVICE": "nvidia"}):
            llm_cfg = get_llm_config(self.config)
            self.assertEqual(llm_cfg["service"], "nvidia")

    def test_fallback_text_generation(self):
        """Test fallback text generation when API key is missing or invalid"""
        for service in ["openai", "nvidia", "gemini"]:
            text = generate_text_section(
                data={},
                prompt_type="tagline",
                api_key=None,
                company_name="Acme Corp",
                company_ticker="ACME",
                service=service
            )
            self.assertIn("Acme Corp", text)
            self.assertGreater(len(text), 20)

    def test_enhanced_text_generator_services(self):
        """Test EnhancedTextGenerator handles all services properly"""
        gen_openai = create_enhanced_text_generator(api_key="sk-test", service="openai")
        self.assertEqual(gen_openai.service, "openai")

        gen_nvidia = create_enhanced_text_generator(api_key="nv-test", service="nvidia")
        self.assertEqual(gen_nvidia.service, "nvidia")

        gen_gemini = create_enhanced_text_generator(api_key="gem-test", service="gemini")
        self.assertEqual(gen_gemini.service, "gemini")


if __name__ == "__main__":
    unittest.main()
