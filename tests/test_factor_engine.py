"""
因子引擎单元测试
"""
import os
import unittest
import tempfile
import shutil
import pandas as pd

# 添加项目路径
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_manager import DataManager
from app.factor_engine import FactorEngine


class TestFactorEngine(unittest.TestCase):
    """因子引擎测试"""
    
    def setUp(self):
        """测试前置"""
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test.db")
        self.hdf5_path = os.path.join(self.test_dir, "hdf5")
        os.makedirs(self.hdf5_path, exist_ok=True)
        
        # 创建数据管理器和因子引擎
        self.dm = DataManager(self.db_path, self.hdf5_path)
        self.fe = FactorEngine(self.dm)
    
    def tearDown(self):
        """测试清理"""
        shutil.rmtree(self.test_dir)
    
    def test_init(self):
        """测试因子引擎初始化"""
        self.assertIsNotNone(self.fe)
    
    def test_calculate_cr5_percent_no_data(self):
        """测试 CR5% 计算（无数据）"""
        cr5 = self.fe.calculate_cr5_percent("20240101")
        self.assertIsInstance(cr5, float)
        self.assertEqual(cr5, 0.0)
    
    def test_calculate_ma_no_data(self):
        """测试 MA 计算（无数据）"""
        ma = self.fe.calculate_ma("000001", "20240101", 20)
        self.assertIsNone(ma)
    
    def test_calculate_index_ma_no_data(self):
        """测试指数 MA 计算（无数据）"""
        ma = self.fe.calculate_index_ma("000001", "20240101", 20)
        self.assertIsNone(ma)
    
    def test_batch_calculate_ma_no_data(self):
        """测试批量 MA 计算（无数据）"""
        result = self.fe.batch_calculate_ma(
            ["000001", "000002"], "20240101", "20240131", 20
        )
        self.assertIsInstance(result, pd.DataFrame)
    
    def test_get_all_cr5_history_no_data(self):
        """测试获取 CR5% 历史（无数据）"""
        history = self.fe.get_all_cr5_history("20240101", "20240131")
        self.assertIsInstance(history, pd.Series)


if __name__ == "__main__":
    unittest.main()
