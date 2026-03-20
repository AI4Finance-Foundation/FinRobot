#!/usr/bin/env python3
"""
Start the FinRobot Equity Research Web Application

This script starts the FastAPI web application for equity research analysis.

Usage:
    python run_web_app.py
    
    Or from the FinRobot root directory:
    python -m finrobot_equity.run_web_app
"""

import sys
import os
import uvicorn

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def run_web_app(host: str = "127.0.0.1", port: int = 8001, reload: bool = True):
    """
    Start the web application
    
    Args:
        host: Host address to bind to
        port: Port number to bind to
        reload: Whether to enable auto-reload on code changes
    """
    print("=" * 60)
    print("FinRobot Equity Research Web Application")
    print("=" * 60)
    print(f"\nStarting web application...")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Access the application at: http://{host}:{port}")
    print("\nPress Ctrl+C to stop the server\n")
    
    try:
        # Use import string for uvicorn so reload mode works
        # This allows uvicorn to reload the app when code changes
        uvicorn.run(
            "finrobot_equity.web_app.main:app",
            host=host,
            port=port,
            reload=reload,
            log_level="info"
        )
    except ImportError as e:
        print(f"\nError: Could not import web application")
        print(f"Details: {e}")
        print("\nMake sure you have installed the required dependencies:")
        print("  pip install finrobot[equity]")
        sys.exit(1)
    except Exception as e:
        print(f"\nError starting web application: {e}")
        sys.exit(1)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Start the FinRobot Equity Research Web Application"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port number to bind to (default: 8001)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=True,
        help="Enable auto-reload on code changes (default: enabled)"
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable auto-reload on code changes"
    )
    
    args = parser.parse_args()
    
    run_web_app(
        host=args.host,
        port=args.port,
        reload=not args.no_reload
    )
