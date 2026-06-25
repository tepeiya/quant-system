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

app.config["TEMPLATES_AUTO_RELOAD"] = True

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
from security_policy import PUBLIC_PATHS
apply_security_fixes(app)

# ====== 数据库初始化 ======
try:
    from database import init_database
    init_database(with_migration=True)
    logger.info("✅ 数据库初始化完成")
except Exception as e:
    logger.warning(f"⚠️ 数据库初始化失败（功能可能受限）: {e}")

# ====== 插件系统预初始化 ======
try:
    from plugin_loader import get_loader
    # 预加载所有插件，避免第一个请求延迟
    loader = get_loader()
    logger.info(f"✅ 插件系统预初始化完成，已加载 {len(loader.get_all_plugins())} 个插件")
except Exception as e:
    logger.warning(f"⚠️ 插件系统初始化失败: {e}")


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
    
    public_paths = PUBLIC_PATHS
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


@app.route("/api/warmup", methods=["POST"])
def api_warmup():
    """手动触发数据预热一轮"""
    try:
        from warmup_data import warmup
        r = warmup(batch_size=80)
        return jsonify({"status": "ok", "message": "预热完成", "data": r})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/api/health/full")
def api_health_full():
    """全链路健康检查"""
    from datetime import datetime
    report = {
        "time": str(datetime.now()),
        "status": "ok",
        "checks": {},
        "trace_id": __import__('uuid').uuid4().hex[:12],
        "last_error_time": None
    }
    
    # 1) 登录系统
    try:
        report["checks"]["auth"] = {"ok": True, "user": session.get("user")}
    except Exception as e:
        report["checks"]["auth"] = {"ok": False, "error": str(e)}
        report["status"] = "degraded"
        report["last_error_time"] = str(datetime.now())

    # 2) 券商配置
    try:
        from broker_manager import list_brokers
        brokers = list_brokers()
        report["checks"]["brokers"] = {
            "ok": True,
            "count": len(brokers),
            "enabled": [b["id"] for b in brokers if b.get("enabled")],
            "ready": [b["id"] for b in brokers if b.get("ready")],
        }
    except Exception as e:
        report["checks"]["brokers"] = {"ok": False, "error": str(e)}
        report["status"] = "degraded"

    # 3) 数据缓存
    try:
        from data_prod import load_price_cache
        cache = load_price_cache()
        report["checks"]["data_cache"] = {"ok": True, "stocks": len(cache)}
        if len(cache) < 50:
            report["status"] = "degraded"
    except Exception as e:
        report["checks"]["data_cache"] = {"ok": False, "error": str(e)}
        report["status"] = "degraded"

    # 4) 信号文件
    try:
        import glob
        files = sorted(glob.glob("signals/signal_*.json"))
        report["checks"]["signals"] = {"ok": bool(files), "count": len(files), "latest": files[-1] if files else None}
        if not files:
            report["status"] = "degraded"
    except Exception as e:
        report["checks"]["signals"] = {"ok": False, "error": str(e)}
        report["status"] = "degraded"

    # 5) 热图接口
    try:
        from web.blueprints.heatmap import _get_data
        d = _get_data()
        report["checks"]["heatmap"] = {"ok": True, "sectors": len(d.get("sectors", []))}
    except Exception as e:
        report["checks"]["heatmap"] = {"ok": False, "error": str(e)}
        report["status"] = "degraded"

    return jsonify(report)


# ====== 一键切换纸交易/实盘 ======
@app.route("/api/switch_mode", methods=["POST"])
def api_switch_mode():
    """一键切换所有券商到纸交易或实盘模式"""
    data = request.json or {}
    target = data.get("mode", "paper")
    if target not in ("paper", "live"):
        return jsonify({"status": "error", "message": "无效模式"}), 400

    try:
        from broker_manager import load_config, save_config
        cfg = load_config()

        # 纸交易券商和实盘券商的映射
        paper_to_live = {
            "alpaca_paper": "alpaca_live",
            "alpaca_paper_intraday": "alpaca_live_intraday",
        }

        changes = []
        if target == "live":
            # 切到实盘：启用实盘券商，禁用纸交易券商
            for paper_id, live_id in paper_to_live.items():
                if paper_id in cfg:
                    cfg[paper_id]["enabled"] = False
                    changes.append(f"禁用{paper_id}")
                if live_id in cfg:
                    cfg[live_id]["enabled"] = True
                    changes.append(f"启用{live_id}")
        else:
            # 切回纸交易：启用纸交易券商，禁用实盘券商
            for paper_id, live_id in paper_to_live.items():
                if paper_id in cfg:
                    cfg[paper_id]["enabled"] = True
                    changes.append(f"启用{paper_id}")
                if live_id in cfg:
                    cfg[live_id]["enabled"] = False
                    changes.append(f"禁用{live_id}")

        save_config(cfg)
        _set_trade_mode(target)
        _log_audit("switch_mode", session.get("user", "?"), f"{target}: {'; '.join(changes)}")
        return jsonify({"status": "ok", "message": f"已切换到{'🔴 实盘' if target == 'live' else '📄 纸交易'}", "changes": changes})
    except Exception as e:
        logger.error(f"切换失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ====== 操作审计日志持久化 ======
AUDIT_LOG_FILE = "logs/operation.log"

def _log_audit(action: str, user: str, detail: str = ""):
    """记录操作日志到持久化文件"""
    try:
        from datetime import datetime
        os.makedirs("logs", exist_ok=True)
        with open(AUDIT_LOG_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {user:20s} | {action:30s} | {detail}\n")
    except:
        pass


@app.route("/api/audit_log")
def api_audit_log():
    """查看操作审计日志"""
    import os
    path = "logs/operation.log"
    if os.path.exists(path):
        with open(path) as f:
            lines = f.readlines()
        return jsonify({"logs": lines[-100:]})
    return jsonify({"logs": []})


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