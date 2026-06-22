"""
数据管理器单元测试
"""
import os
import unittest
import tempfile
import shutil
from datetime import datetime

import pandas as pd

# 添加项目路径
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data_manager import DataManager


class TestDataManager(unittest.TestCase):
    """数据管理器测试"""
    
    def setUp(self):
        """测试前置"""
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test.db")
        self.hdf5_path = os.path.join(self.test_dir, "hdf5")
        os.makedirs(self.hdf5_path, exist_ok=True)
        
        # 创建数据管理器
        self.dm = DataManager(self.db_path, self.hdf5_path)
    
    def tearDown(self):
        """测试清理"""
        shutil.rmtree(self.test_dir)
    
    def test_init_database(self):
        """测试数据库初始化"""
        # 检查数据库文件已创建
        self.assertTrue(os.path.exists(self.db_path))
    
    def test_stock_basics_table_exists(self):
        """测试 stock_basics 表存在"""
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='stock_basics'
            """)
            self.assertIsNotNone(cursor.fetchone())
    
    def test_get_all_stock_codes_empty(self):
        """测试获取股票代码（空）"""
        codes = self.dm.get_all_stock_codes()
        self.assertIsInstance(codes, list)
    
    def test_get_stock_universe_empty(self):
        """测试获取股票池（空）"""
        universe = self.dm.get_stock_universe("20240101")
        self.assertIsInstance(universe, list)
        self.assertEqual(len(universe), 0)
    
    def test_get_adj_close_no_data(self):
        """测试获取复权收盘（无数据）"""
        price = self.dm.get_adj_close("000001", "20240101")
        self.assertIsNone(price)
    
    def test_get_index_data_empty(self):
        """测试获取指数数据（空）"""
        df = self.dm.get_index_data("000001", "20240101", "20240131")
        self.assertIsInstance(df, pd.DataFrame)


if __name__ == "__main__":
    unittest.main()
