"""calendar_service 表征测试：锁定快照生成与每日总结的返回结构。

锁定对象为 `app.server.services.calendar_service` 中的：
- `generate_calendar_snapshot(trade_date, repo)`
- `get_calendar_daily_summary(year, month, index_code, repo)`

结构 = 下沉前 api 层现状行为（纯搬家，不改行为），确保下沉不破坏返回契约。
数据访问已下沉 `CalendarRepository`，测试注入 mock repo（无需接触真实 MongoDB）。
"""
import unittest
from unittest import mock

from app.server.services.calendar_service import (
    generate_calendar_snapshot,
    get_calendar_daily_summary,
)

SNAPSHOT_FIELDS = {
    'up_count', 'down_count', 'total_amount', 'market_change_pct',
    'top_sector', 'top_sector_chg', 'is_final', 'tdx_status',
}

DAILY_SUMMARY_ITEM_FIELDS = {
    'date', 'day', 'is_trading_day', 'has_data',
    'up_count', 'down_count', 'total_amount', 'market_change_pct',
    'top_sector', 'top_sector_chg', 'is_final', 'tdx_status',
    'recommended_position', 'market_risk_level',
    'position_management_commentary', 'core_target_sectors',
}


class GenerateCalendarSnapshotTest(unittest.TestCase):
    """锁定 generate_calendar_snapshot 返回结构（8 字段，无 core_target_sectors）"""

    def _make_repo(self):
        repo = mock.MagicMock()
        repo.get_base_snapshot.return_value = {
            'up_count': 3000, 'down_count': 2000,
            'total_amount': 100_000_000_000, 'is_final': True,
        }
        repo.get_market_snapshot.return_value = {
            'new_high': {'clusters': [{'industry': '半导体', 'chg_pct': 3.5}]},
            'overview': {'indices': [{'code': '880003', 'tdx_status': '日红周蓝'}]},
        }
        repo.get_index_chg_pct.return_value = {'chg_pct': 1.23}
        return repo

    def test_return_structure(self):
        result = generate_calendar_snapshot('20260102', self._make_repo())

        self.assertIsInstance(result, dict)
        self.assertEqual(set(result.keys()), SNAPSHOT_FIELDS)
        self.assertNotIn('core_target_sectors', result)

        self.assertEqual(result['up_count'], 3000)
        self.assertEqual(result['down_count'], 2000)
        self.assertEqual(result['total_amount'], 1000)  # 1e11 / 1e8 截断
        self.assertEqual(result['market_change_pct'], 1.23)
        self.assertEqual(result['top_sector'], '半导体')
        self.assertEqual(result['top_sector_chg'], 3.5)
        self.assertTrue(result['is_final'])
        self.assertEqual(result['tdx_status'], '日红周蓝')

    def test_returns_none_without_base_doc(self):
        repo = mock.MagicMock()
        repo.get_base_snapshot.return_value = None
        self.assertIsNone(generate_calendar_snapshot('20260102', repo))

    def test_is_final_taken_from_base_doc(self):
        """is_final 取自 base_data_daily 字段，而非 stock_daily 比例计算"""
        repo = self._make_repo()
        repo.get_base_snapshot.return_value['is_final'] = False
        result = generate_calendar_snapshot('20260102', repo)
        self.assertFalse(result['is_final'])


class GetCalendarDailySummaryTest(unittest.TestCase):
    """锁定 get_calendar_daily_summary 返回结构（顶层 5 键 + 每日条目 16 字段）"""

    def test_structure_all_non_trading(self):
        repo = mock.MagicMock()
        repo.get_snapshots_range.return_value = []
        repo.get_ai_analysis_range.return_value = []
        with mock.patch('app.server.services.calendar_service.is_workday', return_value=False):
            result = get_calendar_daily_summary(2026, 2, '880003', repo)

        # 顶层结构
        self.assertEqual(set(result.keys()), {'success', 'data', 'year', 'month', 'index_code'})
        self.assertTrue(result['success'])
        self.assertEqual(result['year'], 2026)
        self.assertEqual(result['month'], 2)
        self.assertEqual(result['index_code'], '880003')

        # 2026-02 共 28 天，每天一条
        self.assertEqual(len(result['data']), 28)

        first = result['data'][0]
        self.assertEqual(set(first.keys()), DAILY_SUMMARY_ITEM_FIELDS)
        self.assertEqual(first['date'], '20260201')
        self.assertEqual(first['day'], 1)
        self.assertFalse(first['is_trading_day'])
        self.assertFalse(first['has_data'])

    def test_trading_day_realtime_computed(self):
        """某天为交易日且无快照 → 实时计算，锁定交易日条目结构"""
        repo = mock.MagicMock()
        base_doc = {'date': '20260201', 'up_count': 3000, 'down_count': 2000,
                    'total_amount': 100_000_000_000}
        market_doc = {
            'trade_date': '20260201',
            'new_high': {'clusters': [{'industry': '半导体', 'chg_pct': 2.5}]},
            'overview': {'indices': [{'code': '880003', 'tdx_status': '日红周蓝'}]},
        }
        index_doc = {'trade_date': '20260201', 'close': 100.0, 'chg_pct': 1.5}

        repo.get_snapshots_range.return_value = []
        repo.get_ai_analysis_range.return_value = []
        repo.get_base_daily_bulk.return_value = [base_doc]
        repo.get_market_daily_bulk.return_value = [market_doc]
        repo.get_index_daily_bulk.return_value = [index_doc]
        # count_stock_daily 两次：total / final
        repo.count_stock_daily.side_effect = [5000, 4900]

        with mock.patch('app.server.services.calendar_service.is_workday',
                        side_effect=lambda d: d == '20260201'):
            result = get_calendar_daily_summary(2026, 2, '880003', repo)

        self.assertEqual(len(result['data']), 28)

        first = result['data'][0]
        self.assertEqual(set(first.keys()), DAILY_SUMMARY_ITEM_FIELDS)
        self.assertEqual(first['date'], '20260201')
        self.assertEqual(first['day'], 1)
        self.assertTrue(first['is_trading_day'])
        self.assertTrue(first['has_data'])
        self.assertEqual(first['up_count'], 3000)
        self.assertEqual(first['down_count'], 2000)
        self.assertEqual(first['total_amount'], 1000)  # round(1e11 / 1e8, 0) 后 int
        self.assertEqual(first['market_change_pct'], 1.5)
        self.assertEqual(first['top_sector'], '半导体')
        self.assertEqual(first['top_sector_chg'], 2.5)
        self.assertTrue(first['is_final'])  # 4900 / 5000 = 0.98 > 0.95
        self.assertEqual(first['tdx_status'], '日红周蓝')
        # 无 AI 分析数据时字段回退为空
        self.assertEqual(first['recommended_position'], '')
        self.assertEqual(first['market_risk_level'], '')
        self.assertEqual(first['position_management_commentary'], '')
        self.assertEqual(first['core_target_sectors'], [])


if __name__ == '__main__':
    unittest.main()
