"""
数据库模块 v1.0 - Multi-Factor Momentum+ 量化系统
================================================
从JSON文件迁移到SQLite/SQLAlchemy

功能：
1. 用户管理（多用户、角色、券商绑定）
2. 持仓记录
3. 交易历史
4. 信号记录
5. 因子权重历史
6. 权益曲线
7. 系统配置

数据迁移：
- 自动从现有JSON文件导入数据
- 保持向后兼容，JSON文件作为备份
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Text, JSON, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, scoped_session
from sqlalchemy.pool import StaticPool

logger = logging.getLogger("quant.db")

# 数据库路径
DB_PATH = os.environ.get("DATABASE_PATH", "data/quant_system.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# 数据库URL
DATABASE_URL = f"sqlite:///{DB_PATH}"

# SQLAlchemy 配置
Base = declarative_base()


# ===== 用户表 =====

class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="user")  # admin / user
    broker_type = Column(String(50), default="alpaca_paper")
    created_at = Column(DateTime, default=datetime.now)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    
    # 关系
    positions = relationship("Position", back_populates="user", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="user", cascade="all, delete-orphan")
    signals = relationship("Signal", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    equity_history = relationship("EquityHistory", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(username={self.username}, role={self.role})>"


# ===== 持仓表 =====

class Position(Base):
    """持仓表"""
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    quantity = Column(Float, default=0)
    avg_cost = Column(Float, default=0)
    current_price = Column(Float, default=0)
    market_value = Column(Float, default=0)
    unrealized_pnl = Column(Float, default=0)
    unrealized_pnl_pct = Column(Float, default=0)
    sector = Column(String(50), nullable=True)
    entry_date = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关系
    user = relationship("User", back_populates="positions")
    
    # 索引
    __table_args__ = (
        Index("idx_position_user_ticker", "user_id", "ticker", unique=True),
    )
    
    def __repr__(self):
        return f"<Position(ticker={self.ticker}, qty={self.quantity})>"


# ===== 交易记录表 =====

class Trade(Base):
    """交易记录表"""
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # 基本信息
    ticker = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # BUY / SELL
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    commission = Column(Float, default=0)
    
    # 时间和来源
    trade_time = Column(DateTime, default=datetime.now, index=True)
    strategy = Column(String(50), nullable=True)  # conservative / momentum / intraday / manual
    source = Column(String(50), nullable=True)  # signal / rebalance / stop_loss / manual
    notes = Column(Text, nullable=True)
    
    # 关系
    user = relationship("User", back_populates="trades")
    
    # 索引
    __table_args__ = (
        Index("idx_trade_user_time", "user_id", "trade_time"),
        Index("idx_trade_ticker_time", "ticker", "trade_time"),
    )
    
    def __repr__(self):
        return f"<Trade({self.side} {self.ticker} {self.quantity}@{self.price})>"


# ===== 信号表 =====

class Signal(Base):
    """信号记录表"""
    __tablename__ = "signals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # 信号基本信息
    signal_date = Column(DateTime, index=True)
    market_status = Column(String(50), nullable=True)  # 多头/震荡/熊市
    market_action = Column(String(50), nullable=True)  # 正常买入/减仓/空仓
    macro_score = Column(Float, default=0)  # 宏观温度
    
    # 市场数据
    spy_price = Column(Float, nullable=True)
    spy_rsi = Column(Float, nullable=True)
    
    # 信号JSON（保留完整数据）
    signal_data = Column(JSON, nullable=True)  # 买入候选股列表
    
    # 创建时间
    created_at = Column(DateTime, default=datetime.now)
    
    # 关系
    user = relationship("User", back_populates="signals")
    
    # 索引
    __table_args__ = (
        Index("idx_signal_user_date", "user_id", "signal_date"),
        UniqueConstraint("user_id", "signal_date", name="uq_signal_user_date"),
    )
    
    def __repr__(self):
        return f"<Signal(date={self.signal_date}, market={self.market_status})>"


# ===== 因子权重历史表 =====

class FactorWeightHistory(Base):
    """因子权重历史表"""
    __tablename__ = "factor_weight_history"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 权重数据
    momentum = Column(Float, default=0)
    quality = Column(Float, default=0)
    trend = Column(Float, default=0)
    value = Column(Float, default=0)
    lowvol = Column(Float, default=0)
    volume = Column(Float, default=0)
    
    # IC数据
    ic_momentum = Column(Float, nullable=True)
    ic_quality = Column(Float, nullable=True)
    ic_trend = Column(Float, nullable=True)
    ic_value = Column(Float, nullable=True)
    ic_lowvol = Column(Float, nullable=True)
    
    # 进化信息
    evolution_type = Column(String(20), default="auto")  # auto / manual
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    
    def __repr__(self):
        return f"<FactorWeight(epoch={self.id}, mom={self.momentum}%)>"


# ===== 因子排名表 =====

class FactorRanking(Base):
    """因子排名表"""
    __tablename__ = "factor_rankings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 因子名称和排名
    factor_name = Column(String(50), nullable=False)
    ic_rank = Column(Float, default=0)  # Spearman IC
    ic_pearson = Column(Float, default=0)  # Pearson IC
    abs_ic = Column(Float, default=0)
    samples = Column(Integer, default=0)
    
    # 元数据
    category = Column(String(50), nullable=True)  # 动量/趋势/波动等
    created_at = Column(DateTime, default=datetime.now, index=True)
    
    # 索引
    __table_args__ = (
        Index("idx_factor_ranking_time", "factor_name", "created_at"),
    )
    
    def __repr__(self):
        return f"<FactorRanking({self.factor_name} IC={self.ic_rank:.4f})>"


# ===== 订单表 =====

class Order(Base):
    """订单记录表"""
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # 订单信息
    order_id = Column(String(100), unique=True, nullable=True)  # 券商订单ID
    ticker = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # BUY / SELL
    order_type = Column(String(20), default="market")  # market / limit / stop
    quantity = Column(Float, nullable=False)
    limit_price = Column(Float, nullable=True)
    
    # 状态
    status = Column(String(20), default="pending")  # pending / filled / cancelled / rejected
    filled_qty = Column(Float, default=0)
    filled_price = Column(Float, nullable=True)
    filled_at = Column(DateTime, nullable=True)
    
    # 时间和来源
    created_at = Column(DateTime, default=datetime.now, index=True)
    strategy = Column(String(50), nullable=True)
    
    # 关系
    user = relationship("User", back_populates="orders")
    
    def __repr__(self):
        return f"<Order({self.order_id} {self.side} {self.ticker} {self.status})>"


# ===== 权益历史表 =====

class EquityHistory(Base):
    """权益历史表"""
    __tablename__ = "equity_history"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # 权益数据
    date = Column(DateTime, index=True)
    total_equity = Column(Float, nullable=False)
    cash = Column(Float, default=0)
    market_value = Column(Float, default=0)
    daily_return = Column(Float, nullable=True)
    cumulative_return = Column(Float, nullable=True)
    
    # 风险指标
    daily_pnl = Column(Float, nullable=True)
    position_count = Column(Integer, default=0)
    
    # 关联
    created_at = Column(DateTime, default=datetime.now)
    
    # 关系
    user = relationship("User", back_populates="equity_history")
    
    # 索引
    __table_args__ = (
        Index("idx_equity_user_date", "user_id", "date"),
        UniqueConstraint("user_id", "date", name="uq_equity_user_date"),
    )
    
    def __repr__(self):
        return f"<EquityHistory(date={self.date}, equity={self.total_equity})>"


# ===== 系统配置表 =====

class SystemConfig(Base):
    """系统配置表"""
    __tablename__ = "system_config"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=True)
    value_type = Column(String(20), default="string")  # string / number / boolean / json
    category = Column(String(50), nullable=True)  # strategy / risk / notification
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def __repr__(self):
        return f"<Config({self.key}={self.value[:50] if self.value else 'None'})>"


# ===== 数据库管理类 =====

class Database:
    """数据库管理类"""
    
    def __init__(self, db_url: str = DATABASE_URL):
        self.engine = create_engine(
            db_url,
            echo=False,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False}
        )
        self.session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(self.session_factory)
        
    def create_all(self):
        """创建所有表"""
        Base.metadata.create_all(self.engine)
        logger.info("✅ 数据库表创建完成")
        
    def drop_all(self):
        """删除所有表（慎用）"""
        Base.metadata.drop_all(self.engine)
        logger.warning("⚠️ 所有数据库表已删除")
        
    def get_session(self):
        """获取数据库会话"""
        return self.Session()
    
    def close_session(self):
        """关闭会话"""
        self.Session.remove()


# 全局数据库实例
db = Database()


# ===== 数据迁移函数 =====

def migrate_from_json():
    """从JSON文件迁移数据到数据库"""
    session = db.get_session()
    
    try:
        # 1. 迁移用户
        users_file = "config/users.json"
        if os.path.exists(users_file):
            with open(users_file) as f:
                users_data = json.load(f)
            
            for username, user_info in users_data.items():
                existing = session.query(User).filter_by(username=username).first()
                if not existing:
                    user = User(
                        username=username,
                        password_hash=user_info.get("password", ""),
                        role=user_info.get("role", "user"),
                        broker_type=user_info.get("broker", "alpaca_paper"),
                        created_at=datetime.fromisoformat(user_info["created"]) if user_info.get("created") else datetime.now(),
                        last_login=datetime.fromisoformat(user_info["last_login"]) if user_info.get("last_login") else None
                    )
                    session.add(user)
                    logger.info(f"  ✅ 迁移用户: {username}")
            
            session.commit()
            logger.info("✅ 用户数据迁移完成")
        
        # 2. 迁移因子权重历史
        weights_file = "config/factor_weights.json"
        if os.path.exists(weights_file):
            with open(weights_file) as f:
                weights = json.load(f)
            
            fw = FactorWeightHistory(
                momentum=weights.get("momentum", 45),
                quality=weights.get("quality", 26),
                trend=weights.get("trend", 13),
                value=weights.get("value", 8),
                lowvol=weights.get("lowvol", 6),
                volume=weights.get("volume", 6),
                evolution_type="initial"
            )
            session.add(fw)
            session.commit()
            logger.info("✅ 因子权重迁移完成")
        
        # 3. 迁移系统配置
        config_file = "config/system_config.json"
        if os.path.exists(config_file):
            with open(config_file) as f:
                config = json.load(f)
            
            for key, value in config.items():
                existing = session.query(SystemConfig).filter_by(key=key).first()
                if not existing:
                    cfg = SystemConfig(
                        key=key,
                        value=str(value) if not isinstance(value, (dict, list, bool)) else json.dumps(value) if isinstance(value, (dict, list)) else str(value).lower() if isinstance(value, bool) else str(value),
                        value_type=type(value).__name__,
                        category="system"
                    )
                    session.add(cfg)
            
            session.commit()
            logger.info("✅ 系统配置迁移完成")
        
        # 4. 迁移信号历史
        signals_dir = "signals"
        if os.path.exists(signals_dir):
            for filename in os.listdir(signals_dir):
                if filename.startswith("signal_") and filename.endswith(".json"):
                    filepath = os.path.join(signals_dir, filename)
                    try:
                        with open(filepath) as f:
                            signal_data = json.load(f)
                        
                        # 解析日期
                        date_str = filename.replace("signal_", "").replace(".json", "")
                        signal_date = datetime.strptime(date_str, "%Y-%m-%d")
                        
                        # 获取默认用户
                        default_user = session.query(User).first()
                        if default_user:
                            signal = Signal(
                                user_id=default_user.id,
                                signal_date=signal_date,
                                market_status=signal_data.get("market", {}).get("trend", ""),
                                market_action=signal_data.get("market", {}).get("action", ""),
                                spy_price=signal_data.get("market", {}).get("spy", 0),
                                spy_rsi=signal_data.get("market", {}).get("rsi", 0),
                                signal_data=signal_data
                            )
                            session.add(signal)
                            logger.info(f"  ✅ 迁移信号: {date_str}")
                        
                        session.commit()
                    except Exception as e:
                        logger.warning(f"  ⚠️ 迁移信号失败 {filename}: {e}")
            
            logger.info("✅ 信号历史迁移完成")
        
        logger.info("🎉 数据迁移全部完成！")
        
    except Exception as e:
        session.rollback()
        logger.error(f"❌ 数据迁移失败: {e}")
        raise
    finally:
        session.close()


def init_database(with_migration: bool = True):
    """初始化数据库"""
    db.create_all()
    
    # 检查是否需要迁移
    session = db.get_session()
    user_count = session.query(User).count()
    session.close()
    
    if user_count == 0 and with_migration:
        logger.info("📦 检测到新数据库，开始迁移数据...")
        migrate_from_json()
    else:
        logger.info(f"📦 数据库已有 {user_count} 个用户，跳过迁移")


# ===== 便捷访问函数 =====

def get_config(key: str, default: Any = None) -> Any:
    """获取配置"""
    session = db.get_session()
    try:
        cfg = session.query(SystemConfig).filter_by(key=key).first()
        if cfg:
            if cfg.value_type == "json":
                return json.loads(cfg.value)
            elif cfg.value_type == "bool":
                return cfg.value.lower() == "true"
            elif cfg.value_type == "int":
                return int(cfg.value)
            elif cfg.value_type == "float":
                return float(cfg.value)
            return cfg.value
        return default
    finally:
        session.close()


def set_config(key: str, value: Any, category: str = "system"):
    """设置配置"""
    session = db.get_session()
    try:
        cfg = session.query(SystemConfig).filter_by(key=key).first()
        if cfg:
            if isinstance(value, (dict, list)):
                cfg.value = json.dumps(value)
                cfg.value_type = "json"
            elif isinstance(value, bool):
                cfg.value = str(value).lower()
                cfg.value_type = "bool"
            else:
                cfg.value = str(value)
                cfg.value_type = type(value).__name__
        else:
            cfg = SystemConfig(
                key=key,
                value=json.dumps(value) if isinstance(value, (dict, list)) else str(value).lower() if isinstance(value, bool) else str(value),
                value_type="json" if isinstance(value, (dict, list)) else type(value).__name__,
                category=category
            )
            session.add(cfg)
        
        session.commit()
        return True
    finally:
        session.close()


def record_equity(user_id: int, total_equity: float, cash: float = 0, market_value: float = 0, position_count: int = 0):
    """记录权益快照"""
    session = db.get_session()
    try:
        # 获取上一条记录计算日收益
        last = session.query(EquityHistory).filter_by(user_id=user_id).order_by(EquityHistory.date.desc()).first()
        
        daily_return = None
        cumulative_return = None
        daily_pnl = None
        
        if last:
            daily_pnl = total_equity - last.total_equity
            daily_return = (total_equity / last.total_equity - 1) * 100 if last.total_equity > 0 else 0
            
            # 计算累计收益（相对于初始权益）
            if last.id == 1 or last.cumulative_return is None:
                cumulative_return = 0
            else:
                # 找到初始权益
                first = session.query(EquityHistory).filter_by(user_id=user_id).order_by(EquityHistory.date.asc()).first()
                if first:
                    cumulative_return = (total_equity / first.total_equity - 1) * 100 if first.total_equity > 0 else 0
        
        equity = EquityHistory(
            user_id=user_id,
            date=datetime.now(),
            total_equity=total_equity,
            cash=cash,
            market_value=market_value,
            daily_return=daily_return,
            cumulative_return=cumulative_return,
            daily_pnl=daily_pnl,
            position_count=position_count
        )
        session.add(equity)
        session.commit()
    finally:
        session.close()


# 导出
__all__ = [
    "db", "Database",
    "Base",
    "User", "Position", "Trade", "Signal",
    "FactorWeightHistory", "FactorRanking",
    "Order", "EquityHistory", "SystemConfig",
    "init_database", "migrate_from_json",
    "get_config", "set_config", "record_equity"
]
