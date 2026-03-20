"""
SQLAlchemy ORM models for FinRobot database
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    """User account model"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)  # Nullable for OAuth users
    name = Column(String(100))
    provider = Column(String(50), default="local")  # 'local' or 'github'
    avatar_url = Column(String(500))
    github_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    request_logs = relationship("RequestLog", back_populates="user", cascade="all, delete-orphan")
    report_requests = relationship("ReportRequest", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}', name='{self.name}')>"


class Session(Base):
    """User session model"""
    __tablename__ = "sessions"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String(255), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ip_address = Column(String(50))
    user_agent = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="sessions")
    
    def __repr__(self):
        return f"<Session(id={self.id}, user_id={self.user_id})>"



class RequestLog(Base):
    """API request log model - tracks who is using the system and what they request"""
    __tablename__ = "request_logs"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    email = Column(String(255), index=True)
    endpoint = Column(String(255), index=True)
    method = Column(String(10))
    request_body = Column(Text)
    response_status = Column(Integer)
    ip_address = Column(String(50))
    user_agent = Column(Text)
    duration_ms = Column(Integer)  # Request duration in milliseconds
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    user = relationship("User", back_populates="request_logs")
    
    def __repr__(self):
        return f"<RequestLog(id={self.id}, endpoint='{self.endpoint}', user='{self.email}')>"


class ReportRequest(Base):
    """Report generation request model"""
    __tablename__ = "report_requests"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_id = Column(String(255), unique=True, index=True)
    ticker = Column(String(20), index=True, nullable=False)
    company_name = Column(String(255))
    peers = Column(String(500))  # Comma-separated peer tickers
    status = Column(String(50), default="pending")  # pending, running, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime)
    duration_seconds = Column(Integer)
    error_message = Column(Text)
    
    # Report options
    generate_text = Column(Boolean, default=True)
    generate_pdf = Column(Boolean, default=True)
    enable_sensitivity = Column(Boolean, default=False)
    enable_catalyst = Column(Boolean, default=False)
    enable_enhanced_news = Column(Boolean, default=False)
    
    # Relationships
    user = relationship("User", back_populates="report_requests")
    
    def __repr__(self):
        return f"<ReportRequest(id={self.id}, ticker='{self.ticker}', status='{self.status}')>"
