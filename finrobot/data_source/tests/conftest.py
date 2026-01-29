"""
Pytest configuration for data_source tests.

This conftest ensures the parent directory is in the path
before any imports happen through the package __init__.py.
"""
import sys
import os

# Add parent directory for direct module imports (before package __init__.py loads)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
