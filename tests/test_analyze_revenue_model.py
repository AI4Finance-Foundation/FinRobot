"""
Simple end-to-end test for analyze_revenue_model() method.

Usage:
    python tests/test_analyze_revenue_model.py

Requirements:
    - API keys configured in environment or config files
    - Internet connection for SEC/FMP API calls
"""

import os
import sys
import tempfile

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load API keys from config file
from finrobot.utils import register_keys_from_json
register_keys_from_json("config_api_keys")

from finrobot.functional.analyzer import ReportAnalysisUtils


def test_analyze_revenue_model():
    """Test analyze_revenue_model with AAPL for FY2024."""

    # Create temp file for output
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        save_path = f.name

    ticker = "AAPL"
    fyear = "2024"

    print(f"Testing analyze_revenue_model({ticker}, {fyear}, {save_path})")
    print("-" * 60)

    try:
        # Call the method
        result = ReportAnalysisUtils.analyze_revenue_model(ticker, fyear, save_path)
        print(f"Result: {result}")

        # Verify file was created
        assert os.path.exists(save_path), f"Output file not created: {save_path}"

        # Read and display content
        with open(save_path, 'r') as f:
            content = f.read()

        print(f"\nFile size: {len(content)} characters")
        print(f"\nFirst 2000 characters of output:")
        print("-" * 60)
        print(content[:2000])
        print("-" * 60)

        # Basic validation
        assert len(content) > 100, "Output file is too small"
        assert "revenue" in content.lower() or "Revenue" in content, "Output should mention revenue"

        print("\nTest PASSED")
        return True

    except Exception as e:
        print(f"\nTest FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Cleanup
        if os.path.exists(save_path):
            os.remove(save_path)
            print(f"\nCleaned up temp file: {save_path}")


if __name__ == "__main__":
    success = test_analyze_revenue_model()
    sys.exit(0 if success else 1)
