"""get_*_sync_start_date 表征测试：锁定三分支行为（P1 去重前基线）"""
import unittest
from unittest import mock

from app.data.db import get_stock_sync_start_date, get_sector_sync_start_date


class SyncStartDateTest(unittest.TestCase):
    @mock.patch('app.data.db.get_collection')
    def test_no_data_returns_none(self, mock_coll):
        mock_coll.return_value.find_one.return_value = None
        self.assertIsNone(get_stock_sync_start_date('000001'))

    @mock.patch('app.data.db.get_collection')
    def test_final_data_returns_next_day(self, mock_coll):
        mock_coll.return_value.find_one.return_value = {
            'trade_date': '20260724', 'is_final': True}
        self.assertEqual(get_stock_sync_start_date('000001'), '20260725')

    @mock.patch('app.data.db.get_collection')
    def test_intraday_data_returns_same_day(self, mock_coll):
        mock_coll.return_value.find_one.return_value = {
            'trade_date': '20260724', 'is_final': False}
        self.assertEqual(get_stock_sync_start_date('000001'), '20260724')

    @mock.patch('app.data.db.get_collection')
    def test_missing_is_final_defaults_to_false(self, mock_coll):
        """锁定现状：get('is_final', False) 缺省为 False，与注释"默认已收盘"不一致（待修）"""
        mock_coll.return_value.find_one.return_value = {'trade_date': '20260724'}
        self.assertEqual(get_stock_sync_start_date('000001'), '20260724')

    @mock.patch('app.data.db.get_collection')
    def test_sector_uses_sector_collection(self, mock_coll):
        mock_coll.return_value.find_one.return_value = None
        get_sector_sync_start_date('880001')
        mock_coll.assert_called_once_with('sector')


if __name__ == '__main__':
    unittest.main()
