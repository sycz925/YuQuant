"""get_sector_daily_data 表征测试：锁定返回结构（vol→volume 映射 + 升序）"""
import unittest
from unittest import mock

from fastapi import HTTPException

from app.server.api.factors import get_sector_daily_data


class SectorDailyDataTest(unittest.TestCase):
    @mock.patch('app.server.api.factors.get_sector_repo')
    def test_vol_to_volume_mapping_and_ascending(self, mock_get_repo):
        mock_repo = mock.MagicMock()
        mock_get_repo.return_value = mock_repo

        # 原始数据按 trade_date 降序返回（20260102 在前）
        raw = [
            {'trade_date': '20260102', 'vol': 100, 'close': 10.5},
            {'trade_date': '20260101', 'vol': 200, 'close': 10.0},
        ]
        mock_repo.get_daily_bars.return_value = raw

        resp = get_sector_daily_data(code='880001', start_date='20260101', end_date='20261231', limit=200)

        self.assertEqual(resp.code, '880001')
        self.assertEqual(resp.total, 2)
        # reverse 后升序：20260101 在前
        self.assertEqual(resp.data[0].trade_date, '20260101')
        self.assertEqual(resp.data[1].trade_date, '20260102')
        # vol 字段映射为 volume（20260101 的 vol=200）
        self.assertEqual(resp.data[0].volume, 200)

    @mock.patch('app.server.api.factors.get_sector_repo')
    def test_empty_raises_404(self, mock_get_repo):
        mock_repo = mock.MagicMock()
        mock_get_repo.return_value = mock_repo
        mock_repo.get_daily_bars.return_value = []

        with self.assertRaises(HTTPException):
            get_sector_daily_data(code='880001', start_date='20260101', end_date='20261231', limit=200)


if __name__ == '__main__':
    unittest.main()
