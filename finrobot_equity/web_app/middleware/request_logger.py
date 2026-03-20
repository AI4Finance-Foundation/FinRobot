"""
Request logging middleware - tracks all API requests
"""
import time
import json
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """Middleware to log all API requests to database"""
    
    # Endpoints to skip logging (to avoid noise)
    SKIP_ENDPOINTS = [
        "/api/status/",  # Task status polling
        "/static/",
        "/output/",
        "/.well-known/",
        "/favicon.ico"
    ]
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip certain endpoints
        path = request.url.path
        if any(path.startswith(skip) for skip in self.SKIP_ENDPOINTS):
            return await call_next(request)
        
        # Record start time
        start_time = time.time()
        
        # Get request info
        method = request.method
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")[:500]  # Limit length
        
        # Get user info from session cookie
        user_id = None
        email = None
        session_id = request.cookies.get("session_id")
        
        if session_id:
            try:
                from ..database.connection import SessionLocal
                from ..database import crud
                
                db = SessionLocal()
                try:
                    session = crud.get_session(db, session_id)
                    if session:
                        user_id = session.user_id
                        user = crud.get_user_by_id(db, session.user_id)
                        if user:
                            email = user.email
                finally:
                    db.close()
            except Exception:
                pass  # Don't fail request if logging fails
        
        # Get request body for POST/PUT requests (limited)
        request_body = None
        if method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                if body and len(body) < 10000:  # Limit to 10KB
                    request_body = body.decode("utf-8")[:5000]  # Limit stored size
            except Exception:
                pass
        
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Log to database (async-safe)
        try:
            from ..database.connection import SessionLocal
            from ..database import crud
            
            db = SessionLocal()
            try:
                crud.log_request(
                    db=db,
                    endpoint=path,
                    method=method,
                    user_id=user_id,
                    email=email,
                    request_body=request_body,
                    response_status=response.status_code,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    duration_ms=duration_ms
                )
            finally:
                db.close()
        except Exception as e:
            # Don't fail request if logging fails
            print(f"Warning: Failed to log request: {e}")
        
        return response
