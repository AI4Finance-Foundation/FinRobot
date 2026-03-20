"""
Authentication module using SQLite database
"""
import os
from datetime import datetime
from typing import Optional, Dict
from fastapi import Request, HTTPException

from .database.connection import SessionLocal
from .database import crud
from .database.models import User


def get_current_user(request: Request) -> Optional[Dict]:
    """Get current user from session cookie"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        return None
    
    db = SessionLocal()
    try:
        session = crud.get_session(db, session_id)
        if not session:
            return None
        
        user = crud.get_user_by_id(db, session.user_id)
        if not user:
            return None
        
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "provider": user.provider,
            "avatar_url": user.avatar_url
        }
    finally:
        db.close()


def require_auth(request: Request) -> Dict:
    """Require authentication, raise 401 if not authenticated"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def create_user_session(
    user_id: int,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    remember: bool = False
) -> str:
    """Create a new session for user"""
    db = SessionLocal()
    try:
        days = 30 if remember else 7
        session = crud.create_session(
            db=db,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            days_valid=days
        )
        
        # Update user's last login
        user = crud.get_user_by_id(db, user_id)
        if user:
            crud.update_user_login(db, user)
        
        return session.session_id
    finally:
        db.close()


def delete_user_session(session_id: str) -> bool:
    """Delete a session"""
    db = SessionLocal()
    try:
        return crud.delete_session(db, session_id)
    finally:
        db.close()


def authenticate_user(email: str, password: str) -> Optional[User]:
    """Authenticate user with email and password"""
    db = SessionLocal()
    try:
        user = crud.get_user_by_email(db, email)
        if not user:
            return None
        
        if not user.password_hash:
            return None  # OAuth user, can't login with password
        
        if not crud.verify_password(password, user.password_hash):
            return None
        
        return user
    finally:
        db.close()


def register_user(
    email: str,
    password: str,
    name: str
) -> Optional[User]:
    """Register a new user"""
    db = SessionLocal()
    try:
        # Check if user exists
        existing = crud.get_user_by_email(db, email)
        if existing:
            return None
        
        user = crud.create_user(
            db=db,
            email=email,
            password=password,
            name=name,
            provider="local"
        )
        return user
    finally:
        db.close()


def get_or_create_github_user(
    email: str,
    name: str,
    avatar_url: Optional[str] = None,
    github_id: Optional[int] = None
) -> User:
    """Get or create a GitHub OAuth user"""
    db = SessionLocal()
    try:
        # Use github: prefix for OAuth users
        github_email = f"github:{email}"
        
        user = crud.get_user_by_email(db, github_email)
        if not user:
            user = crud.create_user(
                db=db,
                email=github_email,
                name=name,
                provider="github",
                avatar_url=avatar_url,
                github_id=github_id
            )
        
        return user
    finally:
        db.close()


def change_user_password(user_id: int, current_password: str, new_password: str) -> bool:
    """Change user password"""
    db = SessionLocal()
    try:
        user = crud.get_user_by_id(db, user_id)
        if not user:
            return False
        
        if not user.password_hash:
            return False  # OAuth user
        
        if not crud.verify_password(current_password, user.password_hash):
            return False
        
        crud.update_user_password(db, user, new_password)
        return True
    finally:
        db.close()


def init_default_admin():
    """Initialize default admin user if no users exist.
    
    Admin credentials can be configured via environment variables:
        FINROBOT_ADMIN_EMAIL (default: admin@finrobot.com)
        FINROBOT_ADMIN_PASSWORD (default: randomly generated)
    
    IMPORTANT: Change the default admin password immediately after first login.
    """
    import secrets
    db = SessionLocal()
    try:
        stats = crud.get_user_stats(db)
        if stats["total_users"] == 0:
            admin_email = os.getenv("FINROBOT_ADMIN_EMAIL", "admin@finrobot.com")
            admin_password = os.getenv("FINROBOT_ADMIN_PASSWORD", secrets.token_urlsafe(12))
            crud.create_user(
                db=db,
                email=admin_email,
                password=admin_password,
                name="Admin User",
                provider="local"
            )
            print(f"✅ Created default admin user: {admin_email}")
            if not os.getenv("FINROBOT_ADMIN_PASSWORD"):
                print(f"⚠️  Generated admin password: {admin_password}")
                print("⚠️  Please change this password immediately after first login!")
    finally:
        db.close()
