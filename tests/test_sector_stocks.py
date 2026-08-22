"""get_sector_stocks 表征测试：锁定返回结构（chg_pct→change_pct + name 注入 + 排序）"""
import unittest
from unittest import mock

from fastapi import HTTPException

from app.server.api.factors import get_sector_stocks


class SectorStocksTest(unittest.TestCase):
    def _setup(self, mock_get_sector, mock_get_stock):
        sector_repo = mock.MagicMock()
        stock_repo = mock.MagicMock()
        mock_get_sector.return_value = sector_repo
        mock_get_stock.return_value = stock_repo

        sector_repo.get_by_code.return_value = {
            'name': '测试板块', 'stock_codes': ['000001', '000002'], 'stock_count': 2,
        }
        stock_repo.get_latest_trade_date.return_value = '20260102'
        stock_repo.get_daily_quotes.return_value = [
            {'stock_code': '000001', 'close': 10.0, 'chg_pct': 1.5, 'rps_20': 90},
            {'stock_code': '000002', 'close': 20.0, 'chg_pct': -0.5, 'rps_20': 50},
        ]
        stock_repo.get_stock_names.return_value = {
            '000001': '平安银行', '000002': '万科A',
        }

    @mock.patch('app.server.api.factors.get_stock_repo')
    @mock.patch('app.server.api.factors.get_sector_repo')
    def test_returns_stocks_with_name_and_change_pct(self, mock_get_sector, mock_get_stock):
        self._setup(mock_get_sector, mock_get_stock)

        resp = get_sector_stocks(code='880001')

        self.assertTrue(resp['success'])
        self.assertEqual(resp['sector_name'], '测试板块')
        self.assertEqual(resp['stock_count'], 2)
        self.assertEqual(resp['trade_date'], '20260102')
        # chg_pct → change_pct 映射 + name 注入
        self.assertIn('change_pct', resp['stocks'][0])
        self.assertNotIn('chg_pct', resp['stocks'][0])
        # 按名称排序：'万科A'('万' U+4E07) < '平安银行'('平' U+5E73)
        self.assertEqual(resp['stocks'][0]['name'], '万科A')
        self.assertEqual(resp['stocks'][1]['name'], '平安银行')

    @mock.patch('app.server.api.factors.get_stock_repo')
    @mock.patch('app.server.api.factors.get_sector_repo')
    def test_missing_sector_returns_404(self, mock_get_sector, mock_get_stock):
        sector_repo = mock.MagicMock()
        mock_get_sector.return_value = sector_repo
        sector_repo.get_by_code.return_value = None

        with self.assertRaises(HTTPException):
            get_sector_stocks(code='880001')


if __name__ == '__main__':
    unittest.main()
