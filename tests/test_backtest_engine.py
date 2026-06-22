"""
回测引擎单元测试
"""
import os
import unittest
import tempfile
import shutil
import pandas as pd
from dataclasses import dataclass

# 添加项目路径
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_manager import DataManager
from app.factor_engine import FactorEngine
from app.backtest_engine import BacktestEngine, Strategy


class TestBacktestEngine(unittest.TestCase):
    """回测引擎测试"""
    
    def setUp(self):
        """测试前置"""
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test.db")
        self.hdf5_path = os.path.join(self.test_dir, "hdf5")
        os.makedirs(self.hdf5_path, exist_ok=True)
        
        # 创建数据管理器和因子引擎
        self.dm = DataManager(self.db_path, self.hdf5_path)
        self.fe = FactorEngine(self.dm)
        self.engine = BacktestEngine(self.dm, self.fe, initial_capital=1000000)
    
    def tearDown(self):
        """测试清理"""
        shutil.rmtree(self.test_dir)
    
    def test_init(self):
        """测试回测引擎初始化"""
        self.assertIsNotNone(self.engine)
        self.assertEqual(self.engine.initial_capital, 1000000)
    
    def test_set_commission(self):
        """测试设置佣金"""
        self.engine.set_commission(
            commission_rate=0.0005, min_commission=5.0)
        self.assertEqual(self.engine.commission_rate, 0.0005)
        self.assertEqual(self.engine.min_commission, 5.0)
    
    def test_set_risk_control(self):
        """测试设置风控"""
        self.engine.set_risk_control(
            stop_loss=0.05, take_profit=0.10, cr5_stop_threshold=50.0)
        self.assertEqual(self.engine.stop_loss_pct, 0.05)
        self.assertEqual(self.engine.cr5_stop_threshold, 50.0)
    
    def test_get_trade_log_empty(self):
        """测试获取交易日志（空）"""
        log = self.engine.get_trade_log()
        self.assertIsInstance(log, pd.DataFrame)
    
    def test_get_equity_curve_empty(self):
        """测试获取资金曲线（空）"""
        curve = self.engine.get_equity_curve()
        self.assertIsInstance(curve, pd.Series)
    
    def test_calculate_equity_initial(self):
        """测试计算初始权益"""
        equity = self.engine._calculate_equity()
        self.assertEqual(equity, 1000000)
    
    def test_buy_not_enough_cash(self):
        """测试买入（现金不足）"""
        result = self.engine.buy("000001", 100000, "test")
        self.assertFalse(result)
    
    def test_set_strategy(self):
        """测试设置策略"""
        
        class SimpleStrategy(Strategy):
            def on_bar(self, engine, trade_date):
                pass
        
        strategy = SimpleStrategy()
        self.engine.set_strategy(strategy)
        self.assertIsNotNone(self.engine.strategy)


if __name__ == "__main__":
    unittest.main()
