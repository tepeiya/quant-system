# 📊 M+ 量化系统 — Multi-Factor Momentum+

模块化多策略量化交易系统，支持**插件化策略**、**信号总线**、**统一执行器**、**Web面板**、**全自动交易守护进程**、**异步任务队列**、**监控告警体系**。

---

## 🏗️ 系统架构

```
📡 数据服务  →  🧩 策略插件(5个)  →  📨 信号总线  →  💹 统一执行器  →  🔌 券商接口
                          ↑                          ↑
                    ⛏️ 因子矿工(31个因子)       🛡️ 风控检查(3层)
                    🧬 因子进化(IC调权重)        📝 订单记录
                          ↓
                    📊 异步任务队列  →  📈 监控告警
```

### 五大插件

| 插件 | 调度 | 说明 |
|---|---|---|
| ⛏️ **因子矿工** | 每日 | 计算31个因子IC排名，找出当前最有效的因子 |
| 🧬 **因子进化** | 每日 | 根据IC自动调整因子权重 |
| 🛡️ **保守策略** | 每日 | 多因子综合评分选股（动量43%+质量25%+趋势12%+价值8%+低波6%+量比6%） |
| 🚀 **激进动量** | 每日 | 纯动量排名策略（12/6/3月加权） |
| ⚡ **日内交易** | 盘中 | 实时动量扫描+ATR自适应止盈止损+移动止损+单日熔断，收盘前清仓 |

---

## 🚀 快速部署（5分钟）

### 前置要求

| 项目 | 说明 |
|---|---|
| **服务器** | Linux x86_64 / aarch64，256MB+ 内存，2GB+ 磁盘 |
| **Docker** | 需要 Docker CE 20+（没有的话用下面的脚本安装） |
| **网络** | 能访问 `api.deepseek.com` 或 OpenAI 等境外 API |
| **Alpaca 账户** | 免费申请，获取 Paper Trading API Key |

### 一键部署

```bash
# 1. 安装 Docker（如果没有）
curl -fsSL https://get.docker.com | sh

# 2. 拉取项目
git clone https://github.com/tepeiya/quant-system.git m-plus
cd m-plus

# 3. 配置环境变量（Alpaca API Key）
#    去 https://alpaca.markets 注册 → Paper Trading → 复制 Key
cat > .env << EOF
ALPACA_API_KEY_ID=your_paper_key_id
ALPACA_SECRET_KEY=your_paper_secret
ALPACA_INTRADAY_KEY_ID=your_intraday_key_id
ALPACA_INTRADAY_SECRET=your_intraday_secret
CONSERVATIVE_CAP_RATIO=0.5
MOMENTUM_CAP_RATIO=0.5
EOF

# 4. 构建并启动
docker compose up -d

# 5. 打开浏览器
#    访问 http://你的服务器IP:8765
#    默认账号: admin / admin123
```

### 手动部署（无 Docker）

```bash
# 1. 安装 Python 3.10+
apt install python3 python3-pip -y

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
#    编辑 broker_keys.py 或在环境变量中设置
#    ALPACA_API_KEY_ID / ALPACA_SECRET_KEY

# 4. 数据预热（下载行情数据，视网络情况5-30分钟）
python3 data_service.py --full

# 5. 启动 Web 面板
python3 web_app.py

# 6. 启动自动交易守护进程
python3 daemon.py
```

---

## 📖 首次使用指南

### 第一步：登录系统

打开 `http://你的服务器IP:8765`，用默认账号登录：
- **用户名:** `admin`
- **密码:** `admin123`

> ⚠️ 首次登录后请尽快到 `配置中心 → users` 修改密码。

### 第二步：配置券商

导航 **🔌 券商管理** → 确认 Alpaca 纸交易显示 ✅ **就绪**

如果显示 ⚠️ **未配置**，说明环境变量没设对：
- 在服务器上执行 `export ALPACA_API_KEY_ID=你的Key`
- 或到 `配置中心 → broker_keys` 直接填写

### 第三步：数据预热

导航 **🛠️ 运维中心** → 点 **📥 数据预热**

等待5-30分钟（下载600只股票的历史行情+技术指标）。完成后页面会显示完成日志。

### 第四步：运行回测

运维中心 → 点 **🎯 事件驱动回测**

等1-2分钟，刷新页面看结果面板。正常应该显示：
- 总收益 +20~40%（2023-2026区间）
- 夏普比率 0.5~1.0

> 💡 日内策略回测已升级到 v2 版本，修复了未来函数偏差，使用 T-1 日选股 + T 日开盘买入，结果更真实。

### 第五步：配置 AI 辅助（可选）

导航 **⚙️ 策略参数** → 拉到 **🤖 AI 辅助选股**

```
提供商: OpenAI 兼容
API Base URL: https://api.deepseek.com/v1
API Key: 你的 DeepSeek Key（免费注册）
模型: deepseek-v4-flash
```

点保存，然后到运维中心点 **🏆 生成信号**，信号页面的候选股会显示 AI 分析理由。

### 第六步：启动自动交易

运维中心 → 点 **▶️ 启动 daemon**

daemon 会自动按美东时间执行：
```
09:00  数据更新
09:30  因子矿工 → 因子进化 → 策略信号
09:35  执行器自动下单
盘中   日内策略每30分钟扫描（10:00-14:30入场）
15:50  日内策略强制清仓
16:00  收盘记录权益 + 推送日报
```

> 当前是 **纸交易模式**，不会动真钱。页面底部有 **交易模式** 切换开关。

---

## 🌐 Web 面板导航

```
📊 行情数据 — 大盘行情 / 宏观经济 / 市场热图 / 因子分析
🧠 策略中心 — 选股信号 / 当前持仓 / 配对交易 / 轮动策略 / 日内交易
💹 交易管理 — 策略插件 / 执行器 / 订单记录 / 交易历史 / 信号历史 / 手动下单
🔧 系统管理 — 数据服务 / 信号总线 / 券商管理 / 配置中心 / 策略参数 / 资金分配 / 运维中心
```

---

## ⚡ 日内交易策略

日内策略经过全面优化，8项核心改进：

| 优化项 | 优化前 | 优化后 |
|--------|--------|--------|
| 止盈止损比 | 1.7:1 (2.5x/1.5x) | **2.1:1** (3.2x/1.5x) |
| 移动止损 | ❌ 默认关闭 | ✅ 默认开启，盈利达1x ATR启动 |
| 单日亏损保护 | ❌ 无 | ✅ 3%熔断，触发强制清仓 |
| 入场时间 | ❌ 无限制 | ✅ 10:00-14:30 最佳窗口 |
| 回测真实性 | ⚠️ 未来函数偏差 | ✅ T-1选股/T日开盘买 |
| 评分体系 | ⚠️ 原始分不可比 | ✅ z-score归一化0-100分 |
| 交易成本 | 0.1%/单边 | **0.3%/单边**（佣金+滑点+价差） |
| 代码质量 | ⚠️ 重复代码 | ✅ 已清理 |

### 三层风控机制

```
第一层：云端止损单（Alpaca服务器端，最可靠）
第二层：本地移动止损（盈利达1x ATR后追踪）
第三层：单日亏损熔断（3%自动清仓，保命机制）
```

---

## 🔧 日常运维

### 每天开盘前
```bash
# 查看 daemon 是否在运行
docker ps | grep m-plus

# 查看最近一次交易状态
curl http://localhost:8765/ops/api/status
```

### 手动更新数据
```bash
# 增量更新（快）
python3 data_service.py --once

# 全量更新（慢，30天数据）
python3 data_service.py --full
```

### 查看日志
```bash
# Web 访问
http://你的IP:8765/bus      # 信号总线（查看策略心跳）
http://你的IP:8765/orders   # 订单记录（查看成交历史）
http://你的IP:8765/monitor  # 监控中心（系统状态+告警）
http://你的IP:8765/tasks    # 任务管理（异步任务进度）

# 命令行
docker logs m-plus-m-plus-1 --tail 50
```

### 任务管理

系统支持异步任务队列，可在 **任务管理** 页面查看：
- 回测任务（事件驱动回测）
- 数据预热任务
- 压力测试任务
- 策略信号生成任务

---

## 31个因子一览

| 类别 | 因子 | 来源 |
|---|---|---|
| 📈 动量(9个) | 5/10/21/63/126/252日动量、动量加速度、价格到SMA20/50距离 | 行情数据 |
| 📊 趋势(4个) | SMA20/50/200交叉、趋势强度 | 行情数据 |
| 📉 波动(4个) | ATR、波动率、波动率比、ATR Z-Score | 行情数据 |
| 🔗 相关(4个) | 与SPY的20/60日相关性、Beta、RSI | 行情数据 |
| 📶 量价(3个) | 量比1日/20日、量价比 | 行情数据 |
| 💰 资金流(3个) | 主力净流入强度、最新流入、趋势 | 东财 |
| 📰 期权(3个) | Put/Call量比、持仓比、隐含波动率 | Yahoo |
| 📋 基本面(3个) | 营收增长、利润率、负债率 | 东财 |

---

## 🔐 安全

- CSRF Token 全面保护（所有POST请求）
- Session 24小时过期
- 登录限速防暴力破解
- API Key AES-256加密存储
- 实盘/纸盘一键切换（底部导航栏）
- 输入参数验证（防注入、限大小）
- 审计日志记录

---

## ⚙️ 配置说明

### 环境变量

| 变量 | 说明 | 必填 |
|---|---|---|
| `ALPACA_API_KEY_ID` | Alpaca 纸交易 Key | ✅ |
| `ALPACA_SECRET_KEY` | Alpaca 纸交易 Secret | ✅ |
| `ALPACA_INTRADAY_KEY_ID` | 日内专用 Key | 日内交易需要 |
| `ALPACA_INTRADAY_SECRET` | 日内专用 Secret | 日内交易需要 |
| `ALPACA_LIVE_KEY_ID` | 实盘 Key | 实盘交易需要 |
| `ALPACA_LIVE_SECRET` | 实盘 Secret | 实盘交易需要 |
| `CONSERVATIVE_CAP_RATIO` | 保守策略资金比例(默认0.5) | 可选 |
| `MOMENTUM_CAP_RATIO` | 激进策略资金比例(默认0.5) | 可选 |

### 日内策略核心参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `stop_loss_atr_multiple` | 1.5 | 止损 ATR 倍数 |
| `take_profit_atr_multiple` | 3.2 | 止盈 ATR 倍数 |
| `trailing_stop_enabled` | true | 是否启用移动止损 |
| `trailing_stop_atr_multiple` | 0.8 | 移动止损追踪幅度 |
| `trailing_stop_activation_atr` | 1.0 | 移动止损启动门槛（盈利达x ATR） |
| `max_daily_loss_pct` | 3.0 | 单日最大亏损百分比（熔断） |
| `entry_start_time` | 10:00 | 最早入场时间 |
| `entry_end_time` | 14:30 | 最晚入场时间 |
| `close_time` | 15:50 | 收盘清仓时间 |
| `max_positions` | 5 | 最大持仓数 |

所有配置也可以在 **Web面板 → 配置中心** 中直接修改。

---

## 🧪 测试

```bash
# 运行核心模块单元测试
python3 test_core.py

# 运行专业套件测试
python3 test_professional_suite.py

# 运行风控测试
python3 test_risk_manager.py

# 运行 Bug 修复测试
python3 test_bugfixes.py
```

---

## 🐳 Docker Compose

```yaml
services:
  m-plus:
    build: .
    ports:
      - "8765:8765"
    environment:
      - ALPACA_API_KEY_ID=${ALPACA_API_KEY_ID}
      - ALPACA_SECRET_KEY=${ALPACA_SECRET_KEY}
      - ALPACA_INTRADAY_KEY_ID=${ALPACA_INTRADAY_KEY_ID}
      - ALPACA_INTRADAY_SECRET=${ALPACA_INTRADAY_SECRET}
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./data_cache:/app/data_cache
      - ./signals:/app/signals
      - ./logs:/app/logs
      - ./tasks:/app/tasks
    restart: unless-stopped
```

---

## 📄 License

MIT