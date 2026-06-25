"""
核心模块单元测试
================
测试关键模块的基本功能
"""
import unittest
import os
import sys
import json

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 创建 Flask 应用上下文（用于测试 jsonify）
from web_app import app


class TestApiResponse(unittest.TestCase):
    """测试 API 响应模块"""

    def setUp(self):
        self.app_context = app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_ok_response(self):
        from api_response import ok
        result, code = ok(message="测试成功")
        data = json.loads(result.get_data(as_text=True))
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["message"], "测试成功")
        self.assertEqual(code, 200)

    def test_err_response(self):
        from api_response import err
        result, code = err("测试失败")
        data = json.loads(result.get_data(as_text=True))
        self.assertEqual(data["status"], "error")
        self.assertIn("测试失败", data["message"])


class TestConfigCenter(unittest.TestCase):
    """测试配置中心模块"""

    def test_list_configs(self):
        # 使用绝对路径导入根目录的 config_center（避免与 blueprint 冲突）
        import importlib.util
        spec = importlib.util.spec_from_file_location("config_center_root", "/workspace/config_center.py")
        cc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cc)
        result = cc.list_configs()
        self.assertIsInstance(result, list)
        # 返回的是字典列表，检查 namespace 字段
        namespaces = [cfg.get("namespace") for cfg in result]
        core_configs = ["system", "intraday", "broker"]
        for cfg in core_configs:
            self.assertIn(cfg, namespaces)

    def test_get_config(self):
        # 使用绝对路径导入根目录的 config_center
        import importlib.util
        spec = importlib.util.spec_from_file_location("config_center_root", "/workspace/config_center.py")
        cc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cc)
        cfg = cc.get_config("system")
        self.assertIsInstance(cfg, dict)
        # 应包含核心字段
        self.assertIn("stop_loss_pct", cfg)
        self.assertIn("max_positions", cfg)


class TestSignalBus(unittest.TestCase):
    """测试信号总线模块"""

    def test_write_and_read_signal(self):
        import signal_bus
        # 写入测试信号
        test_signal = [{"ticker": "AAPL", "score": 0.85}]
        signal_bus.write_signal("test_strategy", test_signal)
        # 读取状态
        status = signal_bus.get_bus_status()
        self.assertIsInstance(status, dict)

    def test_get_recent_messages(self):
        import signal_bus
        msgs = signal_bus.get_recent_messages(10)
        self.assertIsInstance(msgs, list)


class TestPluginLoader(unittest.TestCase):
    """测试插件加载器"""

    def test_discover_plugins(self):
        from plugin_loader import PluginLoader
        loader = PluginLoader()
        names = loader.discover()
        self.assertIsInstance(names, list)
        # 应包含至少一个插件
        self.assertGreater(len(names), 0)

    def test_get_loader_singleton(self):
        from plugin_loader import get_loader
        loader1 = get_loader()
        loader2 = get_loader()
        # 应返回同一个实例
        self.assertIs(loader1, loader2)


class TestStrategyBroker(unittest.TestCase):
    """测试策略-券商映射"""

    def test_load_mapping(self):
        from strategy_broker import load_mapping
        mapping = load_mapping()
        self.assertIsInstance(mapping, dict)

    def test_set_and_get_broker(self):
        from strategy_broker import set_broker_for_strategy, get_broker_for_strategy
        # 设置测试映射
        set_broker_for_strategy("test_strategy", "test_broker")
        # 获取映射
        broker = get_broker_for_strategy("test_strategy")
        self.assertEqual(broker, "test_broker")


class TestSecurity(unittest.TestCase):
    """测试安全模块"""

    def test_csrf_token_generation(self):
        from security import generate_csrf_token
        token1 = generate_csrf_token()
        token2 = generate_csrf_token()
        # 每次生成不同的 token
        self.assertNotEqual(token1, token2)
        # token 应有足够长度
        self.assertGreater(len(token1), 20)


class TestDatabase(unittest.TestCase):
    """测试数据库模块"""

    def test_db_connection(self):
        from database import db
        session = db.get_session()
        self.assertIsNotNone(session)
        session.close()

    def test_user_model(self):
        from database import User, db
        session = db.get_session()
        # 查询用户表
        users = session.query(User).limit(1).all()
        self.assertIsInstance(users, list)
        session.close()


if __name__ == "__main__":
    # 运行测试
    unittest.main(verbosity=2)