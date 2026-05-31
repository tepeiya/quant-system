"""
量化系统 Web 面板 - 主入口
==========================
架构：Flask + Blueprint 模块化
每个功能模块一个 blueprint，独立文件，互不影响。

添加新功能步骤：
  1. 在 web/blueprints/ 下新建 xxx.py（继承 Blueprint）
  2. 在 web/templates/ 下建对应的 html
  3. 在 register_blueprints() 里注册

启动：python3 web_app.py
访问：http://localhost:8765
"""

import os
import sys
import logging
from pathlib import Path

from flask import Flask, render_template, session, request, jsonify, redirect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quant.web")

# 确保目录存在
Path("web/blueprints").mkdir(parents=True, exist_ok=True)
Path("web/templates").mkdir(parents=True, exist_ok=True)
Path("web/static/css").mkdir(parents=True, exist_ok=True)
Path("web/static/js").mkdir(parents=True, exist_ok=True)

sys.path.insert(0, "web/blueprints")

app = Flask(__name__,
    template_folder="web/templates",
    static_folder="web/static",
    static_url_path="/static")

# Session密钥
import secrets
# 从文件读取持久化 secret_key，重启后不丢失
_secret_key_file = "config/secret_key.txt"
if os.path.exists(_secret_key_file):
    with open(_secret_key_file) as f:
        app.secret_key = f.read().strip()
else:
    app.secret_key = secrets.token_urlsafe(32)
    os.makedirs("config", exist_ok=True)
    with open(_secret_key_file, "w") as f:
        f.write(app.secret_key)

# ====== 安全加固 ======
from security import apply_security_fixes, log_audit
apply_security_fixes(app)


def login_required(f):
    """未登录则跳转登录页"""
    from functools import wraps
    from flask import redirect, url_for, request

    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            if request.path.startswith("/api/") or request.is_json:
                from flask import jsonify
                return jsonify({"status": "error", "message": "请先登录"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


def register_blueprints():
    """自动注册所有 blueprint 模块
    新增功能时，在 web/blueprints/ 下新建文件即可自动加载"""
    import importlib
    bp_dir = Path("web/blueprints")
    # 加载所有蓝图
    # auth blueprint不保护，其他蓝色print不被保护——用全局before_request拦截
    for f in sorted(bp_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        module_name = f"web.blueprints.{f.stem}"
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "bp"):
                app.register_blueprint(mod.bp)
                logger.info(f"  ✅ 已加载: {f.stem}")
        except Exception as e:
            logger.warning(f"  ⚠️ {f.stem} 加载失败: {e}")


# 全局登录拦截
@app.before_request
def check_login():
    """访问任何业务页面/API前检查登录（auth模块放行）"""
    from flask import request, redirect, url_for
    path = request.path
    
    public_paths = ["/login", "/register", "/static/", "/logout",
                    "/auth/login", "/auth/register", "/auth/logout",
                    "/api/trade_mode", "/brokers/", "/settings/api/"]
    if any(path.startswith(p) for p in public_paths):
        return None
    
    if "user" not in session:
        if path.startswith("/api/") or request.is_json:
            return jsonify({"status": "error", "message": "请先登录"}), 401
        return redirect("/auth/login")
    
    return None


@app.route("/")
def index():
    if "user" not in session:
        return render_template("login.html")
    return render_template("base.html")


@app.route("/login")
def login_redirect():
    return render_template("login.html")


@app.route("/register")
def register_redirect():
    return render_template("register.html")


# ====== 交易模式切换 ======
import json
TRADE_MODE_FILE = "config/trade_mode.json"

def _get_trade_mode() -> str:
    if os.path.exists(TRADE_MODE_FILE):
        with open(TRADE_MODE_FILE) as f:
            return json.load(f).get("mode", "paper")
    return "paper"

def _set_trade_mode(mode: str):
    os.makedirs("config", exist_ok=True)
    with open(TRADE_MODE_FILE, "w") as f:
        json.dump({"mode": mode}, f)

@app.route("/api/trade_mode", methods=["GET", "POST"])
def api_trade_mode():
    if request.method == "GET":
        return jsonify({"mode": _get_trade_mode()})
    data = request.json or {}
    mode = data.get("mode", "paper")
    if mode not in ("paper", "live"):
        return jsonify({"error": "无效模式"}), 400
    _set_trade_mode(mode)
    return jsonify({"mode": mode, "message": f"已切换到{'纸交易' if mode == 'paper' else '实盘'}"})


# ====== 启动 ======
# 自动注册所有blueprint
register_blueprints()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    print(f"\n{'='*50}")
    print(f"  🌐 量化系统 Web 面板")
    print(f"  {os.path.basename(__file__)}")
    print(f"{'='*50}")
    print(f"  启动地址: http://0.0.0.0:{port}")
    print(f"{'='*50}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)