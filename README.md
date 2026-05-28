# 📊 Multi-Factor Momentum+ 量化系统

多因子动量选股量化交易系统，支持 Alpaca 纸交易/实盘、IBKR（盈透证券），自带 Web 面板、ATR 动态风控、因子自动进化。

## 🚀 快速开始

### 方案1：Docker 部署（推荐）

```bash
git clone https://github.com/tepeiya/quant-system.git
cd quant-system
cp env_template .env
# 编辑 .env 填入你的 API Key
docker compose up -d
```

访问 `http://localhost:8765`，注册管理员账号。

### 方案2：直接运行

```bash
pip install -r requirements.txt
cp env_template .env   # 填入 API Key
python3 web_app.py     # 启动 Web 面板
```

## 📋 功能清单

### Web 面板（10个页面）

| 页面 | 说明 |
|:----|:------|
| 📈 大盘 | 总权益、现金、持仓、资金曲线 |
| 🏆 信号 | 6因子评分 Top10、买入候选、一键调仓 |
| 📋 持仓 | 持仓明细、PnL、交易记录 |
| 📝 交易 | 绩效归因、因子贡献分解 |
| 🧬 因子 | 权重配置、IC图表、自动进化 |
| 🔄 轮式 | 卖Put/Call期权轮式计划 |
| 🌍 宏观 | 美债/美元/黄金/通胀评分 |
| 📜 历史 | 90天信号历史 |
| 🛒 下单 | 手动买卖 |
| ⚙️ 设置 | 策略参数、券商管理、API密钥 |

### 策略引擎

- **6因子选股：** 动量45% + 质量26% + 趋势13% + 价值8% + 低波6% + 成交量6%
- **4态择时：** 🟢多头 / 🟡震荡 / 🔴过热 / 🔴熊市
- **ATR动态止损：** 低波4.5% ~ 高波25%
- **因子自动进化：** IC追踪 + 滑动窗口 + 退化回滚

### 风控体系

- ATR动态止损 + 跟踪止盈
- 单日亏10%熔断清仓
- 连续亏5%冷却24小时
- 月度再平衡

### 券商支持

| 券商 | 状态 | 说明 |
|:----|:----:|:------|
| Alpaca 纸交易 | ✅ | 已跑通 |
| Alpaca 实盘 | ✅ | 切换 trade_mode |
| IBKR 盈透 | ✅ | TWS/模拟/Gateway |

## ⚙️ 环境变量

```bash
# 必填
ALPACA_API_KEY_ID=你的AlpacaKey
ALPACA_SECRET_KEY=你的AlpacaSecret
TIINGO_API_KEY=你的TiingoKey

# 可选
FRED_API_KEY=你的FREDKey      # 宏观数据
PUSHPLUS_TOKEN=你的PushPlusToken  # 微信推送
```

## 📖 管理命令

```bash
sh manage.sh start       # 启动系统
sh manage.sh stop        # 停止系统
sh manage.sh status      # 查看状态
sh manage.sh signal      # 手动生成信号
sh manage.sh rebalance   # 手动调仓
sh manage.sh evolve      # 因子进化
```

## 🏗️ 项目结构

```
quant-system/
├── web_app.py               # Web面板入口
├── daemon.py                # 守护进程（止损/熔断/信号/再平衡）
├── strategy_vector.py       # 向量化策略引擎
├── factor_learner.py        # 因子自动进化
├── paper_trader.py          # 执行器
├── broker_manager.py        # 券商接口（Alpaca/IBKR）
├── wheel_strategy.py        # 轮式期权策略
├── performance_attribution.py # 绩效归因
├── data_prod.py             # 数据层
├── security.py              # 安全加固
├── config/                  # 配置文件
├── signals/                 # 信号与交易记录
├── data_cache/              # 数据缓存
├── web/
│   ├── blueprints/          # Web API（10个蓝图）
│   ├── templates/           # 页面模板
│   └── static/              # 静态资源
└── Dockerfile               # Docker部署
```

## 🔐 安全

- 密码 bcrypt 加密
- API Key AES-256 加密存储
- 登录限速（5次/分钟）
- CSRF 保护
- Session 24小时过期
- 操作审计日志

## 📄 许可证

AGPL v3
