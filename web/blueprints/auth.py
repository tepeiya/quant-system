"""
用户认证系统 v3 — 多用户 + 数据库支持
==========================================
功能：
1. 注册/登录/注销
2. 每个用户可绑定自己的Alpaca/IBKR Key
3. 下单、持仓、交易记录按用户隔离
4. 管理员可管理所有用户
5. 支持SQLite数据库 + JSON文件双存储

数据存储：
- SQLite数据库: data/quant_system.db
- JSON文件备份: config/users.json
"""

import os
import json
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, session, redirect
import bcrypt
from security import login_rate_limit, log_audit, is_registration_allowed
from api_response import ok, err

logger = logging.getLogger("quant.auth")

bp = Blueprint("auth", __name__, url_prefix="/auth")
USERS_FILE = "config/users.json"
USERS_DIR = "config/users"
os.makedirs("config", exist_ok=True)
os.makedirs(USERS_DIR, exist_ok=True)

# 数据库支持
_db = None

def get_db():
    """获取数据库连接"""
    global _db
    if _db is None:
        try:
            from database import db as database_instance
            _db = database_instance
        except Exception as e:
            logger.warning(f"数据库连接失败: {e}")
            _db = None
    return _db


# ===== 用户数据管理 =====

def load_users() -> dict:
    """从JSON加载用户（兼容旧数据）"""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_users(users: dict):
    """保存用户到JSON（兼容旧数据）"""
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


def load_users_from_db() -> dict:
    """从数据库加载用户"""
    database = get_db()
    if database is None:
        return {}
    
    session_db = database.get_session()
    try:
        from database import User
        users = session_db.query(User).all()
        result = {}
        for u in users:
            result[u.username] = {
                "password": u.password_hash,
                "role": u.role,
                "created": u.created_at.isoformat() if u.created_at else str(datetime.now()),
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "broker": u.broker_type,
                "db_id": u.id
            }
        return result
    finally:
        session_db.close()


def save_user_to_db(username: str, user_data: dict):
    """保存用户到数据库"""
    database = get_db()
    if database is None:
        return False
    
    session_db = database.get_session()
    try:
        from database import User
        user = session_db.query(User).filter_by(username=username).first()
        if user:
            # 更新现有用户
            if "role" in user_data:
                user.role = user_data["role"]
            if "broker" in user_data:
                user.broker_type = user_data["broker"]
            if "last_login" in user_data:
                user.last_login = datetime.fromisoformat(user_data["last_login"]) if user_data["last_login"] else None
        else:
            # 创建新用户
            user = User(
                username=username,
                password_hash=user_data.get("password", ""),
                role=user_data.get("role", "user"),
                broker_type=user_data.get("broker", "alpaca_paper"),
                created_at=datetime.fromisoformat(user_data["created"]) if user_data.get("created") else datetime.now()
            )
            session_db.add(user)
        
        session_db.commit()
        return True
    except Exception as e:
        session_db.rollback()
        logger.error(f"保存用户到数据库失败: {e}")
        return False
    finally:
        session_db.close()


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
    """保存用户的券商Key"""
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
    """获取当前登录用户名"""
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
    """登录"""
    if request.method == "GET":
        return render_template("login.html")

    data = request.json or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    if not username or not password:
        return err("用户名和密码不能为空")

    # 优先从数据库读取
    users = load_users_from_db()
    
    # 如果数据库为空，尝试从JSON读取
    if not users:
        users = load_users()
    
    user = users.get(username)

    if not user:
        return err("用户不存在")

    # 检查密码
    password_hash = user.get("password", "")
    try:
        if not bcrypt.checkpw(password.encode(), password_hash.encode()):
            return err("密码错误")
    except Exception:
        return err("密码验证失败")

    # 更新最后登录时间
    user["last_login"] = str(datetime.now())
    
    # 保存到数据库和JSON
    save_user_to_db(username, user)
    save_users(users)

    session["user"] = username
    session["role"] = user.get("role", "user")
    session["login_time"] = str(datetime.now())

    log_audit("LOGIN", username, "登录成功")

    return jsonify({
        "status": "ok",
        "message": "登录成功",
        "username": username,
        "role": user.get("role", "user"),
        "data": {"username": username, "role": user.get("role", "user")}
    })


@bp.route("/register", methods=["GET", "POST"])
def register():
    """注册新用户"""
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
        return err("注册未开放，请联系管理员")
    
    if len(password) < 6:
        return err("密码至少6个字符")
    if password != confirm:
        return err("两次密码不一致")

    # 优先从数据库检查
    users = load_users_from_db()
    if not users:
        users = load_users()
    
    if username in users:
        return err("用户已存在")

    # 创建新用户
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    new_user = {
        "password": hashed,
        "role": "user",
        "created": str(datetime.now()),
        "last_login": None,
        "broker": "alpaca_paper",
    }
    
    users[username] = new_user
    
    # 同时保存到数据库和JSON
    save_user_to_db(username, new_user)
    save_users(users)

    # 创建用户目录
    get_user_dir(username)

    session["user"] = username
    session["role"] = "user"
    session["login_time"] = str(datetime.now())

    log_audit("REGISTER", username, "新用户注册")
    logger.info(f"新用户注册: {username}")
    return jsonify({
        "status": "ok",
        "message": "注册成功",
        "username": username,
        "role": "user",
        "data": {"username": username, "role": "user"}
    })


@bp.route("/logout")
def logout():
    """登出"""
    session.clear()
    return redirect("/login")


@bp.route("/api/current_user")
def api_current_user():
    """获取当前用户信息"""
    if "user" not in session:
        return err("未登录", 401)
    return ok({
        "username": session.get("user"),
        "role": session.get("role"),
    })


# ===== 用户券商Key管理 =====

@bp.route("/api/broker_keys", methods=["GET", "POST"])
@login_required
def api_broker_keys():
    """获取/保存用户的券商Key"""
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
    """获取所有用户列表"""
    # 优先从数据库读取
    users = load_users_from_db()
    if not users:
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
    """设置用户角色"""
    data = request.json or {}
    username = data.get("username", "")
    role = data.get("role", "user")
    
    if role not in ("user", "admin"):
        return jsonify({"status": "error", "message": "无效角色"})
    
    # 优先从数据库读取
    users = load_users_from_db()
    if not users:
        users = load_users()
    
    if username not in users:
        return jsonify({"status": "error", "message": "用户不存在"})
    
    users[username]["role"] = role
    
    # 保存到数据库和JSON
    save_user_to_db(username, users[username])
    save_users(users)
    
    return jsonify({"status": "ok", "message": f"{username} 角色已设为 {role}"})
