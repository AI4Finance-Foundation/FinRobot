#!/bin/bash

################################################################################
# FinRobot Equity Research - Complete Deployment Script
# 
# This script manages the complete FinRobot Equity Research module including:
# - Virtual environment setup
# - Dependency installation (core + equity + web)
# - Web application startup
# - Process management
#
# Usage:
#   ./deploy.sh start      - Start the web application
#   ./deploy.sh stop       - Stop the application
#   ./deploy.sh status     - Check application status
#   ./deploy.sh restart    - Restart the application
#   ./deploy.sh install    - Install/update dependencies only
#   ./deploy.sh help       - Show this help message
#
################################################################################

set -e

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/venv"
PID_FILE="${SCRIPT_DIR}/.app.pid"
LOG_DIR="${SCRIPT_DIR}/finrobot_equity/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/app.log"
#REQUIREMENTS_CORE="${SCRIPT_DIR}/requirements.txt"
REQUIREMENTS_EQUITY="${SCRIPT_DIR}/requirements-equity.txt"
REQUIREMENTS_WEB="${SCRIPT_DIR}/web_requirements.txt"

# Web app configuration
WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-8001}"
WEB_RELOAD="${WEB_RELOAD:-true}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# Utility Functions
# ============================================================================

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1"
}

print_header() {
    echo ""
    echo "================================================================================"
    echo "  $1"
    echo "================================================================================"
    echo ""
}

# ============================================================================
# Python Detection
# ============================================================================

detect_python() {
    # Try to find Python 3.10+, 3.9 in order
    for python_cmd in python3.12 python3.11 python3.10 python3.9 python3 python; do
        if command -v "$python_cmd" &> /dev/null; then
            # Check if it's Python 3.9 or higher
            version=$("$python_cmd" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null)
            if [ -z "$version" ]; then
                continue
            fi
            
            major=$(echo "$version" | cut -d. -f1)
            minor=$(echo "$version" | cut -d. -f2)
            
            # Ensure major and minor are numbers
            if ! [[ "$major" =~ ^[0-9]+$ ]] || ! [[ "$minor" =~ ^[0-9]+$ ]]; then
                continue
            fi
            
            if [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]; then
                # Output to stderr for messages, stdout for the result
                print_info "Found Python: $python_cmd (version: $version)" >&2
                echo "$python_cmd"
                return 0
            fi
        fi
    done
    
    print_error "Python 3.9 or higher is required but not found" >&2
    print_error "Please install Python 3.9+ and try again" >&2
    exit 1
}

# ============================================================================
# Virtual Environment Management
# ============================================================================

create_venv() {
    if [ -d "$VENV_DIR" ]; then
        print_info "Virtual environment already exists at $VENV_DIR"
        return 0
    fi
    
    print_info "Creating virtual environment at $VENV_DIR..."
    
    PYTHON_CMD=$(detect_python)
    
    # Verify the Python command was found
    if [ -z "$PYTHON_CMD" ]; then
        print_error "Failed to detect Python"
        exit 1
    fi
    
    # Verify the Python command exists
    if ! command -v "$PYTHON_CMD" &> /dev/null; then
        print_error "Python command not found: $PYTHON_CMD"
        exit 1
    fi
    
    if ! "$PYTHON_CMD" -m venv "$VENV_DIR"; then
        print_error "Failed to create virtual environment"
        print_error "Command: $PYTHON_CMD -m venv $VENV_DIR"
        exit 1
    fi
    
    print_info "Virtual environment created successfully"
}

activate_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        print_error "Virtual environment not found at $VENV_DIR"
        exit 1
    fi
    
    # Source the activation script (try both Unix and macOS paths)
    if [ -f "$VENV_DIR/bin/activate" ]; then
        source "$VENV_DIR/bin/activate"
    elif [ -f "$VENV_DIR/Scripts/activate" ]; then
        source "$VENV_DIR/Scripts/activate"
    else
        print_error "Failed to activate virtual environment"
        print_error "Activation script not found at $VENV_DIR/bin/activate"
        exit 1
    fi
}

# ============================================================================
# Dependency Installation
# ============================================================================

install_deps() {
    print_header "Installing Dependencies"
    
    create_venv
    activate_venv
    
    print_info "Upgrading pip, setuptools, and wheel..."
    pip install --upgrade pip setuptools wheel 2>&1 | tail -5
    
    # # Install core dependencies
    # if [ -f "$REQUIREMENTS_CORE" ]; then
    #     print_info "Installing core dependencies from $REQUIREMENTS_CORE..."
    #     pip install -r "$REQUIREMENTS_CORE" 2>&1 | tail -5
    # fi
    
    # Install equity research dependencies
    if [ -f "$REQUIREMENTS_EQUITY" ]; then
        print_info "Installing equity research dependencies from $REQUIREMENTS_EQUITY..."
        pip install -r "$REQUIREMENTS_EQUITY" 2>&1 | tail -5
    fi
    
    # Install web application dependencies
    if [ -f "$REQUIREMENTS_WEB" ]; then
        print_info "Installing web application dependencies from $REQUIREMENTS_WEB..."
        pip install -r "$REQUIREMENTS_WEB" 2>&1 | tail -5
    fi
    
    # Note: finrobot_equity is a local module, no need to install separately
    
    print_info "All dependencies installed successfully"
}

# ============================================================================
# Application Management
# ============================================================================

start_app() {
    print_header "Starting FinRobot Equity Research Web Application"
    
    # Check if already running
    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        if kill -0 "$OLD_PID" 2>/dev/null; then
            print_warning "Application is already running (PID: $OLD_PID)"
            print_info "Access the application at: http://$WEB_HOST:$WEB_PORT"
            return 0
        else
            print_debug "Removing stale PID file"
            rm -f "$PID_FILE"
        fi
    fi
    
    # Install dependencies if needed
    if [ ! -d "$VENV_DIR" ]; then
        print_info "Virtual environment not found, installing dependencies..."
        install_deps
    fi
    
    # Activate virtual environment
    activate_venv
    
    # Verify required modules
    print_info "Verifying required modules..."
    python -c "import fastapi; import uvicorn" 2>/dev/null || {
        print_warning "Some modules are missing, reinstalling dependencies..."
        install_deps
        activate_venv
    }
    
    # Start the web application in background
    print_info "Starting web application..."
    print_info "Host: $WEB_HOST"
    print_info "Port: $WEB_PORT"
    print_info "Logs: $LOG_FILE"
    
    # Determine reload flag
    RELOAD_FLAG=""
    if [ "$WEB_RELOAD" = "false" ] || [ "$WEB_RELOAD" = "no" ]; then
        RELOAD_FLAG="--no-reload"
    else
        RELOAD_FLAG="--reload"
    fi
    
    # Start the application
    # Add current directory to PYTHONPATH so finrobot_equity can be imported
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    
    nohup python "$SCRIPT_DIR/run_web_app.py" \
        --host "$WEB_HOST" \
        --port "$WEB_PORT" \
        $RELOAD_FLAG \
        > "$LOG_FILE" 2>&1 &
    
    APP_PID=$!
    echo "$APP_PID" > "$PID_FILE"
    
    # Wait a moment for the app to start
    sleep 2
    
    # Check if the process is still running
    if kill -0 "$APP_PID" 2>/dev/null; then
        print_info "Application started successfully (PID: $APP_PID)"
        print_info ""
        print_info "Access the application at:"
        print_info "  http://$WEB_HOST:$WEB_PORT"
        print_info ""
        print_info "View logs with:"
        print_info "  tail -f $LOG_FILE"
        print_info ""
        return 0
    else
        print_error "Failed to start application"
        print_error "Check logs: $LOG_FILE"
        cat "$LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
}

stop_app() {
    print_header "Stopping FinRobot Equity Research Web Application"
    
    if [ ! -f "$PID_FILE" ]; then
        print_warning "Application is not running (no PID file found)"
        return 0
    fi
    
    PID=$(cat "$PID_FILE")
    
    if ! kill -0 "$PID" 2>/dev/null; then
        print_warning "Process $PID is not running"
        rm -f "$PID_FILE"
        return 0
    fi
    
    print_info "Stopping application (PID: $PID)..."
    
    # Try graceful shutdown
    kill -TERM "$PID" 2>/dev/null || true
    
    # Wait for graceful shutdown
    for i in {1..10}; do
        if ! kill -0 "$PID" 2>/dev/null; then
            print_info "Application stopped gracefully"
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done
    
    # Force kill if still running
    print_warning "Application did not stop gracefully, forcing shutdown..."
    kill -9 "$PID" 2>/dev/null || true
    
    rm -f "$PID_FILE"
    print_info "Application stopped"
}

check_status() {
    print_header "FinRobot Equity Research Application Status"
    
    if [ ! -f "$PID_FILE" ]; then
        print_warning "Application is not running"
        return 1
    fi
    
    PID=$(cat "$PID_FILE")
    
    if kill -0 "$PID" 2>/dev/null; then
        print_info "Application is running (PID: $PID)"
        print_info "Access at: http://$WEB_HOST:$WEB_PORT"
        print_info "Log file: $LOG_FILE"
        
        # Show last few log lines
        if [ -f "$LOG_FILE" ]; then
            echo ""
            print_info "Recent logs:"
            tail -5 "$LOG_FILE" | sed 's/^/  /'
        fi
        return 0
    else
        print_warning "Process $PID is not running"
        rm -f "$PID_FILE"
        return 1
    fi
}

restart_app() {
    print_header "Restarting FinRobot Equity Research Web Application"
    
    stop_app
    sleep 2
    start_app
}

# ============================================================================
# Help and Usage
# ============================================================================

show_help() {
    cat << 'EOF'

================================================================================
  FinRobot Equity Research - Deployment Script
================================================================================

USAGE:
  ./deploy.sh [COMMAND] [OPTIONS]

COMMANDS:
  start       Start the web application
  stop        Stop the application
  status      Check application status
  restart     Restart the application
  install     Install/update dependencies only
  help        Show this help message

OPTIONS:
  --host HOST       Host address (default: 127.0.0.1)
  --port PORT       Port number (default: 8001)
  --no-reload       Disable auto-reload (for production)

EXAMPLES:
  # Start the application with default settings
  ./deploy.sh start

  # Start on a different host/port
  ./deploy.sh start --host 0.0.0.0 --port 8080

  # Start in production mode (no auto-reload)
  ./deploy.sh start --no-reload

  # Check if application is running
  ./deploy.sh status

  # Stop the application
  ./deploy.sh stop

  # Restart the application
  ./deploy.sh restart

  # Install/update dependencies
  ./deploy.sh install

FEATURES:
  ✓ Automatic virtual environment creation
  ✓ Automatic dependency installation
  ✓ Background process management
  ✓ Graceful shutdown
  ✓ Comprehensive logging
  ✓ Status monitoring

REQUIREMENTS:
  - Python 3.9 or higher
  - Bash shell
  - Standard Unix utilities

CONFIGURATION:
  API Keys:
    Before using equity analysis, configure your API keys:
    
    cp finrobot_equity/core/config/config.ini.example \
       finrobot_equity/core/config/config.ini
    
    Edit config.ini with your API keys:
    [API_KEYS]
    fmp_api_key = YOUR_FMP_API_KEY
    openai_api_key = YOUR_OPENAI_API_KEY

ENVIRONMENT VARIABLES:
  WEB_HOST      Host address (default: 127.0.0.1)
  WEB_PORT      Port number (default: 8001)
  WEB_RELOAD    Enable auto-reload (default: true)

LOG FILES:
  Application logs: finrobot_equity/logs/app.log
  Task logs:        finrobot_equity/logs/task_{id}.log
  Process ID file: .app.pid

TROUBLESHOOTING:
  Issue: Port already in use
    Solution: ./deploy.sh start --port 8080

  Issue: Module not found
    Solution: ./deploy.sh install

  Issue: Permission denied
    Solution: chmod +x deploy.sh

  Issue: Python not found
    Solution: Install Python 3.9+ and ensure it's in PATH

SUPPORT:
  For more information, see:
  - COMPLETE_INTEGRATION_GUIDE.md
  - WEB_APP_INTEGRATION.md
  - INSTALL_EQUITY.md

================================================================================

EOF
}

# ============================================================================
# Main Script Logic
# ============================================================================

main() {
    COMMAND="${1:-help}"
    
    # Parse command-line options
    shift || true
    while [[ $# -gt 0 ]]; do
        case $1 in
            --host)
                WEB_HOST="$2"
                shift 2
                ;;
            --port)
                WEB_PORT="$2"
                shift 2
                ;;
            --no-reload)
                WEB_RELOAD="false"
                shift
                ;;
            *)
                print_warning "Unknown option: $1"
                shift
                ;;
        esac
    done
    
    case "$COMMAND" in
        start)
            start_app
            ;;
        stop)
            stop_app
            ;;
        status)
            check_status
            ;;
        restart)
            restart_app
            ;;
        install)
            install_deps
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "Unknown command: $COMMAND"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
