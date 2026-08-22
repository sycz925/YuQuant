"""watchlist 删除时联动清理预警记录单测：delete_alerts by code"""
import unittest
from unittest.mock import Mock, MagicMock, patch

from app.engine.watchlist_alert import delete_alerts


class DeleteAlertsTest(unittest.TestCase):
    """delete_alerts：按 code 删除 watchlist_alerts，返回删除数"""

    def test_deletes_matching_code(self):
        coll = Mock()
        coll.delete_many.return_value.deleted_count = 3
        db = MagicMock()
        db.__getitem__.return_value = coll

        with patch('app.data.db.get_db', return_value=db):
            count = delete_alerts('600000')

        coll.delete_many.assert_called_once_with({'code': '600000'})
        self.assertEqual(count, 3)

    def test_zero_when_none(self):
        coll = Mock()
        coll.delete_many.return_value.deleted_count = 0
        db = MagicMock()
        db.__getitem__.return_value = coll

        with patch('app.data.db.get_db', return_value=db):
            count = delete_alerts('999999')

        coll.delete_many.assert_called_once_with({'code': '999999'})
        self.assertEqual(count, 0)


if __name__ == '__main__':
    unittest.main()