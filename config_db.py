"""
Config DB - 配置数据库持久化模块
==============================
将 users.json / broker_config.json / intraday_config.json /
system_config.json / factor_weights.json 等配置存到 SQLite 数据库，
并提供导入导出、备份恢复功能。
"""

import json
import os
import sqlite3
import shutil
from datetime import datetime

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, "data", "config.db")
BACKUP_DIR = os.path.join(DB_DIR, "data", "backups")
CONFIG_DIR = os.path.join(DB_DIR, "config")

# 需要保护的配置文件清单
CONFIG_TABLES = {
    "users": {"file": "users.json", "pk": "username"},
    "broker_config": {"file": "broker_config.json", "pk": "broker_id"},
    "intraday_config": {"file": "intraday_config.json", "pk": None},
    "system_config": {"file": "system_config.json", "pk": None},
    "factor_weights": {"file": "factor_weights.json", "pk": None},
    "trade_mode": {"file": "trade_mode.json", "pk": None},
    "circuit_breaker": {"file": "circuit_breaker.json", "pk": None},
    "factor_ranking": {"file": "factor_ranking.json", "pk": None},
    "broker_keys": {"file": "broker_keys.json", "pk": None},
}

# ========== 初始化 ==========

def init_db():
    """创建数据库和表结构"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    c = conn.cursor()

    # 配置表 - 按 JSON 文件划分
    c.execute("""
        CREATE TABLE IF NOT EXISTS config_store (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_key TEXT NOT NULL UNIQUE,
            config_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # 配置备份历史表
    c.execute("""
        CREATE TABLE IF NOT EXISTS config_backup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_key TEXT NOT NULL,
            config_value TEXT NOT NULL,
            backup_at TEXT NOT NULL,
            reason TEXT
        )
    """)

    # 导入/导出日志
    c.execute("""
        CREATE TABLE IF NOT EXISTS import_export_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            details TEXT,
            status TEXT
        )
    """)

    conn.commit()
    conn.close()
    log_action("init", "数据库初始化完成")


def get_conn():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ========== 导入 JSON → DB ==========

def import_from_json(config_key, json_file=None):
    """从 JSON 文件导入到数据库"""
    if json_file is None:
        table_info = CONFIG_TABLES.get(config_key)
        if not table_info:
            return {"status": "error", "message": f"未知配置: {config_key}"}
        json_file = os.path.join(CONFIG_DIR, table_info["file"])

    if not os.path.exists(json_file):
        return {"status": "error", "message": f"文件不存在: {json_file}"}

    with open(json_file, "r") as f:
        data = json.load(f)

    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 先备份当前值
    c.execute("SELECT config_value FROM config_store WHERE config_key=?", (config_key,))
    row = c.fetchone()
    if row:
        c.execute(
            "INSERT INTO config_backup (config_key, config_value, backup_at, reason) VALUES (?,?,?,?)",
            (config_key, row["config_value"], now, "auto_backup_before_import")
        )

    # 写入新值
    c.execute(
        "INSERT OR REPLACE INTO config_store (config_key, config_value, updated_at) VALUES (?,?,?)",
        (config_key, json.dumps(data, ensure_ascii=False), now)
    )
    conn.commit()
    conn.close()
    log_action("import", f"导入 {config_key}")
    return {"status": "ok", "message": f"{config_key} 已导入", "updated_at": now}


def import_all():
    """从 config/ 目录导入所有 JSON 到数据库"""
    results = []
    for config_key, info in CONFIG_TABLES.items():
        json_file = os.path.join(CONFIG_DIR, info["file"])
        r = import_from_json(config_key, json_file)
        results.append(r)
    return results


# ========== 导出 DB → JSON ==========

def export_to_json(config_key):
    """从数据库导出到 JSON 文件"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT config_value FROM config_store WHERE config_key=?", (config_key,))
    row = c.fetchone()
    conn.close()

    if not row:
        return {"status": "error", "message": f"数据库中没有 {config_key}"}

    table_info = CONFIG_TABLES.get(config_key)
    if not table_info:
        return {"status": "error", "message": f"未知配置: {config_key}"}

    json_file = os.path.join(CONFIG_DIR, table_info["file"])
    data = json.loads(row["config_value"])

    with open(json_file, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    log_action("export", f"导出 {config_key}")
    return {"status": "ok", "message": f"{config_key} 已写入 {table_info['file']}"}


def export_all():
    """从数据库恢复所有 JSON 配置文件"""
    results = []
    for config_key in CONFIG_TABLES:
        r = export_to_json(config_key)
        results.append(r)
    return results


# ========== 读写接口 ==========

def get_config(config_key):
    """从数据库读取配置"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT config_value FROM config_store WHERE config_key=?", (config_key,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row["config_value"])
    return None


def set_config(config_key, data):
    """写入配置到数据库"""
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 备份旧值
    c.execute("SELECT config_value FROM config_store WHERE config_key=?", (config_key,))
    row = c.fetchone()
    if row:
        c.execute(
            "INSERT INTO config_backup (config_key, config_value, backup_at, reason) VALUES (?,?,?,?)",
            (config_key, row["config_value"], now, "auto_backup_before_set")
        )

    c.execute(
        "INSERT OR REPLACE INTO config_store (config_key, config_value, updated_at) VALUES (?,?,?)",
        (config_key, json.dumps(data, ensure_ascii=False), now)
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "updated_at": now}


# ========== 备份与恢复 ==========

def create_backup(label=""):
    """创建完整备份（生成 .json 快照文件）"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"config_backup_{ts}_{label}.json")

    # 收集所有配置
    snapshot = {}
    for config_key, info in CONFIG_TABLES.items():
        json_path = os.path.join(CONFIG_DIR, info["file"])
        if os.path.exists(json_path):
            with open(json_path, "r") as f:
                snapshot[config_key] = json.load(f)

    snapshot["__meta__"] = {
        "backup_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "label": label,
        "version": "1.0"
    }

    with open(backup_file, "w") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    # 同时备份数据库文件
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, os.path.join(BACKUP_DIR, f"config_db_{ts}_{label}.db"))

    log_action("backup", f"创建备份 {label} -> {backup_file}")
    return {"status": "ok", "file": backup_file, "timestamp": ts}


def restore_from_backup(backup_file):
    """从备份文件恢复所有配置"""
    if not os.path.exists(backup_file):
        return {"status": "error", "message": f"备份文件不存在: {backup_file}"}

    with open(backup_file, "r") as f:
        snapshot = json.load(f)

    meta = snapshot.pop("__meta__", {})
    results = []

    for config_key, data in snapshot.items():
        if config_key in CONFIG_TABLES:
            json_path = os.path.join(CONFIG_DIR, CONFIG_TABLES[config_key]["file"])
            with open(json_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            set_config(config_key, data)
            results.append(f"{config_key}: ✓")

    log_action("restore", f"从备份恢复: {backup_file}")
    return {"status": "ok", "results": results, "backup_at": meta.get("backup_at")}


def list_backups():
    """列出所有备份"""
    if not os.path.exists(BACKUP_DIR):
        return []
    files = sorted(os.listdir(BACKUP_DIR), reverse=True)
    backups = []
    for f in files:
        path = os.path.join(BACKUP_DIR, f)
        size = os.path.getsize(path)
        mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
        backups.append({"file": f, "size": size, "mtime": mtime, "path": path})
    return backups


# ========== 日志 ==========

def log_action(action, details, status="ok"):
    """记录操作日志"""
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO import_export_log (action, timestamp, details, status) VALUES (?,?,?,?)",
            (action, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), details, status)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_history(config_key=None, limit=50):
    """获取操作历史"""
    conn = get_conn()
    c = conn.cursor()
    if config_key:
        c.execute(
            "SELECT * FROM config_backup WHERE config_key=? ORDER BY id DESC LIMIT ?",
            (config_key, limit)
        )
    else:
        c.execute("SELECT * FROM config_backup ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_logs(limit=20):
    """获取操作日志"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM import_export_log ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ========== 启动时自动执行 ==========

def ensure_initialized():
    """确保数据库已初始化，从现有 JSON 导入"""
    init_db()

    # 检查是否已有数据
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM config_store")
    count = c.fetchone()[0]
    conn.close()

    if count == 0:
        print("[config_db] 首次初始化，从 JSON 导入配置...")
        results = import_all()
        for r in results:
            status = "✓" if r["status"] == "ok" else "✗"
            print(f"  [{status}] {r['message']}")

    # 创建当日备份（每天一次）
    today = datetime.now().strftime("%Y%m%d")
    existing = [b for b in list_backups() if today in b["file"] and "daily" in b["file"]]
    if not existing:
        create_backup("daily")
        print(f"[config_db] 每日备份已创建")
    else:
        print(f"[config_db] 今日已有备份，跳过")


# ========== CLI 入口 ==========

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python config_db.py <命令> [参数]")
        print("   init          初始化数据库")
        print("   import        从 JSON 导入所有配置")
        print("   export        从数据库导出到 JSON")
        print("   backup [标签]  创建备份")
        print("   list-backups  列出备份")
        print("   restore <文件> 从备份恢复")
        print("   history       查看备份历史")
        print("   logs          查看操作日志")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "init":
        ensure_initialized()
        print("✅ 数据库已初始化")

    elif cmd == "import":
        r = import_all()
        for res in r:
            print(f"  [{res['status']}] {res['message']}")

    elif cmd == "export":
        r = export_all()
        for res in r:
            print(f"  [{res['status']}] {res['message']}")

    elif cmd == "backup":
        label = sys.argv[2] if len(sys.argv) > 2 else "manual"
        r = create_backup(label)
        print(f"✅ 备份已创建: {r['file']}")

    elif cmd == "list-backups":
        backups = list_backups()
        if not backups:
            print("📭 暂无备份")
        else:
            for b in backups:
                print(f"  {b['mtime']}  {b['file']}  ({b['size']} bytes)")

    elif cmd == "restore":
        if len(sys.argv) < 3:
            print("❌ 请指定备份文件")
            sys.exit(1)
        r = restore_from_backup(sys.argv[2])
        print(f"  [{r['status']}] 恢复结果: {r.get('results', r.get('message', ''))}")

    elif cmd == "history":
        key = sys.argv[2] if len(sys.argv) > 2 else None
        rows = get_history(key)
        for r in rows:
            print(f"  #{r['id']} {r['backup_at']} {r['config_key']} - {r.get('reason','')}")

    elif cmd == "logs":
        logs = get_logs()
        for l in logs:
            print(f"  [{l['id']}] {l['timestamp']} {l['action']}: {l['details']}")

    else:
        print(f"❌ 未知命令: {cmd}")
