# 📊 M+ 量化系统 — Multi-Factor Momentum+

多因子动量选股量化交易系统，支持 **双策略独立运行**、**零鉴权全球数据源**、**Web 面板**、**全自动交易守护进程**。

> 🚀 **激进策略回测 +124.3%** · 🛡️ **保守策略回测 +46.0%** · 📡 **新浪/东财/Yahoo 零鉴权**

---

## 🚀 一键部署（VPS / Docker）

### 方式一：一键脚本（推荐）

```bash
curl -sSL https://raw.githubusercontent.com/tepeiya/quant-system/main/install.sh | bash
```
自动安装 Docker → 克隆代码 → 引导填写 API Key → 构建镜像 → 启动

### 方式二：手动 Docker

```bash
git clone https://github.com/tepeiya/quant-system.git
cd quant-system
cp env_template .env   # 编辑 .env 填入 API Key
docker compose up -d
```

访问 `http://<VPS_IP>:8765`，默认管理员 `admin` / `admin123`。

---

## 📡 数据源（零鉴权，无需 API Key）

系统整合了 [global-stock-data](https://github.com/simonlin1212/global-stock-data) 的全栈数据层，5 个免费数据源：

| 数据源 | 鉴权 | 覆盖 | 用途 |
|--------|------|------|------|
| 新浪财经 | ❌ 无需 | 美股行情 + K线（回溯至1984） | 主力数据源 |
| 东方财富 | ❌ 无需 | 行情 + 全市场列表 + 基本面 + 资金流 | 股票池、交易数据 |
| 腾讯财经 | ❌ 无需 | 美股71字段 + 港股78字段 | 备用行情 |
| Yahoo Finance | 自动 crumb | K线 + 期权链 + 财务数据 | 回退/期权 |
| SEC EDGAR | ❌ 无需(需UA) | Filing + XBRL | 财报深度分析 |

> 全部直连 HTTP API，无需 API Key，无需第三方封装。国内服务器也能直接访问新浪/东财。

---

## 🧩 双策略体系

两套策略**完全独立运行**，互不影响，通过资金分配比例共存。

### 🛡️ 保守策略（`strategy_vector.py`）

| 指标 | 数值 |
|------|------|
| 选股 | 动量 + 质量因子 + 趋势 + 大盘择时 |
| 持仓 | 8-10 只 |
| 调仓 | 每日 |
| 回测收益 | **+46.0%** |
| 年化 | **+6.0%** |
| 最大回撤 | **-16.1%** |
| 适合 | 震荡市 / 熊市 |

### 🚀 激进策略（`strategy_momentum.py`）

| 指标 | 数值 |
|------|------|
| 选股 | 纯动量（12-1月动量排名） |
| 持仓 | 15 只等权 |
| 调仓 | 每月 |
| 回测收益 | **+124.3%** |
| 年化 | **+13.3%** |
| 最大回撤 | **-22.7%** |
| 适合 | 牛市 / 趋势市 |

### 💰 资金分配

在 Web 设置页面（`/settings/`）用滑块调整两策略资金比例，支持 0-100%，合计不超过 100%，剩余自动留作现金缓冲。

---

## 📋 功能清单

### Web 面板

| 页面 | 说明 |
|:----|:------|
| 📈 大盘 | 总权益、现金、持仓、资金曲线 |
| 🏆 信号 | 因子评分 Top10、买入候选 |
| 📋 持仓 | 持仓明细、PnL |
| 🔥 热图 | 板块动量热力图 |
| 🛒 下单 | 手动交易界面 |
| ⚙️ 设置 | 策略参数 + 双策略资金分配滑块 |
| 🛠️ 运维 | 一键数据预热、回测、信号生成、启动/停止自动交易 |

### 策略引擎

- **双策略并行**：保守（动量+质量+择时）+ 激进（纯动量不择时）
- **4态大盘择时**：多头 / 震荡 / 过热 / 熊市
- **ATR动态风控**：根据波动率调整止损和仓位
- **S&P 500 全量回测**：支持 300+ 只股票的向量化回测

### 自动交易守护进程

```bash
# 启动自动交易
python3 daemon.py

# 每日流程（自动执行）
09:00  数据增量更新
09:30  生成保守策略信号 + 激进策略信号
09:35  保守策略调仓 + 激进策略调仓
盘中   每5分钟止损监控
```

---

## ⚙️ 环境变量

```bash
# --- 必填 ---
ALPACA_API_KEY_ID=       # Alpaca Key（纸交易/实盘）
ALPACA_SECRET_KEY=       # Alpaca Secret

# --- 可选 ---
CONSERVATIVE_CAP_RATIO=0.5  # 保守策略资金比例（默认50%）
MOMENTUM_CAP_RATIO=0.5      # 激进策略资金比例（默认50%）
TIINGO_API_KEY=             # Tiingo数据源（备用）
FRED_API_KEY=               # FRED宏观数据
PUSHPLUS_TOKEN=             # 微信推送

# 国内镜像代理（国内服务器访问 Yahoo 用）
# https_proxy=http://127.0.0.1:7890
```

---

## 🏗️ 项目结构

```
quant-system/
├── web_app.py                   # Web面板入口
├── daemon.py                    # 双策略自动交易守护进程
├── install.sh                   # VPS一键部署脚本
├── Dockerfile / docker-compose.yml
│
├── strategy_vector.py           # 🛡️ 保守策略引擎
├── strategy_momentum.py         # 🚀 激进策略引擎
├── paper_trader.py              # 保守策略执行器
├── paper_trader_momentum.py     # 激进策略执行器
│
├── data_global.py               # 🌐 全球数据层（新浪/东财/Yahoo）
├── data_prod.py                 # 数据生产（集成 data_global）
├── warmup_full.py               # S&P 500 全量数据预热
│
├── broker_manager.py            # 券商接口（Alpaca/IBKR）
├── factor_learner.py            # 因子自动进化
├── wheel_strategy.py            # 轮式期权策略
├── pairs_trading.py             # 配对交易
├── performance_attribution.py   # 绩效归因
│
├── config/                      # 配置文件
├── signals/                     # 信号与交易记录
├── data_cache/                  # 数据缓存
├── web/
│   ├── blueprints/              # Web API 蓝图
│   ├── templates/               # 页面模板
│   └── static/                  # 静态资源
└── logs/                        # 运行日志
```

---

## 🧪 常用管理命令

```bash
# 一键部署
bash install.sh

# Docker 管理
docker compose logs -f        # 查看日志
docker compose restart        # 重启
docker compose down           # 停止

# 数据预热（下载 S&P 500 全部股票）
python3 warmup_full.py

# 生成今日信号
python3 daily_signal.py              # 保守策略
python3 strategy_momentum.py --generate  # 激进策略

# 全量回测
python3 main_final.py                # 保守策略
python3 strategy_momentum.py             # 激进策略

# 运维中心（Web 面板）
# 访问 http://<IP>:8765/ops/
```

---

## 🖥️ 推荐部署配置

| 配置 | 最低 | 推荐 |
|------|------|------|
| CPU | 1 核 | **2 核** |
| 内存 | 1 GB | **2-4 GB** |
| 存储 | 5 GB | **10 GB** |
| 网络 | 能连外网 | 国内 VPS（阿里云/腾讯云）直连新浪 |

---

## 📄 许可证

AGPL v3

> 数据来源：新浪财经 · 东方财富 · 腾讯财经 · Yahoo Finance · SEC EDGAR  
> 灵感与数据层整合自 [simonlin1212/global-stock-data](https://github.com/simonlin1212/global-stock-data)
