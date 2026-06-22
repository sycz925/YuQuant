"""
回测API
"""
import logging
import threading
from typing import Optional
from fastapi import APIRouter, HTTPException

from app.engine.backtest_engine import BacktestEngine
from app.data.manager import get_data_manager
from app.server.models import BacktestRequest, BacktestResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

_backtest_engine: Optional[BacktestEngine] = None
_engine_lock = threading.Lock()


def get_backtest_engine():
    """获取BacktestEngine单例（线程安全）"""
    global _backtest_engine
    if _backtest_engine is None:
        with _engine_lock:
            if _backtest_engine is None:
                from app.engine.factor_engine import FactorEngine
                dm = get_data_manager()
                fe = FactorEngine(dm)
                _backtest_engine = BacktestEngine(dm, fe, initial_capital=100000)
    return _backtest_engine


@router.post("/run", response_model=BacktestResult)
def run_backtest(request: BacktestRequest):
    """运行回测"""
    try:
        engine = get_backtest_engine()
        engine.initial_capital = request.initial_capital

        # 设置默认股票
        if not request.stock_codes:
            request.stock_codes = ["600000", "000001", "688279"]

        # 简单的演示回测（实际使用完整BacktestEngine）
        import numpy as np
        from datetime import datetime, timedelta

        # 生成演示数据
        start = datetime.strptime(request.start_date, "%Y%m%d")
        end = datetime.strptime(request.end_date, "%Y%m%d")

        equity_curve = []
        current_capital = request.initial_capital
        current_date = start

        while current_date <= end:
            # 简单的随机收益波动
            daily_return = np.random.normal(0.0005, 0.015)
            current_capital *= (1 + daily_return)

            equity_curve.append({
                "trade_date": current_date.strftime("%Y%m%d"),
                "equity": float(current_capital)
            })

            current_date += timedelta(days=1)

        # 计算指标
        total_return = (equity_curve[-1]["equity"] / request.initial_capital - 1)
        annual_return = total_return * 365 / max(len(equity_curve), 1)

        # 模拟最大回撤
        peak = request.initial_capital
        max_drawdown = 0
        for point in equity_curve:
            if point["equity"] > peak:
                peak = point["equity"]
            drawdown = (peak - point["equity"]) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        # 模拟夏普比率
        returns = []
        for i in range(1, len(equity_curve)):
            r = equity_curve[i]["equity"] / equity_curve[i-1]["equity"] - 1
            returns.append(r)

        if len(returns) > 0:
            sharpe_ratio = np.mean(returns) / (np.std(returns) + 1e-6) * np.sqrt(252)
        else:
            sharpe_ratio = 0

        # 模拟交易记录
        trades = []
        for i, code in enumerate(request.stock_codes[:5]):
            trades.append({
                "trade_date": (start + timedelta(days=i*30)).strftime("%Y%m%d"),
                "stock_code": code,
                "action": "BUY" if i % 2 == 0 else "SELL",
                "quantity": 100,
                "price": 100 + i * 5
            })

        return BacktestResult(
            total_return=float(total_return),
            annual_return=float(annual_return),
            max_drawdown=float(max_drawdown),
            sharpe_ratio=float(sharpe_ratio),
            equity_curve=equity_curve,
            trades=trades
        )

    except Exception as e:
        logger.error(f"回测失败: {e}")
        raise HTTPException(status_code=500, detail="回测失败")
