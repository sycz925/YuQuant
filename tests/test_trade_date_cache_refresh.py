"""
回归测试：一键更新完成后必须刷新交易日缓存。

背景：/health 的 latest_trade_date 来自内存缓存（app/server/cache.py），
缓存仅在服务启动时初始化一次。此前 refresh_trade_dates() 从未被调用，
导致一键更新写入新交易日（如 20260817）后缓存仍停留在旧值（20260814），
前端 /review/20260814 页面因 currentDate == latestTradeDate 而禁用"后一天"。
"""
import unittest
from unittest import mock

from app.server.orchestrators.one_click_orchestrator import OneClickUpdateOrchestrator


class TradeDateCacheRefreshTest(unittest.TestCase):
    """一键更新完成后必须调用 refresh_trade_dates() 刷新缓存"""

    @mock.patch('app.data.task_manager.get_task_manager')
    @mock.patch('app.server.orchestrators.one_click_orchestrator.refresh_trade_dates')
    def test_one_click_completion_refreshes_cache(self, mock_refresh, mock_tm):
        mock_tm.return_value.is_cancelled.return_value = False
        orch = OneClickUpdateOrchestrator()
        orch.task_repo = mock.MagicMock()
        orch.execute_step = mock.MagicMock()

        orch._run('task_id', [])

        mock_refresh.assert_called_once()


if __name__ == '__main__':
    unittest.main()
