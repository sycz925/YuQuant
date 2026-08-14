"""复权基准漂移修复测试：xdxr 除权事件指纹检测 + 全量重拉判定"""
import unittest
from unittest import mock

import pandas as pd

from app.data.sources.pytdx_source import PytdxSource


def _evt(year, month, day, fenhong=0, songzhuangu=0, peigu=0, peigujia=0, category=1):
    """构造一条原始 xdxr 事件（pytdx get_xdxr_info 原始格式）"""
    return {
        'year': year, 'month': month, 'day': day,
        'category': category,
        'fenhong': fenhong, 'songzhuangu': songzhuangu,
        'peigu': peigu, 'peigujia': peigujia,
    }


class XdxrFingerprintTest(unittest.TestCase):
    """xdxr 事件指纹：同事件集合同指纹，除权变化则指纹变化"""

    def test_same_events_same_fingerprint(self):
        events = [
            _evt(2024, 6, 20, fenhong=30, songzhuangu=0),
            _evt(2025, 6, 18, fenhong=50, songzhuangu=0),
        ]
        self.assertEqual(
            PytdxSource.xdxr_fingerprint(events),
            PytdxSource.xdxr_fingerprint(events),
        )

    def test_new_event_changes_fingerprint(self):
        base = [_evt(2024, 6, 20, fenhong=30)]
        extended = base + [_evt(2025, 6, 18, fenhong=50)]
        self.assertNotEqual(
            PytdxSource.xdxr_fingerprint(base),
            PytdxSource.xdxr_fingerprint(extended),
        )

    def test_factor_change_changes_fingerprint(self):
        before = [_evt(2024, 6, 20, fenhong=30)]
        after = [_evt(2024, 6, 20, fenhong=50)]
        self.assertNotEqual(
            PytdxSource.xdxr_fingerprint(before),
            PytdxSource.xdxr_fingerprint(after),
        )

    def test_ignores_non_adjust_categories(self):
        """category != 1 的事件不影响指纹"""
        with_cash = [_evt(2024, 6, 20, fenhong=30, category=1)]
        with_other = [_evt(2024, 6, 20, fenhong=30, category=1), _evt(2025, 1, 1, category=2)]
        self.assertEqual(
            PytdxSource.xdxr_fingerprint(with_cash),
            PytdxSource.xdxr_fingerprint(with_other),
        )

    def test_event_order_does_not_matter(self):
        a = [_evt(2024, 6, 20, fenhong=30), _evt(2025, 6, 18, fenhong=50)]
        b = [_evt(2025, 6, 18, fenhong=50), _evt(2024, 6, 20, fenhong=30)]
        self.assertEqual(
            PytdxSource.xdxr_fingerprint(a),
            PytdxSource.xdxr_fingerprint(b),
        )

    def test_empty_events_return_none(self):
        self.assertIsNone(PytdxSource.xdxr_fingerprint([]))

    def test_zero_factor_events_return_none(self):
        """无分红送转配股的 event 不产生复权，指纹视为无事件"""
        self.assertIsNone(PytdxSource.xdxr_fingerprint([_evt(2024, 6, 20, fenhong=0, songzhuangu=0, peigu=0)]))


class StockNameCleanTest(unittest.TestCase):
    """股票名称 XD/XR/DR 前缀清理"""

    def test_strip_xd_prefix(self):
        self.assertEqual(PytdxSource.clean_stock_name('XD贵州茅台'), '贵州茅台')

    def test_strip_xr_prefix(self):
        self.assertEqual(PytdxSource.clean_stock_name('XR中远海控'), '中远海控')

    def test_strip_dr_prefix(self):
        self.assertEqual(PytdxSource.clean_stock_name('DR平安银行'), '平安银行')

    def test_keep_plain_name(self):
        self.assertEqual(PytdxSource.clean_stock_name('贵州茅台'), '贵州茅台')

    def test_keep_st_prefix(self):
        self.assertEqual(PytdxSource.clean_stock_name('ST海航'), 'ST海航')

    def test_keep_star_st_prefix(self):
        self.assertEqual(PytdxSource.clean_stock_name('*ST金科'), '*ST金科')

    def test_strip_empty_and_none(self):
        self.assertEqual(PytdxSource.clean_stock_name(''), '')
        self.assertIsNone(PytdxSource.clean_stock_name(None))

    def test_keep_whitespace_only_prefix(self):
        """仅前缀无名称时不剥离，避免产生空名称"""
        self.assertEqual(PytdxSource.clean_stock_name('XD'), 'XD')

    def test_keep_nan(self):
        """NaN（float）原样返回，不报错"""
        import math
        nan = float('nan')
        result = PytdxSource.clean_stock_name(nan)
        self.assertTrue(isinstance(result, float) and math.isnan(result))


class FullReloadTriggerTest(unittest.TestCase):
    """全量重拉判定：仅当已记录指纹且发生变化时触发"""

    def setUp(self):
        from app.data.manager import DataManager
        self.dm = DataManager

    def test_no_stored_fp_no_reload(self):
        """首次同步（无历史指纹）不触发全量重拉"""
        self.assertFalse(self.dm._should_full_reload(None, 'abc'))

    def test_same_fp_no_reload(self):
        self.assertFalse(self.dm._should_full_reload('abc', 'abc'))

    def test_changed_fp_triggers_reload(self):
        self.assertTrue(self.dm._should_full_reload('old', 'new'))

    def test_fp_to_none_triggers_reload(self):
        """之前有除权，现在无除权 → 触发重拉（因子归零）"""
        self.assertTrue(self.dm._should_full_reload('old', ''))

    def test_none_to_fp_triggers_reload(self):
        """之前无除权，现在有除权 → 触发重拉"""
        self.assertTrue(self.dm._should_full_reload('', 'new'))


class SyncSingleStockReloadIntegrationTest(unittest.TestCase):
    """_sync_single_stock 集成：指纹变化时触发全量重拉而非增量写入"""

    def _make_df(self):
        return pd.DataFrame([{
            'trade_date': '20260808', 'open': 10.0, 'close': 10.5,
            'high': 10.6, 'low': 9.9, 'vol': 1000, 'amount': 10000.0,
        }])

    @mock.patch('app.data.manager.set_xdxr_fingerprint')
    @mock.patch('app.data.manager.get_xdxr_fingerprint', return_value='old_fp')
    @mock.patch('app.data.manager.bulk_upsert_daily_data')
    @mock.patch('app.data.db.get_collection')
    def test_fingerprint_change_triggers_full_reload(self, mock_coll, mock_bulk, mock_get_fp, mock_set_fp):
        """已记录指纹变化 → 走全量重拉，不执行增量 bulk_upsert"""
        from app.data.manager import DataManager, _NO_DATA_CACHE
        _NO_DATA_CACHE.pop('20260808', None)

        mock_coll.return_value.find_one.return_value = None  # 无历史数据

        dm = DataManager()
        dm.pytdx.get_daily_data = mock.Mock(return_value=(self._make_df(), 'pytdx'))
        dm._get_xdxr_fingerprint = mock.Mock(return_value='new_fp')
        dm._full_reload_stock = mock.Mock(return_value=True)

        result = dm._sync_single_stock('000001', '平安银行', '20260808', '20260808')

        self.assertEqual(result['status'], 'success')
        self.assertTrue(result.get('reloaded'))
        dm._full_reload_stock.assert_called_once()
        mock_bulk.assert_not_called()  # 全量重拉路径不应走增量写入
        mock_set_fp.assert_called_once_with('000001', 'new_fp')

    @mock.patch('app.data.manager.set_xdxr_fingerprint')
    @mock.patch('app.data.manager.get_xdxr_fingerprint', return_value='old_fp')
    @mock.patch('app.data.manager.bulk_upsert_daily_data')
    @mock.patch('app.data.db.get_collection')
    def test_reload_failure_falls_back_to_incremental(self, mock_coll, mock_bulk, mock_get_fp, mock_set_fp):
        """全量重拉失败 → 回退增量写入"""
        from app.data.manager import DataManager, _NO_DATA_CACHE
        _NO_DATA_CACHE.pop('20260808', None)

        mock_coll.return_value.find_one.return_value = None

        dm = DataManager()
        dm.pytdx.get_daily_data = mock.Mock(return_value=(self._make_df(), 'pytdx'))
        dm._get_xdxr_fingerprint = mock.Mock(return_value='new_fp')
        dm._full_reload_stock = mock.Mock(return_value=False)

        result = dm._sync_single_stock('000001', '平安银行', '20260808', '20260808')

        self.assertEqual(result['status'], 'success')
        self.assertFalse(result.get('reloaded'))
        mock_bulk.assert_called_once()  # 回退到增量写入

    @mock.patch('app.data.manager.set_xdxr_fingerprint')
    @mock.patch('app.data.manager.get_xdxr_fingerprint', return_value='same_fp')
    @mock.patch('app.data.manager.bulk_upsert_daily_data')
    @mock.patch('app.data.db.get_collection')
    def test_same_fingerprint_no_reload(self, mock_coll, mock_bulk, mock_get_fp, mock_set_fp):
        """指纹未变 → 正常增量写入，不触发全量重拉"""
        from app.data.manager import DataManager, _NO_DATA_CACHE
        _NO_DATA_CACHE.pop('20260808', None)

        mock_coll.return_value.find_one.return_value = None

        dm = DataManager()
        dm.pytdx.get_daily_data = mock.Mock(return_value=(self._make_df(), 'pytdx'))
        dm._get_xdxr_fingerprint = mock.Mock(return_value='same_fp')
        dm._full_reload_stock = mock.Mock()

        result = dm._sync_single_stock('000001', '平安银行', '20260808', '20260808')

        self.assertEqual(result['status'], 'success')
        self.assertFalse(result.get('reloaded'))
        dm._full_reload_stock.assert_not_called()
        mock_bulk.assert_called_once()


if __name__ == '__main__':
    unittest.main()
