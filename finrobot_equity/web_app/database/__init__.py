# Database module for FinRobot Web App
from .connection import get_db, init_db, engine
from .models import User, Session, RequestLog, ReportRequest
from .crud import (
    create_user,
    get_user_by_email,
    verify_password,
    create_session,
    get_session,
    delete_session,
    log_request,
    create_report_request,
    update_report_request,
    get_user_stats,
    get_recent_requests,
    get_report_stats
)

__all__ = [
    "get_db",
    "init_db", 
    "engine",
    "User",
    "Session",
    "RequestLog",
    "ReportRequest",
    "create_user",
    "get_user_by_email",
    "verify_password",
    "create_session",
    "get_session",
    "delete_session",
    "log_request",
    "create_report_request",
    "update_report_request",
    "get_user_stats",
    "get_recent_requests",
    "get_report_stats"
]
