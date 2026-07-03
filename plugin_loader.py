"""
策略插件系统 — 标准接口和加载器
================================
每个策略是一个独立的 Python 包，放在 plugins/ 目录下。
系统启动时自动发现并注册，热插拔：加/删一个目录即可。

插件目录结构：
    plugins/
    ├── __init__.py          ← 加载器
    ├── strategy_vector/     ← 保守策略插件
    │   ├── __init__.py
    │   └── plugin.py        ← 必须实现 StrategyPlugin 接口
    ├── strategy_momentum/   ← 激进动量插件
    ├── intraday/            ← 日内插件
    ├── pairs_trading/       ← 配对交易插件
    ├── futures_pairs/       ← 期货套利插件
    └── wheel/               ← 轮式期权插件

每个 plugin.py 必须实现:
    class Plugin(StrategyPlugin):
        name = "strategy_name"
        def generate_signals(self) -> list[dict]: ...
        def get_info(self) -> dict: ...
"""

import importlib
import inspect
import logging
import os
import pkgutil
import sys

logger = logging.getLogger("quant.plugins")

PLUGINS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins")


# ============================================================
# 标准接口
# ============================================================

class StrategyPlugin:
    """所有策略插件必须继承此类"""

    # 策略元信息
    name: str = "unknown"           # 唯一标识，如 "conservative"
    display_name: str = ""           # 显示名称
    description: str = ""            # 说明
    version: str = "1.0.0"
    schedule: str = "daily"          # daily / intraday / manual
    enabled: bool = True

    def generate_signals(self) -> list[dict]:
        """
        生成交易信号
        返回: [{"ticker": str, "score": float, "price": float, ...}, ...]
        """
        raise NotImplementedError

    def get_info(self) -> dict:
        """返回插件信息"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
            "schedule": self.schedule,
            "enabled": self.enabled,
        }

    def on_load(self):
        """插件加载时回调（可选重写）"""
        pass

    def on_unload(self):
        """插件卸载时回调（可选重写）"""
        pass


# ============================================================
# 插件加载器
# ============================================================

class PluginLoader:
    """插件加载器——负责发现、加载、卸载插件"""

    def __init__(self):
        self._plugins: dict[str, StrategyPlugin] = {}
        self._modules: dict[str, object] = {}

    def discover(self) -> list[str]:
        """扫描 plugins/ 目录，返回发现的插件名列表"""
        if not os.path.exists(PLUGINS_DIR):
            os.makedirs(PLUGINS_DIR, exist_ok=True)
            # 创建 __init__.py
            init_file = os.path.join(PLUGINS_DIR, "__init__.py")
            if not os.path.exists(init_file):
                with open(init_file, "w") as f:
                    f.write("# 策略插件包\n")

        plugin_names = []
        for entry in os.listdir(PLUGINS_DIR):
            entry_path = os.path.join(PLUGINS_DIR, entry)
            # 每个子目录是一个插件
            if os.path.isdir(entry_path) and not entry.startswith("_") and not entry.startswith("."):
                plugin_init = os.path.join(entry_path, "__init__.py")
                plugin_file = os.path.join(entry_path, "plugin.py")
                if os.path.exists(plugin_init) or os.path.exists(plugin_file):
                    plugin_names.append(entry)
        return sorted(plugin_names)

    def load_plugin(self, plugin_name: str) -> StrategyPlugin | None:
        """加载单个插件"""
        # 把项目根目录加入 sys.path，使 plugins 包可导入
        root_dir = os.path.dirname(os.path.abspath(__file__))
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)

        try:
            plugin_path = os.path.join(PLUGINS_DIR, plugin_name)
            plugin_file = os.path.join(plugin_path, "plugin.py")
            init_file = os.path.join(plugin_path, "__init__.py")
            
            if os.path.exists(plugin_file):
                spec = importlib.util.spec_from_file_location(f"plugins.{plugin_name}.plugin", plugin_file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            elif os.path.exists(init_file):
                spec = importlib.util.spec_from_file_location(f"plugins.{plugin_name}", init_file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            else:
                mod = importlib.import_module(f"plugins.{plugin_name}")
            
            self._modules[plugin_name] = mod

            # 直接取 Plugin 属性
            PluginClass = getattr(mod, "Plugin", None)
            if PluginClass is None:
                logger.warning(f"  ⚠️ {plugin_name}: 模块中没有 Plugin 类")
                return None

            # 检查是否继承自 StrategyPlugin（用 MRO 避免跨模块同源问题）
            if not any(c.__name__ == "StrategyPlugin" and c.__module__ == "plugin_loader"
                       for c in PluginClass.__mro__):
                logger.warning(f"  ⚠️ {plugin_name}: Plugin 未继承 StrategyPlugin")
                return None

            if PluginClass.__name__ == "StrategyPlugin":
                logger.warning(f"  ⚠️ {plugin_name}: Plugin 就是基类本身")
                return None

            instance = PluginClass()
            instance.on_load()
            self._plugins[plugin_name] = instance
            logger.info(f"  ✅ 加载插件: {instance.display_name or plugin_name} v{instance.version}")
            return instance

        except Exception as e:
            logger.error(f"  ❌ {plugin_name} 加载失败: {e}", exc_info=True)
            return None

    def load_all(self) -> dict[str, StrategyPlugin]:
        """加载所有发现的插件"""
        names = self.discover()
        for name in names:
            self.load_plugin(name)
        loaded = list(self._plugins.keys())
        logger.info(f"  ✅ 已加载 {len(loaded)} 个插件: {', '.join(loaded)}")
        try:
            import signal_bus
            signal_bus.write_message("plugin_loader", "plugins_loaded", {
                "count": len(loaded), "plugins": loaded,
            })
        except:
            pass
        return self._plugins

    def unload_plugin(self, plugin_name: str):
        """卸载插件"""
        plugin = self._plugins.pop(plugin_name, None)
        if plugin:
            plugin.on_unload()
        self._modules.pop(plugin_name, None)
        logger.info(f"  🗑️ 卸载插件: {plugin_name}")

    def get_plugin(self, name: str) -> StrategyPlugin | None:
        return self._plugins.get(name)

    def get_all_plugins(self) -> list[StrategyPlugin]:
        return list(self._plugins.values())

    def get_enabled_plugins(self) -> list[StrategyPlugin]:
        return [p for p in self._plugins.values() if p.enabled]

    def run_all(self) -> dict[str, list[dict]]:
        """运行所有已启用的插件，返回 {插件名: 信号列表}"""
        results = {}
        for name, plugin in self._plugins.items():
            if not plugin.enabled:
                logger.debug(f"  ⏭️ {name} 已禁用")
                continue
            try:
                logger.info(f"  🏃 运行插件: {name}")
                signals = plugin.generate_signals()
                results[name] = signals or []
                logger.info(f"     → {len(results[name])} 条信号")
            except Exception as e:
                logger.error(f"  ❌ {name} 执行失败: {e}")
                results[name] = []
        total = sum(len(v) for v in results.values())
        try:
            import signal_bus
            signal_bus.write_message("plugin_loader", "signals_generated", {
                "plugins": list(results.keys()),
                "total_signals": total,
                "details": {k: len(v) for k, v in results.items()},
            })
        except:
            pass
        return results


# ============================================================
# 全局单例
# ============================================================

_loader = None

def get_loader() -> PluginLoader:
    global _loader
    if _loader is None:
        _loader = PluginLoader()
        _loader.load_all()
    return _loader


def load_all():
    return get_loader().load_all()


def run_all():
    return get_loader().run_all()


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    loader = PluginLoader()
    names = loader.discover()
    print(f"发现 {len(names)} 个插件: {', '.join(names)}")

    plugins = loader.load_all()
    print(f"\n已加载 {len(plugins)} 个插件:")
    for name, p in plugins.items():
        info = p.get_info()
        print(f"  {info['name']:20s} v{info['version']:8s} [{info['schedule']:8s}] {info.get('display_name', '')}")
