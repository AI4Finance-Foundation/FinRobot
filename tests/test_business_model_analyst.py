"""
Test suite for Business_Model_Analyst agent and BusinessModelAnalysisUtils.

Usage:
    python tests/test_business_model_analyst.py

Requirements:
    - API keys configured in config_api_keys
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

from finrobot.functional import BusinessModelAnalysisUtils
from finrobot.agents.agent_library import library


def test_agent_registered():
    """Test that Business_Model_Analyst is registered in agent library."""
    print("Testing agent registration...")
    assert "Business_Model_Analyst" in library, "Business_Model_Analyst not in library"
    agent = library["Business_Model_Analyst"]
    assert "profile" in agent, "Agent missing profile"
    assert "toolkits" in agent, "Agent missing toolkits"
    assert len(agent["toolkits"]) > 0, "Agent has no toolkits"
    print("  - Agent registered with profile and toolkits")
    print("  - Test PASSED")
    return True


def test_analyze_revenue_streams():
    """Test analyze_revenue_streams method."""
    print("\nTesting analyze_revenue_streams...")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        save_path = f.name

    try:
        result = BusinessModelAnalysisUtils.analyze_revenue_streams("AAPL", "2024", save_path)
        print(f"  Result: {result}")

        assert os.path.exists(save_path), "Output file not created"
        with open(save_path, 'r') as f:
            content = f.read()

        print(f"  File size: {len(content)} characters")
        assert len(content) > 500, "Output too small"
        assert "revenue" in content.lower(), "Should mention revenue"
        print("  - Test PASSED")
        return True
    except Exception as e:
        print(f"  - Test FAILED: {e}")
        return False
    finally:
        if os.path.exists(save_path):
            os.remove(save_path)


def test_analyze_unit_economics():
    """Test analyze_unit_economics method."""
    print("\nTesting analyze_unit_economics...")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        save_path = f.name

    try:
        result = BusinessModelAnalysisUtils.analyze_unit_economics("AAPL", "2024", save_path)
        print(f"  Result: {result}")

        assert os.path.exists(save_path), "Output file not created"
        with open(save_path, 'r') as f:
            content = f.read()

        print(f"  File size: {len(content)} characters")
        assert len(content) > 500, "Output too small"
        assert "margin" in content.lower(), "Should mention margin"
        print("  - Test PASSED")
        return True
    except Exception as e:
        print(f"  - Test FAILED: {e}")
        return False
    finally:
        if os.path.exists(save_path):
            os.remove(save_path)


def test_classify_business_model():
    """Test classify_business_model method."""
    print("\nTesting classify_business_model...")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        save_path = f.name

    try:
        result = BusinessModelAnalysisUtils.classify_business_model("AAPL", "2024", save_path)
        print(f"  Result: {result}")

        assert os.path.exists(save_path), "Output file not created"
        with open(save_path, 'r') as f:
            content = f.read()

        print(f"  File size: {len(content)} characters")
        assert len(content) > 500, "Output too small"
        # Check for Business Model Canvas building blocks
        assert "customer" in content.lower() or "value" in content.lower(), "Should mention BMC elements"
        print("  - Test PASSED")
        return True
    except Exception as e:
        print(f"  - Test FAILED: {e}")
        return False
    finally:
        if os.path.exists(save_path):
            os.remove(save_path)


def test_compare_operating_models():
    """Test compare_operating_models method."""
    print("\nTesting compare_operating_models...")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        save_path = f.name

    try:
        result = BusinessModelAnalysisUtils.compare_operating_models(
            "AAPL", "MSFT,GOOGL", "2024", save_path
        )
        print(f"  Result: {result}")

        assert os.path.exists(save_path), "Output file not created"
        with open(save_path, 'r') as f:
            content = f.read()

        print(f"  File size: {len(content)} characters")
        assert len(content) > 500, "Output too small"
        assert "aapl" in content.lower() or "msft" in content.lower(), "Should mention tickers"
        print("  - Test PASSED")
        return True
    except Exception as e:
        print(f"  - Test FAILED: {e}")
        return False
    finally:
        if os.path.exists(save_path):
            os.remove(save_path)


def test_analyze_revenue_quality():
    """Test analyze_revenue_quality method."""
    print("\nTesting analyze_revenue_quality...")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        save_path = f.name

    try:
        result = BusinessModelAnalysisUtils.analyze_revenue_quality("AAPL", "2024", save_path)
        print(f"  Result: {result}")

        assert os.path.exists(save_path), "Output file not created"
        with open(save_path, 'r') as f:
            content = f.read()

        print(f"  File size: {len(content)} characters")
        assert len(content) > 500, "Output too small"
        assert "revenue" in content.lower(), "Should mention revenue"
        print("  - Test PASSED")
        return True
    except Exception as e:
        print(f"  - Test FAILED: {e}")
        return False
    finally:
        if os.path.exists(save_path):
            os.remove(save_path)


def run_all_tests():
    """Run all tests and report results."""
    print("=" * 60)
    print("Business Model Analyst Test Suite")
    print("=" * 60)

    tests = [
        ("Agent Registration", test_agent_registered),
        ("Revenue Streams Analysis", test_analyze_revenue_streams),
        ("Unit Economics Analysis", test_analyze_unit_economics),
        ("Business Model Classification", test_classify_business_model),
        ("Operating Model Comparison", test_compare_operating_models),
        ("Revenue Quality Analysis", test_analyze_revenue_quality),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n{name} - EXCEPTION: {e}")
            results.append((name, False))

    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "PASSED" if result else "FAILED"
        print(f"  {name}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")
    print("=" * 60)

    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
