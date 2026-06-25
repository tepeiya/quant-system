#!/usr/bin/env python3
"""
数据库初始化脚本
================
用于初始化数据库和迁移数据

用法：
    python init_db.py              # 初始化并迁移数据
    python init_db.py --fresh     # 清空数据库重新初始化
    python init_db.py --check     # 检查数据库状态
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (
    db, init_database, migrate_from_json,
    User, Position, Trade, Signal, EquityHistory,
    FactorWeightHistory, FactorRanking, Order, SystemConfig
)

def check_database():
    """检查数据库状态"""
    session = db.get_session()
    
    try:
        print("\n📊 数据库状态检查")
        print("=" * 50)
        
        # 统计各表记录数
        tables = [
            ("用户表", User),
            ("持仓表", Position),
            ("交易记录", Trade),
            ("信号记录", Signal),
            ("权益历史", EquityHistory),
            ("因子权重历史", FactorWeightHistory),
            ("因子排名", FactorRanking),
            ("订单记录", Order),
            ("系统配置", SystemConfig),
        ]
        
        for name, model in tables:
            count = session.query(model).count()
            print(f"  {name}: {count} 条记录")
        
        print("=" * 50)
        
        # 显示用户列表
        users = session.query(User).all()
        if users:
            print("\n👥 用户列表:")
            for u in users:
                print(f"  - {u.username} ({u.role}) - 创建于 {u.created_at.strftime('%Y-%m-%d')}")
        
        # 显示最新权益记录
        latest_equity = session.query(EquityHistory).order_by(EquityHistory.date.desc()).first()
        if latest_equity:
            print(f"\n💰 最新权益: ${latest_equity.total_equity:,.2f} ({latest_equity.date.strftime('%Y-%m-%d %H:%M')})")
        
        # 显示最新信号
        latest_signal = session.query(Signal).order_by(Signal.signal_date.desc()).first()
        if latest_signal:
            print(f"📈 最新信号: {latest_signal.signal_date.strftime('%Y-%m-%d')} - {latest_signal.market_status}")
        
        print()
        return True
        
    finally:
        session.close()


def fresh_init():
    """清空并重新初始化"""
    print("⚠️ 即将清空数据库并重新初始化...")
    print("   所有现有数据将被删除！")
    
    response = input("确认继续？(y/N): ")
    if response.lower() != 'y':
        print("已取消")
        return False
    
    session = db.get_session()
    try:
        # 删除并重建表
        db.drop_all()
        session.commit()
        
        # 重新创建表
        db.create_all()
        session.commit()
        
        # 执行迁移
        migrate_from_json()
        
        print("\n✅ 数据库重新初始化完成！")
        check_database()
        return True
        
    except Exception as e:
        session.rollback()
        print(f"\n❌ 初始化失败: {e}")
        return False
    finally:
        session.close()


def main():
    """主函数"""
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "--check":
            check_database()
        elif cmd == "--fresh":
            fresh_init()
        elif cmd == "--help":
            print(__doc__)
        else:
            print(f"未知命令: {cmd}")
            print(__doc__)
    else:
        # 默认初始化
        print("🚀 开始初始化数据库...")
        init_database(with_migration=True)
        check_database()


if __name__ == "__main__":
    main()
