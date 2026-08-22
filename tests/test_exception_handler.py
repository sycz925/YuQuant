"""全局异常处理器测试：响应骨架 + P0 脱敏回归"""
import json
import unittest
from unittest import mock

from app.server.main import global_exception_handler


class GlobalExceptionHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def _invoke(self, exc):
        return await global_exception_handler(mock.Mock(), exc)

    async def test_returns_500_with_code(self):
        resp = await self._invoke(RuntimeError('boom'))
        self.assertEqual(resp.status_code, 500)
        body = json.loads(resp.body)
        self.assertEqual(body['code'], 500)

    async def test_does_not_leak_exception_detail(self):
        """P0：异常 detail 不得回传内部堆栈/敏感串。当前 main.py 会泄露，此测试应为红，修复后转绿。"""
        secret = 'internal_secret_do_not_leak'
        resp = await self._invoke(RuntimeError(secret))
        body = json.loads(resp.body)
        self.assertNotIn(secret, json.dumps(body, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
