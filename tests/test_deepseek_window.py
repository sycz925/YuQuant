"""DeepSeek 时间窗口规则测试：高峰/空闲时段边界

规则（北京时间）：
- 高峰时段：周一至周五（不含中国法定节假日）9:00-12:00、14:00-18:00
- 空闲时段：其余全部时间，含周末与法定节假日全天

锁定 `is_peak_time()` 的边界行为，防止后续改动破坏窗口定义。
"""
import unittest
from datetime import datetime

from app.server.services.deepseek_analyst import is_peak_time


def _at(date_str: str, hhmm: str) -> datetime:
    return datetime.strptime(f'{date_str} {hhmm}', '%Y-%m-%d %H:%M')


class TestDeepSeekPeakWindow(unittest.TestCase):
    # 2026-10-19 是周一（交易日）
    MONDAY = '2026-10-19'

    def test_morning_boundaries(self):
        self.assertFalse(is_peak_time(_at(self.MONDAY, '08:59')), '9点前应为空闲')
        self.assertTrue(is_peak_time(_at(self.MONDAY, '09:00')), '9点整进入高峰')
        self.assertTrue(is_peak_time(_at(self.MONDAY, '11:59')), '11:59 仍在高峰')
        self.assertFalse(is_peak_time(_at(self.MONDAY, '12:00')), '12点整转空闲')

    def test_afternoon_boundaries(self):
        self.assertFalse(is_peak_time(_at(self.MONDAY, '13:59')), '14点前为空闲')
        self.assertTrue(is_peak_time(_at(self.MONDAY, '14:00')), '14点整进入高峰')
        self.assertTrue(is_peak_time(_at(self.MONDAY, '17:59')), '17:59 仍在高峰')
        self.assertFalse(is_peak_time(_at(self.MONDAY, '18:00')), '18点整转空闲')

    def test_night_is_idle(self):
        self.assertFalse(is_peak_time(_at(self.MONDAY, '23:30')))
        self.assertFalse(is_peak_time(_at(self.MONDAY, '00:30')))

    def test_weekend_always_idle(self):
        # 2026-10-24 周六 / 2026-10-25 周日
        self.assertFalse(is_peak_time(_at('2026-10-24', '10:00')))
        self.assertFalse(is_peak_time(_at('2026-10-25', '15:00')))

    def test_holiday_always_idle(self):
        # 2026-10-01 国庆（法定节假日），落在高峰时间段也应空闲
        self.assertFalse(is_peak_time(_at('2026-10-01', '10:00')))
        self.assertFalse(is_peak_time(_at('2026-10-01', '15:00')))


if __name__ == '__main__':
    unittest.main()
