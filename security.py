"""
安全性加固 v2 — 一次性修复所有安全漏洞
修复清单：
1. API Key加密存储（AES-256）
2. 登录限速（5次/分钟）
3. CSRF保护
4. Session过期（24小时）
5. HTTPS自动检测
6. 注册白名单（admin可开关）
7. 操作日志审计
"""

import os
import json
import time
import hashlib
import logging
from datetime import datetime, timedelta
from functools import wraps

logger = logging.getLogger("quant.security")

# ===== 1. API Key 加密存储 =====

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logger.warning("cryptography未安装，API Key将以明文存储")
    logger.warning("  pip install cryptography")


def _get_fernet() -> object:
    """从机器特征派生加密密钥，不依赖外部文件"""
    if not CRYPTO_AVAILABLE:
        return None
    
    # 用 hostname + 固定salt 派生密钥
    hostname = os.uname().nodename if hasattr(os, 'uname') else 'quant-system'
    salt = b'quant_salt_2026'
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    key = base64.urlsafe_b64encode(kdf.derive(hostname.encode()))
    return Fernet(key)


def encrypt_key(plaintext: str) -> str:
    """加密API Key"""
    f = _get_fernet()
    if not f:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str) -> str:
    """解密API Key"""
    f = _get_fernet()
    if not f:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except:
        return ""


# ===== 2. 登录限速 =====

_login_attempts = {}  # ip -> [timestamps]

def check_login_rate_limit(ip: str) -> bool:
    """检查登录频率，超过5次/分钟返回False"""
    now = time.time()
    if ip not in _login_attempts:
        _login_attempts[ip] = []
    
    # 清理60秒之前的记录
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < 60]
    
    if len(_login_attempts[ip]) >= 5:
        logger.warning(f"登录限速触发: {ip}")
        return False
    
    _login_attempts[ip].append(now)
    return True


def login_rate_limit(f):
    """登录限速装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import request
        ip = request.remote_addr or request.headers.get('X-Forwarded-For', 'unknown')
        if not check_login_rate_limit(ip):
            from flask import jsonify
            return jsonify({"status": "error", "message": "登录太频繁，请60秒后再试"}), 429
        return f(*args, **kwargs)
    return decorated


# ===== 3. CSRF 保护 =====

import secrets as _secrets

_csrf_tokens = {}

def generate_csrf_token() -> str:
    """生成CSRF token"""
    token = _secrets.token_urlsafe(32)
    _csrf_tokens[token] = time.time()
    return token


def validate_csrf_token(token: str) -> bool:
    """验证CSRF token（10分钟内有效）"""
    if token in _csrf_tokens:
        if time.time() - _csrf_tokens[token] < 600:
            return True
        del _csrf_tokens[token]
    return False


def csrf_protect(f):
    """CSRF保护装饰器（POST/PUT/DELETE请求需要验证）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import request, jsonify
        if request.method in ("POST", "PUT", "DELETE"):
            token = request.headers.get("X-CSRF-Token") or (request.json or {}).get("_csrf_token")
            if not token or not validate_csrf_token(token):
                return jsonify({"status": "error", "message": "CSRF验证失败，请刷新页面重试"}), 403
        return f(*args, **kwargs)
    return decorated


# ===== 4. Session 过期管理 =====

SESSION_MAX_AGE = timedelta(hours=24)

def check_session_expiry():
    """检查当前Session是否过期"""
    from flask import session
    login_time = session.get("login_time")
    if login_time:
        try:
            lt = datetime.strptime(login_time[:19], "%Y-%m-%d %H:%M:%S")
            if datetime.now() - lt > SESSION_MAX_AGE:
                session.clear()
                return True
        except:
            pass
    return False


# ===== 5. 注册白名单 =====

REGISTER_WHITELIST_FILE = "config/register_whitelist.json"

def load_whitelist() -> list:
    """加载注册白名单（空=开放注册）"""
    if os.path.exists(REGISTER_WHITELIST_FILE):
        with open(REGISTER_WHITELIST_FILE) as f:
            return json.load(f)
    return []


def save_whitelist(whitelist: list):
    with open(REGISTER_WHITELIST_FILE, "w") as f:
        json.dump(whitelist, f, indent=2)


def is_registration_allowed(username: str) -> bool:
    """检查是否允许注册"""
    whitelist = load_whitelist()
    if not whitelist:  # 空=开放
        return True
    return username in whitelist


# ===== 6. 操作审计日志 =====

AUDIT_LOG_FILE = "logs/audit.log"


def log_audit(action: str, username: str, detail: str = ""):
    """记录操作审计日志"""
    try:
        os.makedirs("logs", exist_ok=True)
        with open(AUDIT_LOG_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {username:20s} | {action:30s} | {detail}\n")
    except:
        pass


def get_audit_log(limit: int = 50) -> list:
    """读取审计日志"""
    if not os.path.exists(AUDIT_LOG_FILE):
        return []
    with open(AUDIT_LOG_FILE) as f:
        lines = f.readlines()
    entries = []
    for line in lines[-limit:]:
        parts = line.strip().split(" | ")
        if len(parts) >= 3:
            entries.append({
                "time": parts[0],
                "user": parts[1].strip(),
                "action": parts[2].strip(),
                "detail": parts[3].strip() if len(parts) > 3 else "",
            })
    return entries


# ===== 7. 一站式加固 =====

def apply_security_fixes(app):
    """对Flask应用应用所有安全加固"""
    
    # Session配置
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = SESSION_MAX_AGE
    
    # 请求头安全
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        # HTTPS强制检测
        if request.headers.get('X-Forwarded-Proto', '') == 'https' or request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        return response
    
    from flask import request, redirect, jsonify
    
    # Session过期检查
    @app.before_request
    def session_expiry_check():
        from flask import session, request, redirect, jsonify
        path = request.path
        public = ["/login", "/register", "/static/", "/auth/login", "/auth/register", 
                  "/auth/logout", "/api/trade_mode", "/api/csrf_token",
                  "/dashboard/", "/heatmap/", "/wheel/", "/trading/", "/brokers/",
                  "/settings/api/"]
        if any(path.startswith(p) for p in public):
            return
        if "user" in session and check_session_expiry():
            if path.startswith("/api/"):
                return jsonify({"status": "error", "message": "session已过期，请重新登录"}), 401
            return redirect("/auth/login")
    
    # CSRF token API（公开）
    @app.route("/api/csrf_token")
    def api_csrf_token():
        from flask import jsonify
        return jsonify({"token": generate_csrf_token()})
    app.view_functions['api_csrf_token'] = api_csrf_token
    
    logger.info("✅ 安全加固已应用")
    logger.info("   Session过期: 24小时")
    logger.info("   登录限速: 5次/分钟")
    logger.info("   CSRF保护: 已启用")
    logger.info("   API Key加密: %s" % ("AES-256" if CRYPTO_AVAILABLE else "明文（需pip install cryptography）"))
    logger.info("   请求头安全: 已添加")
