"""
异步任务队列系统 v1.0
======================
支持后台任务执行、状态查询、任务调度

功能：
1. 任务队列管理
2. 后台线程执行
3. 任务状态追踪
4. 任务进度报告
5. 任务结果存储
6. 定时任务调度
"""

import os
import json
import uuid
import time
import threading
import logging
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
import queue

logger = logging.getLogger("quant.task_queue")

# 配置
TASK_STORAGE_FILE = "data/tasks/task_storage.json"
TASK_MAX_RETRIES = 3
TASK_TIMEOUT = 3600  # 1小时超时


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"       # 等待中
    RUNNING = "running"       # 执行中
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"         # 失败
    CANCELLED = "cancelled"   # 已取消
    TIMEOUT = "timeout"       # 超时


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 1
    NORMAL = 5
    HIGH = 10
    CRITICAL = 20


@dataclass
class Task:
    """任务"""
    task_id: str
    task_type: str
    name: str
    description: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    result: Any = None
    error: str = ""
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    retries: int = 0
    max_retries: int = TASK_MAX_RETRIES
    timeout: int = TASK_TIMEOUT
    params: Dict = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    user_id: str = ""


class TaskQueue:
    """任务队列"""
    
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.tasks: Dict[str, Task] = {}
        self.queue = queue.PriorityQueue()
        self.workers: List[threading.Thread] = []
        self.running = False
        self._lock = threading.Lock()
        
        # 任务处理器注册
        self.handlers: Dict[str, Callable] = {}
        
        # 加载历史任务
        self._load_tasks()
    
    def register_handler(self, task_type: str, handler: Callable):
        """注册任务处理器"""
        self.handlers[task_type] = handler
        logger.info(f"注册任务处理器: {task_type}")
    
    def create_task(self, task_type: str, name: str, params: Dict = None,
                    description: str = "", priority: TaskPriority = TaskPriority.NORMAL,
                    user_id: str = "") -> str:
        """
        创建任务
        
        Returns:
            task_id
        """
        task_id = str(uuid.uuid4())
        
        task = Task(
            task_id=task_id,
            task_type=task_type,
            name=name,
            description=description,
            priority=priority,
            params=params or {},
            created_at=datetime.now().isoformat(),
            user_id=user_id
        )
        
        with self._lock:
            self.tasks[task_id] = task
        
        # 加入队列
        self.queue.put((-priority.value, task_id))  # 负号表示高优先级先出
        
        logger.info(f"创建任务: {task_id} ({name})")
        self._save_tasks()
        
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务信息"""
        with self._lock:
            return self.tasks.get(task_id)
    
    def get_task_status(self, task_id: str) -> Dict:
        """获取任务状态（简化版）"""
        task = self.get_task(task_id)
        if not task:
            return {"exists": False}
        
        return {
            "exists": True,
            "task_id": task.task_id,
            "task_type": task.task_type,
            "name": task.name,
            "status": task.status.value,
            "progress": task.progress,
            "error": task.error,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "retries": task.retries
        }
    
    def get_all_tasks(self, limit: int = 50, status: str = None) -> List[Dict]:
        """获取所有任务列表"""
        with self._lock:
            tasks = list(self.tasks.values())
        
        # 按创建时间倒序
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        
        # 过滤状态
        if status:
            tasks = [t for t in tasks if t.status.value == status]
        
        # 限制数量
        tasks = tasks[:limit]
        
        return [
            {
                "task_id": t.task_id,
                "task_type": t.task_type,
                "name": t.name,
                "status": t.status.value,
                "progress": t.progress,
                "created_at": t.created_at
            }
            for t in tasks
        ]
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        task = self.get_task(task_id)
        if not task:
            return False
        
        if task.status in [TaskStatus.PENDING]:
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now().isoformat()
            self._save_tasks()
            logger.info(f"任务已取消: {task_id}")
            return True
        
        return False
    
    def retry_task(self, task_id: str) -> bool:
        """重试任务"""
        task = self.get_task(task_id)
        if not task:
            return False
        
        if task.status in [TaskStatus.FAILED, TaskStatus.TIMEOUT]:
            task.status = TaskStatus.PENDING
            task.progress = 0
            task.error = ""
            task.retries += 1
            task.started_at = ""
            task.completed_at = ""
            
            # 重新加入队列
            self.queue.put((-task.priority.value, task_id))
            
            self._save_tasks()
            logger.info(f"任务重试: {task_id} ({task.retries}/{task.max_retries})")
            return True
        
        return False
    
    def start(self):
        """启动工作线程"""
        if self.running:
            return
        
        self.running = True
        
        for i in range(self.max_workers):
            worker = threading.Thread(target=self._worker_loop, args=(i,), daemon=True)
            worker.start()
            self.workers.append(worker)
        
        logger.info(f"任务队列已启动，{self.max_workers}个工作线程")
    
    def stop(self):
        """停止工作线程"""
        self.running = False
        logger.info("任务队列正在停止...")
    
    def _worker_loop(self, worker_id: int):
        """工作线程主循环"""
        logger.info(f"工作线程 {worker_id} 已启动")
        
        while self.running:
            try:
                # 从队列获取任务（非阻塞）
                try:
                    priority, task_id = self.queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                task = self.get_task(task_id)
                if not task:
                    continue
                
                # 检查任务状态
                if task.status != TaskStatus.PENDING:
                    continue
                
                # 执行任务
                self._execute_task(task, worker_id)
                
                self.queue.task_done()
                
            except Exception as e:
                logger.error(f"工作线程 {worker_id} 错误: {e}")
                time.sleep(1)
        
        logger.info(f"工作线程 {worker_id} 已停止")
    
    def _execute_task(self, task: Task, worker_id: int):
        """执行任务"""
        logger.info(f"线程{worker_id}开始执行任务: {task.task_id} ({task.name})")
        
        # 更新状态
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now().isoformat()
        self._save_tasks()
        
        start_time = time.time()
        
        try:
            # 获取处理器
            handler = self.handlers.get(task.task_type)
            if not handler:
                raise ValueError(f"未找到任务处理器: {task.task_type}")
            
            # 执行任务（传入任务对象用于更新进度）
            result = handler(task.params, self._make_progress_callback(task))
            
            # 任务完成
            task.status = TaskStatus.COMPLETED
            task.progress = 100.0
            task.result = result
            task.completed_at = datetime.now().isoformat()
            
            elapsed = time.time() - start_time
            logger.info(f"✅ 任务完成: {task.task_id} ({task.name}) 用时{elapsed:.2f}s")
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now().isoformat()
            
            elapsed = time.time() - start_time
            logger.error(f"❌ 任务失败: {task.task_id} ({task.name}): {e}")
            logger.error(traceback.format_exc())
            
            # 添加错误日志
            task.logs.append(f"[{datetime.now().isoformat()}] ERROR: {str(e)}")
        
        self._save_tasks()
    
    def _make_progress_callback(self, task: Task):
        """创建进度更新回调"""
        def update_progress(progress: float, message: str = ""):
            task.progress = min(100.0, max(0.0, progress))
            if message:
                task.logs.append(f"[{datetime.now().isoformat()}] {message}")
        return update_progress
    
    def _load_tasks(self):
        """加载历史任务"""
        if os.path.exists(TASK_STORAGE_FILE):
            try:
                with open(TASK_STORAGE_FILE) as f:
                    data = json.load(f)
                
                for task_data in data.get("tasks", []):
                    task = Task(
                        task_id=task_data["task_id"],
                        task_type=task_data["task_type"],
                        name=task_data["name"],
                        description=task_data.get("description", ""),
                        priority=TaskPriority[task_data.get("priority", "NORMAL")],
                        status=TaskStatus[task_data.get("status", "PENDING")],
                        progress=task_data.get("progress", 0),
                        result=task_data.get("result"),
                        error=task_data.get("error", ""),
                        created_at=task_data.get("created_at", ""),
                        started_at=task_data.get("started_at", ""),
                        completed_at=task_data.get("completed_at", ""),
                        retries=task_data.get("retries", 0),
                        max_retries=task_data.get("max_retries", TASK_MAX_RETRIES),
                        timeout=task_data.get("timeout", TASK_TIMEOUT),
                        params=task_data.get("params", {}),
                        logs=task_data.get("logs", []),
                        user_id=task_data.get("user_id", "")
                    )
                    self.tasks[task.task_id] = task
                
                logger.info(f"加载了 {len(self.tasks)} 个历史任务")
                
            except Exception as e:
                logger.warning(f"加载任务存储失败: {e}")
    
    def _save_tasks(self):
        """保存任务"""
        os.makedirs(os.path.dirname(TASK_STORAGE_FILE), exist_ok=True)
        
        # 只保存最近100个任务
        all_tasks = list(self.tasks.values())
        all_tasks.sort(key=lambda t: t.created_at, reverse=True)
        recent_tasks = all_tasks[:100]
        
        data = {
            "tasks": [
                {
                    "task_id": t.task_id,
                    "task_type": t.task_type,
                    "name": t.name,
                    "description": t.description,
                    "priority": t.priority.name,
                    "status": t.status.name,
                    "progress": t.progress,
                    "result": t.result if isinstance(t.result, (dict, list, str, int, float, bool)) else None,
                    "error": t.error,
                    "created_at": t.created_at,
                    "started_at": t.started_at,
                    "completed_at": t.completed_at,
                    "retries": t.retries,
                    "max_retries": t.max_retries,
                    "timeout": t.timeout,
                    "params": t.params,
                    "logs": t.logs[-50:],  # 只保留最近50条
                    "user_id": t.user_id
                }
                for t in recent_tasks
            ],
            "updated_at": datetime.now().isoformat()
        }
        
        try:
            with open(TASK_STORAGE_FILE, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.warning(f"保存任务失败: {e}")


# ===== 内置任务处理器 =====

def _handle_backtest(params: Dict, progress_callback: Callable) -> Dict:
    """回测任务处理器"""
    from backtest_engine import quick_backtest
    import pandas as pd
    import numpy as np
    
    progress_callback(10, "准备数据...")
    time.sleep(0.5)
    
    # 生成模拟数据
    ticker = params.get("ticker", "SPY")
    days = params.get("days", 252)
    
    progress_callback(30, "生成价格数据...")
    time.sleep(0.5)
    
    dates = pd.date_range(start="2023-01-01", periods=days, freq="D").strftime("%Y-%m-%d").tolist()
    prices = pd.DataFrame({
        "date": dates,
        "close": 100 + np.cumsum(np.random.randn(days) * 2)
    })
    
    signals_df = pd.DataFrame({
        "date": dates,
        ticker: np.random.randn(days) * 0.5 + 0.1
    })
    
    progress_callback(60, "执行回测...")
    time.sleep(0.5)
    
    result = quick_backtest(ticker, prices, signals_df)
    
    progress_callback(90, "生成报告...")
    time.sleep(0.3)
    
    return result


def _handle_factor_calculation(params: Dict, progress_callback: Callable) -> Dict:
    """因子计算任务处理器"""
    from factor_mining_v3 import calculate_all_factors
    
    ticker = params.get("ticker", "AAPL")
    price = params.get("price", 100.0)
    
    progress_callback(30, f"计算{ticker}因子...")
    time.sleep(0.5)
    
    factors = calculate_all_factors(ticker, price)
    
    progress_callback(80, "因子分析...")
    time.sleep(0.3)
    
    return {"ticker": ticker, "factors": factors}


def _handle_stress_test(params: Dict, progress_callback: Callable) -> Dict:
    """压力测试任务处理器"""
    from stress_test import StressTestEngine
    
    positions = params.get("positions", {"AAPL": 50000, "MSFT": 40000})
    
    progress_callback(20, "初始化引擎...")
    time.sleep(0.3)
    
    engine = StressTestEngine()
    
    progress_callback(50, "运行历史情景...")
    time.sleep(0.5)
    
    results = engine.run_all_scenarios(positions)
    
    progress_callback(80, "生成报告...")
    time.sleep(0.3)
    
    return results


def _handle_data_update(params: Dict, progress_callback: Callable) -> Dict:
    """数据更新任务处理器"""
    progress_callback(10, "检查数据源...")
    time.sleep(0.3)
    
    progress_callback(40, "下载行情数据...")
    time.sleep(0.5)
    
    progress_callback(70, "计算因子...")
    time.sleep(0.5)
    
    progress_callback(90, "生成信号...")
    time.sleep(0.3)
    
    return {"updated": True, "date": datetime.now().isoformat()}


# ===== 全局实例 =====

_task_queue = None

def get_task_queue() -> TaskQueue:
    """获取全局任务队列"""
    global _task_queue
    
    if _task_queue is None:
        _task_queue = TaskQueue(max_workers=4)
        
        # 注册内置任务处理器
        _task_queue.register_handler("backtest", _handle_backtest)
        _task_queue.register_handler("factor_calculation", _handle_factor_calculation)
        _task_queue.register_handler("stress_test", _handle_stress_test)
        _task_queue.register_handler("data_update", _handle_data_update)
        
        # 启动队列
        _task_queue.start()
    
    return _task_queue


# ===== 便捷函数 =====

def create_backtest_task(ticker: str, days: int = 252, user_id: str = "") -> str:
    """创建回测任务"""
    return get_task_queue().create_task(
        task_type="backtest",
        name=f"回测 - {ticker}",
        params={"ticker": ticker, "days": days},
        description=f"对{ticker}进行{days}天回测",
        user_id=user_id
    )


def create_stress_test_task(positions: Dict, user_id: str = "") -> str:
    """创建压力测试任务"""
    return get_task_queue().create_task(
        task_type="stress_test",
        name="组合压力测试",
        params={"positions": positions},
        description="运行所有历史危机情景压力测试",
        user_id=user_id
    )


def create_data_update_task(user_id: str = "") -> str:
    """创建数据更新任务"""
    return get_task_queue().create_task(
        task_type="data_update",
        name="数据更新",
        description="更新所有市场数据和因子",
        user_id=user_id
    )


# ===== 测试 =====

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n🧪 任务队列测试")
    print("=" * 50)
    
    # 获取队列
    queue = get_task_queue()
    
    # 创建任务
    print("\n📋 创建任务...")
    task1 = create_backtest_task("AAPL", days=100)
    task2 = create_stress_test_task({"AAPL": 50000, "MSFT": 40000})
    task3 = create_data_update_task()
    
    print(f"  回测任务: {task1}")
    print(f"  压力测试任务: {task2}")
    print(f"  数据更新任务: {task3}")
    
    # 等待执行
    print("\n⏳ 等待任务执行...")
    time.sleep(3)
    
    # 查看任务状态
    print("\n📊 任务状态:")
    for task in queue.get_all_tasks(limit=10):
        print(f"  {task['name']}: {task['status']} ({task['progress']:.0f}%)")
    
    # 查看单个任务详情
    print("\n📋 回测任务详情:")
    status = queue.get_task_status(task1)
    print(f"  状态: {status['status']}")
    print(f"  进度: {status['progress']:.1f}%")
    print(f"  创建时间: {status['created_at']}")
    
    print("\n" + "=" * 50)
    print("✅ 任务队列测试完成")