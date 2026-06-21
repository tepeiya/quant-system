# 📊 M+ 量化系统 — Multi-Factor Momentum+

模块化多策略量化交易系统，支持**插件化策略**、**信号总线**、**统一执行器**、**Web面板**、**全自动交易守护进程**。

---

## 🏗️ 系统架构

```
📡 数据服务  →  🧩 策略插件(5个)  →  📨 信号总线  →  💹 统一执行器  →  🔌 券商接口
                          ↑                          ↑
                    ⛏️ 因子矿工(31个因子)       🛡️ 风控检查
                    🧬 因子进化(IC调权重)        📝 订单记录
```

### 五大插件

| 插件 | 调度 | 说明 |
|---|---|---|
| ⛏️ **因子矿工** | 每日 | 计算31个因子IC排名，找出当前最有效的因子 |
| 🧬 **因子进化** | 每日 | 根据IC自动调整因子权重 |
| 🛡️ **保守策略** | 每日 | 多因子综合评分选股（动量43%+质量25%+趋势12%+价值8%+低波6%+量比6%） |
| 🚀 **激进动量** | 每日 | 纯动量排名策略（12/6/3月加权） |
| ⚡ **日内交易** | 盘中 | 实时动量扫描+止盈止损+移动止损，收盘前清仓 |

### 31个因子（因子矿工）

| 类别 | 因子 | 来源 |
|---|---|---|
| 📈 动量(9个) | 5/10/21/63/126/252日动量、动量加速度、价格到SMA20/50距离 | 行情数据 |
| 📊 趋势(4个) | SMA20/50/200交叉、趋势强度 | 行情数据 |
| 📉 波动(4个) | ATR、波动率、波动率比、ATR Z-Score | 行情数据 |
| 🔗 相关(4个) | 与SPY的20/60日相关性、Beta、RSI | 行情数据 |
| 📶 量价(3个) | 量比1日/20日、量价比 | 行情数据 |
| 💰 **资金流(3个)** | 主力净流入强度、最新流入、趋势 | **东财** |
| 📰 **期权(3个)** | Put/Call量比、持仓比、隐含波动率 | **Yahoo** |
| 📋 **基本面(3个)** | 营收增长、利润率、负债率 | **东财** |

---

## 🔧 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 首次运行：数据预热
python3 data_service.py --full

# 启动Web面板
python3 web_app.py

# 启动自动交易守护进程
python3 daemon.py

# 查看所有插件
python3 plugin_loader.py
```

访问 `http://localhost:8765` 登录Web面板。

---

## 🌐 Web 面板导航

```
📊 行情 — 大盘 / 宏观 / 热图 / 因子
🧠 策略 — 信号 / 持仓 / 配对 / 轮式 / 日内
💹 交易 — 策略插件 / 执行器 / 订单记录 / 交易历史 / 信号历史 / 手动下单
🔧 系统 — 数据服务 / 信号总线 / 券商管理 / 配置中心 / 策略参数 / 资金分配 / 运维
```

---

## 🔁 自动交易流程

```
美东时间 09:00  数据服务增量更新
         09:30  因子矿工(IC排名) → 因子进化(调权重) → 保守/动量策略(生成信号)
         09:35  统一执行器(读总线→风控→下单)
    盘中每15min  日内策略(扫描→执行)
    盘中持续     止损监控
         16:00  收盘记录权益→推送日报→数据备份
```

---

## ⚙️ 配置

所有配置在 **Web面板 → 配置中心** 统一管理：

| 配置项 | 说明 |
|---|---|
| `config/system_config.json` | 策略参数（止损/仓位/RSI/熔断等80+参数） |
| `config/intraday_config.json` | 日内交易参数 |
| `config/broker_config.json` | 券商账户配置 |
| `config/factor_weights.json` | 因子权重（因子进化自动调整） |
| `config/trade_mode.json` | 纸盘/实盘切换 |
| `config/strategy_broker_map.json` | 策略→券商绑定（插件页面配置） |

### 环境变量

| 变量 | 说明 |
|---|---|
| `ALPACA_API_KEY_ID` / `ALPACA_SECRET_KEY` | Alpaca 纸交易 Key |
| `ALPACA_INTRADAY_KEY_ID` / `ALPACA_INTRADAY_SECRET` | Alpaca 日内专用 Key |
| `ALPACA_LIVE_KEY_ID` / `ALPACA_LIVE_SECRET` | Alpaca 实盘 Key（慎用） |
| `CONSERVATIVE_CAP_RATIO` / `MOMENTUM_CAP_RATIO` | 双策略资金分配比例 |

---

## 🐳 Docker 部署

```bash
docker build -t m-plus .
docker run -d --name m-plus -p 8765:8765 \
  -e ALPACA_API_KEY_ID=your_key \
  -e ALPACA_SECRET_KEY=your_secret \
  m-plus
```

---

## 🗄️ 数据持久化

| 存储 | 路径 | 说明 |
|---|---|---|
| SQLite 配置库 | `data/config.db` | 所有配置的数据库备份 |
| SQLite 信号总线 | `data/signal_bus.db` | 策略→执行器的消息队列 |
| JSON 配置 | `config/*.json` | 向下兼容的配置文件 |
| 行情缓存 | `data_cache/*.pkl` | 股票历史行情+技术指标 |
| 信号日志 | `signals/*.json` | 每日信号/交易记录 |
| 每日备份 | `data/backups/*` | 配置自动每日备份 |

---

## 🔐 安全

- CSRF Token 全面保护
- Session 24小时过期
- 登录限速防暴力破解
- API Key AES-256加密存储
- 实盘/纸盘一键切换（Web面板底部）

---

## 📄 License

MIT
