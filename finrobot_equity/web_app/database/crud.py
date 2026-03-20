"""
CRUD operations for database
"""
import bcrypt
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from .models import User, Session as SessionModel, RequestLog, ReportRequest


# =============================================================================
# Password utilities
# =============================================================================

def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash"""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


# =============================================================================
# User CRUD
# =============================================================================

def create_user(
    db: Session,
    email: str,
    password: Optional[str] = None,
    name: Optional[str] = None,
    provider: str = "local",
    avatar_url: Optional[str] = None,
    github_id: Optional[int] = None
) -> User:
    """Create a new user"""
    user = User(
        email=email,
        password_hash=hash_password(password) if password else None,
        name=name,
        provider=provider,
        avatar_url=avatar_url,
        github_id=github_id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Get user by email"""
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """Get user by ID"""
    return db.query(User).filter(User.id == user_id).first()


def update_user_login(db: Session, user: User) -> User:
    """Update user's last login time"""
    user.last_login = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def get_all_users(db: Session, skip: int = 0, limit: int = 100) -> List[User]:
    """Get all users with pagination"""
    return db.query(User).order_by(desc(User.created_at)).offset(skip).limit(limit).all()


def update_user_password(db: Session, user: User, new_password: str) -> User:
    """Update user password"""
    user.password_hash = hash_password(new_password)
    db.commit()
    db.refresh(user)
    return user


# =============================================================================
# Session CRUD
# =============================================================================

def create_session(
    db: Session,
    user_id: int,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    days_valid: int = 7
) -> SessionModel:
    """Create a new session"""
    session_id = secrets.token_urlsafe(32)
    session = SessionModel(
        session_id=session_id,
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=datetime.utcnow() + timedelta(days=days_valid)
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: str) -> Optional[SessionModel]:
    """Get session by session_id"""
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session and session.expires_at < datetime.utcnow():
        # Session expired, delete it
        db.delete(session)
        db.commit()
        return None
    return session


def delete_session(db: Session, session_id: str) -> bool:
    """Delete a session"""
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if session:
        db.delete(session)
        db.commit()
        return True
    return False


def delete_user_sessions(db: Session, user_id: int) -> int:
    """Delete all sessions for a user"""
    count = db.query(SessionModel).filter(SessionModel.user_id == user_id).delete()
    db.commit()
    return count


# =============================================================================
# Request Log CRUD
# =============================================================================

def log_request(
    db: Session,
    endpoint: str,
    method: str,
    user_id: Optional[int] = None,
    email: Optional[str] = None,
    request_body: Optional[str] = None,
    response_status: Optional[int] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    duration_ms: Optional[int] = None
) -> RequestLog:
    """Log an API request"""
    log = RequestLog(
        user_id=user_id,
        email=email,
        endpoint=endpoint,
        method=method,
        request_body=request_body,
        response_status=response_status,
        ip_address=ip_address,
        user_agent=user_agent,
        duration_ms=duration_ms
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def get_recent_requests(
    db: Session,
    limit: int = 100,
    user_id: Optional[int] = None,
    endpoint_filter: Optional[str] = None
) -> List[RequestLog]:
    """Get recent request logs"""
    query = db.query(RequestLog)
    if user_id:
        query = query.filter(RequestLog.user_id == user_id)
    if endpoint_filter:
        query = query.filter(RequestLog.endpoint.like(f"%{endpoint_filter}%"))
    return query.order_by(desc(RequestLog.created_at)).limit(limit).all()


# =============================================================================
# Report Request CRUD
# =============================================================================

def create_report_request(
    db: Session,
    user_id: int,
    task_id: str,
    ticker: str,
    company_name: str,
    peers: Optional[str] = None,
    generate_text: bool = True,
    generate_pdf: bool = True,
    enable_sensitivity: bool = False,
    enable_catalyst: bool = False,
    enable_enhanced_news: bool = False
) -> ReportRequest:
    """Create a new report request"""
    report = ReportRequest(
        user_id=user_id,
        task_id=task_id,
        ticker=ticker,
        company_name=company_name,
        peers=peers,
        status="pending",
        generate_text=generate_text,
        generate_pdf=generate_pdf,
        enable_sensitivity=enable_sensitivity,
        enable_catalyst=enable_catalyst,
        enable_enhanced_news=enable_enhanced_news
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def update_report_request(
    db: Session,
    task_id: str,
    status: str,
    error_message: Optional[str] = None
) -> Optional[ReportRequest]:
    """Update report request status"""
    report = db.query(ReportRequest).filter(ReportRequest.task_id == task_id).first()
    if report:
        report.status = status
        if status in ["completed", "failed"]:
            report.completed_at = datetime.utcnow()
            if report.created_at:
                report.duration_seconds = int((report.completed_at - report.created_at).total_seconds())
        if error_message:
            report.error_message = error_message
        db.commit()
        db.refresh(report)
    return report


def get_user_reports(db: Session, user_id: int, limit: int = 50) -> List[ReportRequest]:
    """Get reports for a user"""
    return db.query(ReportRequest).filter(
        ReportRequest.user_id == user_id
    ).order_by(desc(ReportRequest.created_at)).limit(limit).all()


# =============================================================================
# Statistics and Analytics
# =============================================================================

def get_user_stats(db: Session) -> Dict[str, Any]:
    """Get user statistics"""
    total_users = db.query(func.count(User.id)).scalar()
    active_users_7d = db.query(func.count(User.id)).filter(
        User.last_login >= datetime.utcnow() - timedelta(days=7)
    ).scalar()
    new_users_7d = db.query(func.count(User.id)).filter(
        User.created_at >= datetime.utcnow() - timedelta(days=7)
    ).scalar()
    
    return {
        "total_users": total_users,
        "active_users_7d": active_users_7d,
        "new_users_7d": new_users_7d
    }


def get_report_stats(db: Session) -> Dict[str, Any]:
    """Get report generation statistics"""
    total_reports = db.query(func.count(ReportRequest.id)).scalar()
    completed_reports = db.query(func.count(ReportRequest.id)).filter(
        ReportRequest.status == "completed"
    ).scalar()
    failed_reports = db.query(func.count(ReportRequest.id)).filter(
        ReportRequest.status == "failed"
    ).scalar()
    reports_today = db.query(func.count(ReportRequest.id)).filter(
        ReportRequest.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)
    ).scalar()
    
    # Top tickers
    top_tickers = db.query(
        ReportRequest.ticker,
        func.count(ReportRequest.id).label("count")
    ).group_by(ReportRequest.ticker).order_by(desc("count")).limit(10).all()
    
    return {
        "total_reports": total_reports,
        "completed_reports": completed_reports,
        "failed_reports": failed_reports,
        "reports_today": reports_today,
        "top_tickers": [{"ticker": t[0], "count": t[1]} for t in top_tickers]
    }


def get_active_users_list(db: Session, days: int = 7, limit: int = 50) -> List[Dict[str, Any]]:
    """Get list of active users with their activity stats"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    users = db.query(
        User.id,
        User.email,
        User.name,
        User.last_login,
        User.created_at,
        func.count(ReportRequest.id).label("report_count")
    ).outerjoin(ReportRequest).filter(
        User.last_login >= cutoff
    ).group_by(User.id).order_by(desc(User.last_login)).limit(limit).all()
    
    return [
        {
            "id": u[0],
            "email": u[1],
            "name": u[2],
            "last_login": u[3].isoformat() if u[3] else None,
            "created_at": u[4].isoformat() if u[4] else None,
            "report_count": u[5]
        }
        for u in users
    ]


def get_request_stats(db: Session, hours: int = 24) -> Dict[str, Any]:
    """Get request statistics for the last N hours"""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    total_requests = db.query(func.count(RequestLog.id)).filter(
        RequestLog.created_at >= cutoff
    ).scalar()
    
    # Requests by endpoint
    by_endpoint = db.query(
        RequestLog.endpoint,
        func.count(RequestLog.id).label("count")
    ).filter(
        RequestLog.created_at >= cutoff
    ).group_by(RequestLog.endpoint).order_by(desc("count")).limit(10).all()
    
    # Unique users
    unique_users = db.query(func.count(func.distinct(RequestLog.user_id))).filter(
        RequestLog.created_at >= cutoff,
        RequestLog.user_id.isnot(None)
    ).scalar()
    
    return {
        "total_requests": total_requests,
        "unique_users": unique_users,
        "by_endpoint": [{"endpoint": e[0], "count": e[1]} for e in by_endpoint]
    }
