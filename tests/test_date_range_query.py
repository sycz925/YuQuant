"""日期范围查询 helper 测试：_norm_date 规范化 + build_date_range_query 边界"""
import unittest

from app.data.db import _norm_date, build_date_range_query


class NormDateTest(unittest.TestCase):
    """_norm_date：统一输出零填充 YYYYMMDD"""

    def test_yyyymmdd_unchanged(self):
        self.assertEqual(_norm_date('20260724'), '20260724')

    def test_dash_format(self):
        self.assertEqual(_norm_date('2026-07-24'), '20260724')

    def test_slash_format(self):
        self.assertEqual(_norm_date('2026/07/24'), '20260724')

    def test_non_padded_input_normalized(self):
        """非零填充的月/日（2026-7-4）也能规范化补零"""
        self.assertEqual(_norm_date('2026-7-4'), '20260704')

    def test_invalid_format_raises(self):
        with self.assertRaises(ValueError):
            _norm_date('not-a-date')


class BuildDateRangeQueryTest(unittest.TestCase):
    """build_date_range_query：$gte/$lte 边界与空参"""

    def test_both_bounds(self):
        self.assertEqual(
            build_date_range_query('2026-07-01', '2026-07-10'),
            {'trade_date': {'$gte': '20260701', '$lte': '20260710'}},
        )

    def test_start_only(self):
        self.assertEqual(
            build_date_range_query('2026-07-01'),
            {'trade_date': {'$gte': '20260701'}},
        )

    def test_end_only(self):
        self.assertEqual(
            build_date_range_query(end='2026-07-10'),
            {'trade_date': {'$lte': '20260710'}},
        )

    def test_no_bounds_returns_empty(self):
        self.assertEqual(build_date_range_query(), {})
        self.assertEqual(build_date_range_query('', ''), {})

    def test_invalid_start_raises(self):
        with self.assertRaises(ValueError):
            build_date_range_query('bad-date', '2026-07-10')


if __name__ == '__main__':
    unittest.main()
