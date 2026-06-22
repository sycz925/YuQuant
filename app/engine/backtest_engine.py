"""
回测引擎 - 模拟真实交易环境
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import sqlite3

from app.data.manager import DataManager
from app.engine.factor_engine import FactorEngine

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """交易记录"""
    stock_code: str
    stock_name: str
    direction: str  # BUY/SELL
    quantity: int
    signal_price: float
    execute_price: float
    commission: float
    transfer_fee: float
    stamp_duty: float
    reason: str
    signal_time: str
    execute_time: str


@dataclass
class Position:
    """持仓记录"""
    stock_code: str
    stock_name: str
    quantity: int
    avg_cost: float
    current_price: float
    highest_price: float  # 持仓期间最高价（用于移动止盈）
    buy_date: str


@dataclass
class BacktestResult:
    """回测结果"""
    initial_capital: float
    final_capital: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    equity_curve: pd.Series
    trade_log: pd.DataFrame


class Strategy(ABC):
    """策略基类"""
    
    @abstractmethod
    def on_bar(self, engine: 'BacktestEngine', trade_date: str) -> None:
        """
        每个交易日调用
        
        Args:
            engine: 回测引擎实例
            trade_date: 当前交易日
        """
        pass


class BacktestEngine:
    """
    回测引擎，模拟真实交易环境
    """
    
    def __init__(self, data_manager: DataManager, factor_engine: FactorEngine, 
                 initial_capital: float = 1000000):
        """
        初始化回测引擎
        
        Args:
            data_manager: 数据管理器
            factor_engine: 因子引擎
            initial_capital: 初始资金
        """
        self.data_manager = data_manager
        self.factor_engine = factor_engine
        self.initial_capital = initial_capital
        
        # 费用参数
        self.commission_rate = 0.0003  # 佣金率
        self.min_commission = 5.0  # 最低佣金
        self.transfer_fee_rate = 0.00002  # 过户费
        self.stamp_duty_rate = 0.0005  # 印花税（仅卖出）
        
        # 风控参数
        self.stop_loss_pct = 0.08  # 8% 绝对止损
        self.take_profit_pct = 0.08  # 8% 移动止盈
        self.cr5_stop_threshold = 40.0  # CR5% 风控阈值
        
        # 滑点（至少1个tick，假设是0.01元）
        self.slippage = 0.01
        
        # 状态
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}  # 持仓
        self.trades: List[Trade] = []  # 交易记录
        self.equity_history: Dict[str, float] = {}  # 资金曲线
        self.today_holdings: set = set()  # T+1 锁
        self.current_date = ""
        self.market_locked = False  # 全局风控锁定
        
        logger.info(f"BacktestEngine 初始化完成，初始资金={initial_capital}")
    
    def set_commission(self, commission_rate: float = 0.0003, 
                      min_commission: float = 5.0,
                      transfer_fee_rate: float = 0.00002,
                      stamp_duty_rate: float = 0.0005) -> None:
        """设置交易费用"""
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.transfer_fee_rate = transfer_fee_rate
        self.stamp_duty_rate = stamp_duty_rate
    
    def set_risk_control(self, stop_loss: float = 0.08, 
                       take_profit: float = 0.08,
                       cr5_stop_threshold: float = 40.0) -> None:
        """设置风控参数"""
        self.stop_loss_pct = stop_loss
        self.take_profit_pct = take_profit
        self.cr5_stop_threshold = cr5_stop_threshold
    
    def set_strategy(self, strategy: Strategy) -> None:
        """设置策略"""
        self.strategy = strategy
    
    def _calculate_fees(self, direction: str, amount: float) -> tuple:
        """
        计算交易费用
        
        Args:
            direction: BUY/SELL
            amount: 成交金额
            
        Returns:
            (佣金, 过户费, 印花税)
        """
        commission = max(amount * self.commission_rate, self.min_commission)
        transfer_fee = amount * self.transfer_fee_rate if direction == 'BUY' else 0
        stamp_duty = amount * self.stamp_duty_rate if direction == 'SELL' else 0
        
        return commission, transfer_fee, stamp_duty
    
    def _get_stock_name(self, stock_code: str) -> str:
        """获取股票名称"""
        # 这里简化处理，实际应该从数据库读取
        return stock_code
    
    def _check_limit_up_down(self, stock_code: str, trade_date: str) -> tuple:
        """
        检查涨跌停
        
        Returns:
            (是否涨停, 是否跌停)
        """
        # 这里简化处理，实际应该从数据读取
        return False, False
    
    def buy(self, stock_code: str, quantity: int, reason: str = "") -> bool:
        """
        买入
        
        Args:
            stock_code: 股票代码
            quantity: 数量（手，1手=100股）
            reason: 买入原因
            
        Returns:
            是否成功
        """
        quantity = quantity * 100  # 转换为股
        
        if quantity <= 0:
            return False
        
        # 全局风控检查
        if self.market_locked:
            logger.warning(f"{self.current_date}: 市场已锁定，禁止买入 {stock_code}")
            return False
        
        # 检查涨停
        is_limit_up, is_limit_down = self._check_limit_up_down(stock_code, self.current_date)
        if is_limit_up:
            logger.warning(f"{self.current_date}: {stock_code} 涨停，无法买入")
            return False
        
        # 获取当前价格
        current_price = self.data_manager.get_adj_close(stock_code, self.current_date)
        if current_price is None:
            logger.warning(f"{self.current_date}: {stock_code} 无价格数据")
            return False
        
        # 滑点（买入时价格上移）
        execute_price = current_price + self.slippage
        
        # 计算金额
        amount = execute_price * quantity
        
        # 计算费用
        commission, transfer_fee, stamp_duty = self._calculate_fees('BUY', amount)
        total_cost = amount + commission + transfer_fee
        
        if self.cash < total_cost:
            logger.warning(f"{self.current_date}: 现金不足，无法买入 {stock_code}")
            return False
        
        # 检查是否已持有
        if stock_code in self.positions:
            # 加仓
            pos = self.positions[stock_code]
            total_quantity = pos.quantity + quantity
            total_cost = (pos.avg_cost * pos.quantity) + (execute_price * quantity)
            new_avg_cost = total_cost / total_quantity
            
            pos.quantity = total_quantity
            pos.avg_cost = new_avg_cost
            pos.current_price = execute_price
        else:
            # 新建持仓
            stock_name = self._get_stock_name(stock_code)
            self.positions[stock_code] = Position(
                stock_code=stock_code,
                stock_name=stock_name,
                quantity=quantity,
                avg_cost=execute_price,
                current_price=execute_price,
                highest_price=execute_price,
                buy_date=self.current_date
            )
        
        # 扣除资金
        self.cash -= total_cost
        
        # 记录交易
        trade = Trade(
            stock_code=stock_code,
            stock_name=self._get_stock_name(stock_code),
            direction='BUY',
            quantity=quantity,
            signal_price=current_price,
            execute_price=execute_price,
            commission=commission,
            transfer_fee=transfer_fee,
            stamp_duty=stamp_duty,
            reason=reason,
            signal_time=self.current_date,
            execute_time=self.current_date
        )
        self.trades.append(trade)
        
        logger.info(f"{self.current_date}: 买入 {stock_code} {quantity}股 @{execute_price:.2f}")
        
        return True
    
    def sell(self, stock_code: str, quantity: int, reason: str = "") -> bool:
        """
        卖出
        
        Args:
            stock_code: 股票代码
            quantity: 数量（手）
            reason: 卖出原因
            
        Returns:
            是否成功
        """
        quantity = quantity * 100
        
        if stock_code not in self.positions:
            return False
        
        pos = self.positions[stock_code]
        
        # 检查 T+1
        if stock_code in self.today_holdings:
            logger.warning(f"{self.current_date}: {stock_code} T+1锁定期，无法卖出")
            return False
        
        # 检查跌停
        is_limit_up, is_limit_down = self._check_limit_up_down(stock_code, self.current_date)
        if is_limit_down:
            logger.warning(f"{self.current_date}: {stock_code} 跌停，无法卖出")
            return False
        
        # 获取当前价格
        current_price = self.data_manager.get_adj_close(stock_code, self.current_date)
        if current_price is None:
            logger.warning(f"{self.current_date}: {stock_code} 无价格数据")
            return False
        
        # 滑点（卖出时价格下移）
        execute_price = current_price - self.slippage
        
        quantity = min(quantity, pos.quantity)
        
        # 计算金额
        amount = execute_price * quantity
        
        # 计算费用
        commission, transfer_fee, stamp_duty = self._calculate_fees('SELL', amount)
        total_cost = commission + transfer_fee + stamp_duty
        net_amount = amount - total_cost
        
        # 增加资金
        self.cash += net_amount
        
        # 更新持仓
        if quantity == pos.quantity:
            del self.positions[stock_code]
        else:
            pos.quantity -= quantity
        
        # 记录交易
        trade = Trade(
            stock_code=stock_code,
            stock_name=self._get_stock_name(stock_code),
            direction='SELL',
            quantity=quantity,
            signal_price=current_price,
            execute_price=execute_price,
            commission=commission,
            transfer_fee=transfer_fee,
            stamp_duty=stamp_duty,
            reason=reason,
            signal_time=self.current_date,
            execute_time=self.current_date
        )
        self.trades.append(trade)
        
        logger.info(f"{self.current_date}: 卖出 {stock_code} {quantity}股 @{execute_price:.2f}")
        
        return True
    
    def _check_risk_control(self, trade_date: str) -> None:
        """检查风控条件"""
        # 1. 检查 CR5% 全局风控
        cr5 = self.factor_engine.calculate_cr5_percent(trade_date)
        if cr5 > self.cr5_stop_threshold:
            if not self.market_locked:
                logger.warning(f"{trade_date}: CR5%={cr5:.2f}% > {self.cr5_stop_threshold}%，触发全局风控，清仓")
                self.market_locked = True
                # 清仓
                for stock_code in list(self.positions.keys()):
                    pos = self.positions[stock_code]
                    self.sell(stock_code, pos.quantity // 100, "CR5%风控清仓")
        else:
            self.market_locked = False
        
        # 2. 检查个股止损止盈
        for stock_code in list(self.positions.keys()):
            pos = self.positions[stock_code]
            
            current_price = self.data_manager.get_adj_close(stock_code, trade_date)
            if current_price is None:
                continue
            
            pos.current_price = current_price
            
            # 更新最高价
            if current_price > pos.highest_price:
                pos.highest_price = current_price
            
            # 止损检查
            pct_change = (current_price - pos.avg_cost) / pos.avg_cost
            if pct_change <= -self.stop_loss_pct:
                self.sell(stock_code, pos.quantity // 100, f"止损{pct_change:.2%}")
                continue
            
            # 止盈检查（移动止盈）
            drawdown_from_high = (pos.highest_price - current_price) / pos.highest_price
            if drawdown_from_high >= self.take_profit_pct:
                self.sell(stock_code, pos.quantity // 100, f"移动止盈回撤{drawdown_from_high:.2%}")
                continue
    
    def _calculate_equity(self) -> float:
        """计算当前总权益"""
        equity = self.cash
        for stock_code, pos in self.positions.items():
            market_value = pos.quantity * pos.current_price
            equity += market_value
        return equity
    
    def run(self, start_date: str, end_date: str) -> BacktestResult:
        """
        运行回测
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            回测结果
        """
        logger.info(f"开始回测: {start_date} - {end_date}")
        
        # 重置状态
        self.cash = self.initial_capital
        self.positions = {}
        self.trades = []
        self.equity_history = {}
        self.today_holdings = set()
        self.market_locked = False
        
        # 生成日期序列（这里简化处理）
        from datetime import datetime, timedelta
        start_dt = datetime.strptime(start_date, '%Y%m%d')
        end_dt = datetime.strptime(end_date, '%Y%m%d')
        
        current_dt = start_dt
        prev_date = ""
        
        while current_dt <= end_dt:
            self.current_date = current_dt.strftime('%Y%m%d')
            
            # 1. 释放 T+1
            if prev_date:
                self.today_holdings = set()
            
            # 2. 检查风控
            self._check_risk_control(self.current_date)
            
            # 3. 执行策略
            if self.strategy:
                self.strategy.on_bar(self, self.current_date)
            
            # 4. 记录 T+1
            for stock_code in self.positions.keys():
                self.today_holdings.add(stock_code)
            
            # 5. 记录资金
            equity = self._calculate_equity()
            self.equity_history[self.current_date] = equity
            
            prev_date = self.current_date
            current_dt += timedelta(days=1)
        
        # 计算回测指标
        result = self._calculate_result()
        
        logger.info(f"回测完成，总收益率: {result.total_return:.2%}")
        
        return result
    
    def _calculate_result(self) -> BacktestResult:
        """计算回测结果"""
        equity_series = pd.Series(self.equity_history)
        
        # 总收益率
        final_capital = equity_series.iloc[-1] if len(equity_series) > 0 else self.initial_capital
        total_return = (final_capital - self.initial_capital) / self.initial_capital
        
        # 最大回撤
        cum_max = equity_series.cummax()
        drawdown = (equity_series - cum_max) / cum_max
        max_drawdown = drawdown.min() if len(drawdown) > 0 else 0
        
        # 年化收益率（简化，假设252个交易日）
        n_days = len(equity_series)
        annual_return = (1 + total_return) ** (252 / n_days) - 1 if n_days > 0 else 0
        
        # 夏普比率（简化，假设无风险利率为3%）
        returns = equity_series.pct_change().dropna()
        sharpe_ratio = (returns.mean() - 0.03 / 252) / returns.std() * np.sqrt(252) if len(returns) > 0 else 0
        
        # 胜率
        if len(self.trades) > 0:
            buy_trades = [t for t in self.trades if t.direction == 'BUY']
            sell_trades = [t for t in self.trades if t.direction == 'SELL']
            total_trades = max(len(buy_trades), len(sell_trades))
            # 这里简化计算胜率
            win_rate = 0.5
        else:
            total_trades = 0
            win_rate = 0
        
        # 交易日志
        trade_log_df = pd.DataFrame([
            {
                'trade_date': t.execute_time,
                'stock_code': t.stock_code,
                'direction': t.direction,
                'quantity': t.quantity,
                'signal_price': t.signal_price,
                'execute_price': t.execute_price,
                'reason': t.reason
            }
            for t in self.trades
        ])
        
        return BacktestResult(
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            win_rate=win_rate,
            total_trades=total_trades,
            equity_curve=equity_series,
            trade_log=trade_log_df
        )
    
    def get_trade_log(self) -> pd.DataFrame:
        """获取交易日志"""
        if len(self.trades) == 0:
            return pd.DataFrame()
        
        return pd.DataFrame([
            {
                'trade_date': t.execute_time,
                'stock_code': t.stock_code,
                'direction': t.direction,
                'quantity': t.quantity,
                'signal_price': t.signal_price,
                'execute_price': t.execute_price,
                'commission': t.commission,
                'reason': t.reason
            }
            for t in self.trades
        ])
    
    def get_equity_curve(self) -> pd.Series:
        """获取资金曲线"""
        return pd.Series(self.equity_history)
