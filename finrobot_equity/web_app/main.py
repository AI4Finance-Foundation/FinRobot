import os
import sys
import subprocess
import threading
import uuid
import json
import logging
import hashlib
import secrets
import httpx
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from fastapi import FastAPI, Request, BackgroundTasks, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# ============== GitHub OAuth Configuration ==============
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "YOUR_GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "YOUR_GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI = "http://localhost:8000/api/auth/github/callback"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base path for the actual project (nested structure)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_ROOT = os.path.join(PROJECT_ROOT, "core")
SRC_ROOT = CORE_ROOT  # SRC_ROOT points to core directory, scripts are in core/src
OUTPUT_DIR = os.path.join(CORE_ROOT, "output")
CONFIG_DIR = os.path.join(CORE_ROOT, "config")
DATA_DIR = os.path.join(PROJECT_ROOT, "web_app", "data")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")  # 统一日志目录：finrobot_equity/logs/

# Ensure directories exist
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)  # 新增：创建日志目录

app = FastAPI(title="FinRobot Equity Research", version="1.0.0")

# Mount static files and templates
app.mount("/static", StaticFiles(directory=os.path.join(PROJECT_ROOT, "web_app", "static")), name="static")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
templates = Jinja2Templates(directory=os.path.join(PROJECT_ROOT, "web_app", "templates"))

# ============== Database Integration ==============
from .database.connection import init_db, SessionLocal
from .database import crud
from .auth import (
    get_current_user, require_auth, create_user_session, delete_user_session,
    authenticate_user, register_user, get_or_create_github_user, 
    change_user_password, init_default_admin
)
from .middleware import RequestLoggerMiddleware
from .admin_routes import router as admin_router

# Initialize database
init_db()
init_default_admin()

# Add middleware for request logging
app.add_middleware(RequestLoggerMiddleware)

# Include admin routes
app.include_router(admin_router)

# Auth Models
class LoginRequest(BaseModel):
    email: str
    password: str
    remember: bool = False

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str

# ============== 日志文件持久化功能 ==============

def get_log_file_path(task_id: str) -> str:
    """获取任务日志文件路径"""
    return os.path.join(LOGS_DIR, f"task_{task_id}.log")

def write_log_to_file(task_id: str, message: str):
    """将日志写入文件"""
    log_path = get_log_file_path(task_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        logger.warning(f"Failed to write log to file: {e}")

def read_log_from_file(task_id: str) -> List[str]:
    """从文件读取日志"""
    log_path = get_log_file_path(task_id)
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f.readlines()]
    except Exception as e:
        logger.warning(f"Failed to read log from file: {e}")
        return []

def append_task_log(task_id: str, message: str):
    """同时写入内存和文件的日志函数"""
    # 写入内存
    if task_id in tasks:
        tasks[task_id]["logs"].append(message)
    # 写入文件
    write_log_to_file(task_id, message)

# ============== Auth Routes ==============

@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request, response: Response):
    user = authenticate_user(req.email, req.password)
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Create session
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:500]
    session_id = create_user_session(
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
        remember=req.remember
    )
    
    # Set cookie
    max_age = 30 * 24 * 60 * 60 if req.remember else 7 * 24 * 60 * 60
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        max_age=max_age,
        samesite="lax"
    )
    
    return {"success": True, "user": {"email": user.email, "name": user.name}}

@app.post("/api/auth/register")
async def register(req: RegisterRequest, request: Request, response: Response):
    user = register_user(req.email, req.password, req.name)
    
    if not user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Auto login after register
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:500]
    session_id = create_user_session(
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent
    )
    
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        max_age=7 * 24 * 60 * 60,
        samesite="lax"
    )
    
    return {"success": True, "user": {"email": user.email, "name": user.name}}

@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    session_id = request.cookies.get("session_id")
    if session_id:
        delete_user_session(session_id)
    
    response.delete_cookie("session_id")
    return {"success": True}

@app.get("/api/auth/me")
async def get_me(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"email": user["email"], "name": user["name"]}

class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str

@app.post("/api/auth/change-password")
async def change_password_route(req: ChangePasswordRequest, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # GitHub users cannot change password
    if user.get("provider") == "github" or user["email"].startswith("github:"):
        raise HTTPException(status_code=400, detail="GitHub users cannot change password")
    
    success = change_user_password(user["id"], req.currentPassword, req.newPassword)
    
    if not success:
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    
    return {"success": True, "message": "Password changed successfully"}

# ============== GitHub OAuth Routes ==============

@app.get("/api/auth/github")
async def github_login():
    """Redirect to GitHub OAuth authorization page"""
    if GITHUB_CLIENT_ID == "YOUR_GITHUB_CLIENT_ID":
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured. Please set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.")
    
    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        f"&scope=user:email"
    )
    return RedirectResponse(url=github_auth_url)

@app.get("/api/auth/github/callback")
async def github_callback(code: str, response: Response):
    """Handle GitHub OAuth callback"""
    if not code:
        raise HTTPException(status_code=400, detail="No code provided")
    
    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": GITHUB_REDIRECT_URI
            },
            headers={"Accept": "application/json"}
        )
        token_data = token_response.json()
        
        if "error" in token_data:
            raise HTTPException(status_code=400, detail=token_data.get("error_description", "Failed to get access token"))
        
        access_token = token_data.get("access_token")
        
        # Get user info from GitHub
        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
        )
        github_user = user_response.json()
        
        # Get user email (might be private)
        email_response = await client.get(
            "https://api.github.com/user/emails",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
        )
        emails = email_response.json()
        
        # Find primary email
        primary_email = None
        for email_obj in emails:
            if email_obj.get("primary"):
                primary_email = email_obj.get("email")
                break
        
        if not primary_email:
            primary_email = github_user.get("email") or f"{github_user['login']}@github.local"
        
        # Create or update user in database
        user = get_or_create_github_user(
            email=primary_email,
            name=github_user.get("name") or github_user.get("login"),
            avatar_url=github_user.get("avatar_url"),
            github_id=github_user.get("id")
        )
        
        # Create session
        session_id = create_user_session(user_id=user.id)
        
        # Create redirect response with cookie
        redirect_response = RedirectResponse(url="/", status_code=302)
        redirect_response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=7 * 24 * 60 * 60,
            samesite="lax"
        )
        
        return redirect_response

# ============== Page Routes ==============

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    user = get_current_user(request)
    if not user:
        response = RedirectResponse(url="/login", status_code=303)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = get_current_user(request)
    if user:
        response = RedirectResponse(url="/", status_code=303)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return templates.TemplateResponse("login.html", {"request": request})

# ============== Chrome DevTools Route ==============

@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def chrome_devtools():
    """Handle Chrome DevTools configuration request"""
    return Response(content="", status_code=204)

# ============== Task System ==============

# Store tasks in memory
tasks = {}

class AnalysisRequest(BaseModel):
    ticker: str
    company_name: str
    peers: List[str] = []
    years_limit: int = 5
    revenue_growth_2025: float = 0.05
    revenue_growth_2026: float = 0.06
    revenue_growth_2027: float = 0.04
    margin_improvement: float = 0.01
    generate_text: bool = True
    generate_pdf: bool = True
    fmp_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    # 新增增强功能选项
    enable_sensitivity_analysis: bool = False
    enable_catalyst_analysis: bool = False
    enable_enhanced_news: bool = False
    enable_enhanced_charts: bool = False
    enable_valuation_analysis: bool = False

def run_process(command, task_id, cwd=None):
    """Run a shell command and capture output to the task logs."""
    logger.info(f"Task {task_id}: Running command: {' '.join(command)}")
    append_task_log(task_id, f"Executing: {' '.join(command)}")  # 修改：使用新函数
    
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=cwd or SRC_ROOT
        )
        
        for line in process.stdout:
            append_task_log(task_id, line.strip())  # 修改：使用新函数
            
        process.wait()
        
        if process.returncode != 0:
            raise Exception(f"Command failed with return code {process.returncode}")
            
        return True
    except Exception as e:
        append_task_log(task_id, f"Error: {str(e)}")  # 修改：使用新函数
        tasks[task_id]["status"] = "failed"
        return False

def execute_analysis_pipeline(task_id: str, req: AnalysisRequest):
    tasks[task_id]["status"] = "running"
    append_task_log(task_id, "Starting analysis pipeline...")  # 修改：使用新函数
    
    # Update report status in database
    try:
        db = SessionLocal()
        crud.update_report_request(db, task_id, "running")
        db.close()
    except Exception as e:
        logger.warning(f"Failed to update report status: {e}")
    
    python_exe = sys.executable
    src_dir = os.path.join(SRC_ROOT, "src")  # Now points to core/src
    config_file = os.path.join(CONFIG_DIR, "config.ini")
    
    # Create output directories
    analysis_output_dir = os.path.join(OUTPUT_DIR, req.ticker, "analysis")
    report_output_dir = os.path.join(OUTPUT_DIR, req.ticker, "report")
    os.makedirs(analysis_output_dir, exist_ok=True)
    os.makedirs(report_output_dir, exist_ok=True)
    
    # Step 1: Generate Financial Analysis
    cmd_analysis = [
        python_exe,
        os.path.join(src_dir, "generate_financial_analysis.py"),
        "--company-ticker", req.ticker,
        "--company-name", req.company_name,
        "--years-limit", str(req.years_limit),
        "--revenue-growth-2025", str(req.revenue_growth_2025),
        "--revenue-growth-2026", str(req.revenue_growth_2026),
        "--revenue-growth-2027", str(req.revenue_growth_2027),
        "--margin-improvement", str(req.margin_improvement),
        "--output-dir", analysis_output_dir
    ]
    
    if req.peers:
        cmd_analysis.append("--peer-tickers")
        cmd_analysis.extend(req.peers)
        
    if req.generate_text:
        cmd_analysis.append("--generate-text-sections")
    
    # 新增增强功能选项
    if req.enable_sensitivity_analysis:
        cmd_analysis.append("--enable-sensitivity-analysis")
    if req.enable_catalyst_analysis:
        cmd_analysis.append("--enable-catalyst-analysis")
    if req.enable_enhanced_news:
        cmd_analysis.append("--enable-enhanced-news")
        
    cmd_analysis.extend(["--config-file", config_file])

    if not run_process(cmd_analysis, task_id, cwd=SRC_ROOT):
        # Update report status to failed
        try:
            db = SessionLocal()
            crud.update_report_request(db, task_id, "failed", "Financial analysis failed")
            db.close()
        except Exception as e:
            logger.warning(f"Failed to update report status: {e}")
        return

    # Step 2: Create Equity Report
    base_output_dir = analysis_output_dir
    
    cmd_report = [
        python_exe,
        os.path.join(src_dir, "create_equity_report.py"),
        "--company-ticker", req.ticker,
        "--company-name", req.company_name,
        "--analysis-csv", os.path.join(base_output_dir, "financial_metrics_and_forecasts.csv"),
        "--ratios-csv", os.path.join(base_output_dir, "ratios_raw_data.csv"),
        "--tagline-file", os.path.join(base_output_dir, "tagline.txt"),
        "--company-overview-file", os.path.join(base_output_dir, "company_overview.txt"),
        "--investment-overview-file", os.path.join(base_output_dir, "investment_overview.txt"),
        "--valuation-overview-file", os.path.join(base_output_dir, "valuation_overview.txt"),
        "--risks-file", os.path.join(base_output_dir, "risks.txt"),
        "--competitor-analysis-file", os.path.join(base_output_dir, "competitor_analysis.txt"),
        "--major-takeaways-file", os.path.join(base_output_dir, "major_takeaways.txt"),
        "--output-dir", report_output_dir,
        "--config-file", config_file,
        "--enable-text-regeneration"
    ]
    
    # 新增增强功能选项
    if req.enable_enhanced_charts:
        cmd_report.append("--enable-enhanced-charts")
    if req.enable_valuation_analysis:
        cmd_report.append("--enable-valuation-analysis")
    
    # 添加增强分析文件路径
    if req.enable_sensitivity_analysis:
        sensitivity_file = os.path.join(base_output_dir, "sensitivity_analysis.json")
        if os.path.exists(sensitivity_file):
            cmd_report.extend(["--sensitivity-analysis-file", sensitivity_file])
    
    if req.enable_catalyst_analysis:
        catalyst_file = os.path.join(base_output_dir, "catalyst_analysis.json")
        if os.path.exists(catalyst_file):
            cmd_report.extend(["--catalyst-analysis-file", catalyst_file])
    
    if req.enable_enhanced_news:
        enhanced_news_file = os.path.join(base_output_dir, "enhanced_news.json")
        if os.path.exists(enhanced_news_file):
            cmd_report.extend(["--enhanced-news-file", enhanced_news_file])
    
    if req.peers:
        cmd_report.extend([
            "--peer-ebitda-csv", os.path.join(base_output_dir, "peer_ebitda_comparison.csv"),
            "--peer-ev-ebitda-csv", os.path.join(base_output_dir, "peer_ev_ebitda_comparison.csv")
        ])

    if not run_process(cmd_report, task_id, cwd=SRC_ROOT):
        # Update report status to failed
        try:
            db = SessionLocal()
            crud.update_report_request(db, task_id, "failed", "Report creation failed")
            db.close()
        except Exception as e:
            logger.warning(f"Failed to update report status: {e}")
        return

    # Step 3: Generate PDF Report
    if req.generate_pdf:
        append_task_log(task_id, "Generating PDF report...")  # 修改：使用新函数
        cmd_pdf = [
            python_exe,
            os.path.join(src_dir, "generate_pdf_report.py"),
            "--company-ticker", req.ticker,
            "--company-name", req.company_name,
            "--analysis-dir", base_output_dir,
            "--output-dir", report_output_dir,
            "--config-file", config_file
        ]
        
        if not run_process(cmd_pdf, task_id, cwd=SRC_ROOT):
            append_task_log(task_id, "Warning: PDF generation failed, but HTML reports are available.")  # 修改：使用新函数

    tasks[task_id]["status"] = "completed"
    append_task_log(task_id, "Pipeline completed successfully!")  # 修改：使用新函数
    
    # Update report status in database
    try:
        db = SessionLocal()
        crud.update_report_request(db, task_id, "completed")
        db.close()
    except Exception as e:
        logger.warning(f"Failed to update report status: {e}")
    
    # Get report files
    report_files = []
    if os.path.exists(report_output_dir):
        report_files = [f for f in os.listdir(report_output_dir) if f.endswith((".html", ".pdf"))]
    
    # Separate HTML and PDF files
    html_files = [f for f in report_files if f.endswith('.html')]
    pdf_files = [f for f in report_files if f.endswith('.pdf')]
    
    # Prioritize Professional HTML reports (matching PDF structure)
    professional_htmls = [f for f in html_files if 'Professional_Equity_Report' in f]
    other_htmls = [f for f in html_files if f not in professional_htmls]
    sorted_htmls = professional_htmls + other_htmls
    
    # Prioritize Professional PDF reports
    professional_pdfs = [f for f in pdf_files if 'Professional_Equity_Report' in f or 'Professional' in f]
    other_pdfs = [f for f in pdf_files if f not in professional_pdfs]
    sorted_pdfs = professional_pdfs + other_pdfs
    
    tasks[task_id]["result"] = {
        "report_dir": report_output_dir,
        "ticker": req.ticker,
        "html": sorted_htmls,
        "pdf": sorted_pdfs
    }

@app.post("/api/run")
async def run_analysis(req: AnalysisRequest, request: Request, background_tasks: BackgroundTasks):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    task_id = str(uuid.uuid4())
    tasks[task_id] = {"status": "pending", "logs": [], "result": None, "user": user["email"]}
    
    # 初始化日志文件
    write_log_to_file(task_id, f"Task created by user: {user['email']}")
    write_log_to_file(task_id, f"Ticker: {req.ticker}, Company: {req.company_name}")
    
    # Record report request in database
    try:
        db = SessionLocal()
        crud.create_report_request(
            db=db,
            user_id=user["id"],
            task_id=task_id,
            ticker=req.ticker,
            company_name=req.company_name,
            peers=",".join(req.peers) if req.peers else None,
            generate_text=req.generate_text,
            generate_pdf=req.generate_pdf,
            enable_sensitivity=req.enable_sensitivity_analysis,
            enable_catalyst=req.enable_catalyst_analysis,
            enable_enhanced_news=req.enable_enhanced_news
        )
        db.close()
    except Exception as e:
        logger.warning(f"Failed to record report request: {e}")
    
    background_tasks.add_task(execute_analysis_pipeline, task_id, req)
    return {"task_id": task_id}

@app.get("/api/status/{task_id}")
async def get_status(task_id: str, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if task_id not in tasks:
        # 尝试从文件读取日志（用于服务器重启后的恢复）
        file_logs = read_log_from_file(task_id)
        if file_logs:
            return {
                "status": "unknown",
                "logs": file_logs,
                "result": None,
                "message": "Task found in log files (server may have restarted)"
            }
        return JSONResponse(status_code=404, content={"message": "Task not found"})
    return tasks[task_id]

# ============== 新增：日志文件读取API ==============

@app.get("/api/logs/{task_id}")
async def get_task_logs(task_id: str, request: Request):
    """获取任务的持久化日志"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    log_path = get_log_file_path(task_id)
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail="Log file not found")
    
    logs = read_log_from_file(task_id)
    return {
        "task_id": task_id,
        "log_file": log_path,
        "logs": logs,
        "line_count": len(logs)
    }

@app.get("/api/logs/{task_id}/download")
async def download_task_logs(task_id: str, request: Request):
    """下载任务日志文件"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    log_path = get_log_file_path(task_id)
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail="Log file not found")
    
    return FileResponse(
        path=log_path,
        filename=f"task_{task_id}.log",
        media_type="text/plain"
    )

@app.get("/api/logs")
async def list_all_logs(request: Request):
    """列出所有日志文件"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # 只有管理员可以查看所有日志
    # Admin emails can be configured via FINROBOT_ADMIN_EMAILS env var (comma-separated)
    admin_emails = os.getenv("FINROBOT_ADMIN_EMAILS", "admin@finrobot.com").split(",")
    admin_emails = [e.strip() for e in admin_emails]
    if user.get("email") not in admin_emails:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    log_files = []
    if os.path.exists(LOGS_DIR):
        for filename in os.listdir(LOGS_DIR):
            if filename.endswith(".log"):
                file_path = os.path.join(LOGS_DIR, filename)
                stat = os.stat(file_path)
                log_files.append({
                    "filename": filename,
                    "task_id": filename.replace("task_", "").replace(".log", ""),
                    "size_bytes": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
    
    # 按修改时间倒序排列
    log_files.sort(key=lambda x: x["modified_at"], reverse=True)
    
    return {
        "logs_dir": LOGS_DIR,
        "total_files": len(log_files),
        "files": log_files
    }

@app.get("/api/reports/{ticker}")
async def list_reports(ticker: str, request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    report_dir = os.path.join(OUTPUT_DIR, ticker, "report")
    if not os.path.exists(report_dir):
        return {"reports": []}
    
    reports = [f for f in os.listdir(report_dir) if f.endswith((".html", ".pdf"))]
    return {"reports": reports}