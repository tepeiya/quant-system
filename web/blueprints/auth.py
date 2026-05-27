"""
用户认证系统 v2 — 多用户 + 券商绑定
==================================
功能：
1. 注册/登录/注销
2. 每个用户可绑定自己的Alpaca/IBKR Key
3. 下单、持仓、交易记录按用户隔离
4. 管理员可管理所有用户

数据文件：config/users.json
每次用户独立券商配置：config/users/{username}/broker_keys.json
"""

import os
import json
import shutil
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, session, redirect, url_for
from passlib.hash import bcrypt
from security import login_rate_limit, csrf_protect, encrypt_key, decrypt_key, log_audit, is_registration_allowed

logger = logging.getLogger("quant.auth")

bp = Blueprint("auth", __name__, url_prefix="/auth")
USERS_FILE = "config/users.json"
USERS_DIR = "config/users"
os.makedirs("config", exist_ok=True)
os.makedirs(USERS_DIR, exist_ok=True)


# ===== 用户数据管理 =====

def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_users(users: dict):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


def get_user_dir(username: str) -> str:
    """每个用户独立目录"""
    d = os.path.join(USERS_DIR, username)
    os.makedirs(d, exist_ok=True)
    return d


def get_user_broker_keys(username: str) -> dict:
    """读取用户的券商Key"""
    path = os.path.join(get_user_dir(username), "broker_keys.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_user_broker_keys(username: str, keys: dict):
    path = os.path.join(get_user_dir(username), "broker_keys.json")
    with open(path, "w") as f:
        json.dump(keys, f, indent=2)


def get_user_signals_dir(username: str) -> str:
    """每个用户独立的信号和交易记录目录"""
    d = os.path.join("signals", username)
    os.makedirs(d, exist_ok=True)
    return d


# ===== 登录状态 =====

def get_current_username() -> str:
    return session.get("user", "")


def login_required(f):
    """登录校验装饰器"""
    from functools import wraps
    from flask import redirect, url_for

    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"status": "error", "message": "请先登录"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """管理员权限装饰器"""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({"status": "error", "message": "需要管理员权限"}), 403
        return f(*args, **kwargs)
    return decorated


# ===== 路由 =====

@bp.route("/login", methods=["GET", "POST"])
@login_rate_limit
def login():
    if request.method == "GET":
        return render_template("login.html")

    data = request.json or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"status": "error", "message": "用户名和密码不能为空"})

    users = load_users()
    user = users.get(username)

    if not user:
        return jsonify({"status": "error", "message": "用户不存在"})

    if not bcrypt.verify(password, user["password"]):
        return jsonify({"status": "error", "message": "密码错误"})

    session["user"] = username
    session["role"] = user.get("role", "user")
    session["login_time"] = str(datetime.now())

    # 更新最后登录
    users[username]["last_login"] = str(datetime.now())
    save_users(users)

    log_audit("LOGIN", username, "登录成功")

    return jsonify({
        "status": "ok",
        "message": "登录成功",
        "username": username,
        "role": user.get("role", "user"),
    })


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    data = request.json or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    confirm = data.get("confirm", "")

    if not username or len(username) < 3:
        return jsonify({"status": "error", "message": "用户名至少3个字符"})
    
    # 注册白名单检查
    if not is_registration_allowed(username):
        return jsonify({"status": "error", "message": "注册未开放，请联系管理员"})
    
    if len(password) < 6:
        return jsonify({"status": "error", "message": "密码至少6个字符"})
    if password != confirm:
        return jsonify({"status": "error", "message": "两次密码不一致"})

    users = load_users()
    if username in users:
        return jsonify({"status": "error", "message": "用户已存在"})

    hashed = bcrypt.hash(password)
    users[username] = {
        "password": hashed,
        "role": "user",
        "created": str(datetime.now()),
        "last_login": None,
        "broker": "alpaca_paper",
    }
    save_users(users)

    # 创建用户目录
    get_user_dir(username)

    session["user"] = username
    session["role"] = "user"
    session["login_time"] = str(datetime.now())

    log_audit("REGISTER", username, "新用户注册")
    logger.info(f"新用户注册: {username}")
    return jsonify({"status": "ok", "message": "注册成功", "username": username})


@bp.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@bp.route("/api/current_user")
def api_current_user():
    return jsonify({
        "username": session.get("user"),
        "role": session.get("role"),
    })


# ===== 用户券商Key管理 =====

@bp.route("/api/broker_keys", methods=["GET", "POST"])
@login_required
def api_broker_keys():
    username = get_current_username()
    
    if request.method == "GET":
        keys = get_user_broker_keys(username)
        # 不暴露具体值，只显示哪些已配置
        status = {}
        for k in ["ALPACA_API_KEY_ID", "ALPACA_SECRET_KEY",
                  "IBKR_ACCOUNT_ID", "IBKR_TOKEN"]:
            status[k] = bool(keys.get(k))
        return jsonify({"status": status})
    
    # POST — 保存key
    data = request.json or {}
    keys = get_user_broker_keys(username)
    for k in ["ALPACA_API_KEY_ID", "ALPACA_SECRET_KEY",
              "IBKR_ACCOUNT_ID", "IBKR_TOKEN"]:
        if k in data:
            keys[k] = data[k]
    save_user_broker_keys(username, keys)
    return jsonify({"status": "ok", "message": "券商Key已保存"})


# ===== 管理员接口 =====

@bp.route("/api/admin/users")
@admin_required
def api_admin_users():
    users = load_users()
    result = []
    for name, info in users.items():
        result.append({
            "username": name,
            "role": info.get("role", "user"),
            "created": info.get("created", ""),
            "last_login": info.get("last_login", ""),
            "has_broker_keys": bool(get_user_broker_keys(name)),
        })
    return jsonify({"users": result})


@bp.route("/api/admin/set_role", methods=["POST"])
@admin_required
def api_admin_set_role():
    data = request.json or {}
    username = data.get("username", "")
    role = data.get("role", "user")
    
    if role not in ("user", "admin"):
        return jsonify({"status": "error", "message": "无效角色"})
    
    users = load_users()
    if username not in users:
        return jsonify({"status": "error", "message": "用户不存在"})
    
    users[username]["role"] = role
    save_users(users)
    return jsonify({"status": "ok", "message": f"{username} 角色已设为 {role}"})
