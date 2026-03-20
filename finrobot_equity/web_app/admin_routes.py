"""
Admin API routes for viewing users and request logs
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional
from .database.connection import SessionLocal
from .database import crud

router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_admin(request: Request):
    """Simple admin check - in production, use proper role-based auth"""
    # For now, just check if user is logged in
    # You can add admin role check here later
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    db = SessionLocal()
    try:
        session = crud.get_session(db, session_id)
        if not session:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        user = crud.get_user_by_id(db, session.user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        # Add admin check here if needed
        # if user.email not in ADMIN_EMAILS:
        #     raise HTTPException(status_code=403, detail="Admin access required")
        
        return user
    finally:
        db.close()


@router.get("/stats")
async def get_stats(admin=Depends(require_admin), db=Depends(get_db)):
    """Get overall system statistics"""
    user_stats = crud.get_user_stats(db)
    report_stats = crud.get_report_stats(db)
    request_stats = crud.get_request_stats(db, hours=24)
    
    return {
        "users": user_stats,
        "reports": report_stats,
        "requests": request_stats
    }


@router.get("/users")
async def get_users(
    skip: int = 0,
    limit: int = 50,
    admin=Depends(require_admin),
    db=Depends(get_db)
):
    """Get list of all users"""
    users = crud.get_all_users(db, skip=skip, limit=limit)
    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "provider": u.provider,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "is_active": u.is_active
            }
            for u in users
        ]
    }


@router.get("/users/active")
async def get_active_users(
    days: int = 7,
    limit: int = 50,
    admin=Depends(require_admin),
    db=Depends(get_db)
):
    """Get list of active users in the last N days"""
    users = crud.get_active_users_list(db, days=days, limit=limit)
    return {"users": users, "period_days": days}


@router.get("/requests")
async def get_requests(
    limit: int = 100,
    user_id: Optional[int] = None,
    endpoint: Optional[str] = None,
    admin=Depends(require_admin),
    db=Depends(get_db)
):
    """Get recent request logs"""
    logs = crud.get_recent_requests(db, limit=limit, user_id=user_id, endpoint_filter=endpoint)
    return {
        "requests": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "email": log.email,
                "endpoint": log.endpoint,
                "method": log.method,
                "response_status": log.response_status,
                "ip_address": log.ip_address,
                "duration_ms": log.duration_ms,
                "created_at": log.created_at.isoformat() if log.created_at else None
            }
            for log in logs
        ]
    }


@router.get("/reports")
async def get_reports(
    limit: int = 100,
    user_id: Optional[int] = None,
    admin=Depends(require_admin),
    db=Depends(get_db)
):
    """Get report generation history"""
    from sqlalchemy import desc
    from .database.models import ReportRequest, User
    
    query = db.query(ReportRequest, User.email, User.name).join(User)
    if user_id:
        query = query.filter(ReportRequest.user_id == user_id)
    
    reports = query.order_by(desc(ReportRequest.created_at)).limit(limit).all()
    
    return {
        "reports": [
            {
                "id": r[0].id,
                "task_id": r[0].task_id,
                "ticker": r[0].ticker,
                "company_name": r[0].company_name,
                "status": r[0].status,
                "user_email": r[1],
                "user_name": r[2],
                "created_at": r[0].created_at.isoformat() if r[0].created_at else None,
                "completed_at": r[0].completed_at.isoformat() if r[0].completed_at else None,
                "duration_seconds": r[0].duration_seconds,
                "error_message": r[0].error_message
            }
            for r in reports
        ]
    }


@router.get("/user/{user_id}")
async def get_user_detail(
    user_id: int,
    admin=Depends(require_admin),
    db=Depends(get_db)
):
    """Get detailed user information"""
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    reports = crud.get_user_reports(db, user_id, limit=20)
    recent_requests = crud.get_recent_requests(db, limit=20, user_id=user_id)
    
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "provider": user.provider,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "is_active": user.is_active
        },
        "reports": [
            {
                "ticker": r.ticker,
                "company_name": r.company_name,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in reports
        ],
        "recent_requests": [
            {
                "endpoint": r.endpoint,
                "method": r.method,
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in recent_requests
        ]
    }
