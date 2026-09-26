"""限售股解禁 API 端点集成测试"""

import pytest
from fastapi.testclient import TestClient
from app.server.main import app

client = TestClient(app)


class TestRestrictedReleaseAPI:
    """限售股解禁 API 测试"""

    def test_summary_requires_year(self):
        """summary 端点必须传 year 参数"""
        resp = client.get("/api/restricted-release/summary")
        assert resp.status_code == 422

    def test_summary_rejects_invalid_year(self):
        """summary 端点拒绝无效年份"""
        resp = client.get("/api/restricted-release/summary?year=2009")
        assert resp.status_code == 422
        data = resp.json()
        assert data["code"] == 422

    def test_summary_returns_months(self):
        """summary 端点返回 12 个月数据"""
        resp = client.get("/api/restricted-release/summary?year=2026")
        assert resp.status_code == 200
        data = resp.json()
        assert data["year"] == 2026
        assert isinstance(data["months"], list)
        assert len(data["months"]) == 12

    def test_summary_month_fields(self):
        """summary 每个月包含 month, total_value, stock_count"""
        resp = client.get("/api/restricted-release/summary?year=2026")
        assert resp.status_code == 200
        for m in resp.json()["months"]:
            assert "month" in m
            assert "total_value" in m
            assert "stock_count" in m
            assert 1 <= m["month"] <= 12

    def test_detail_requires_year_and_month(self):
        """detail 端点必须传 year 和 month"""
        resp = client.get("/api/restricted-release/detail?year=2026")
        assert resp.status_code == 422

        resp = client.get("/api/restricted-release/detail?month=9")
        assert resp.status_code == 422

    def test_detail_rejects_invalid_month(self):
        """detail 端点拒绝无效月份"""
        resp = client.get("/api/restricted-release/detail?year=2026&month=13")
        assert resp.status_code == 422

    def test_detail_returns_stocks_list(self):
        """detail 端点返回 stocks 列表"""
        resp = client.get("/api/restricted-release/detail?year=2026&month=9")
        assert resp.status_code == 200
        data = resp.json()
        assert data["year"] == 2026
        assert data["month"] == 9
        assert isinstance(data["stocks"], list)

    def test_detail_stock_fields(self):
        """detail 每只股票包含必要字段"""
        resp = client.get("/api/restricted-release/detail?year=2026&month=9")
        assert resp.status_code == 200
        stocks = resp.json()["stocks"]
        if stocks:
            stock = stocks[0]
            required = [
                "stock_code", "stock_name", "release_date",
                "release_type", "release_shares", "release_market_value",
                "float_ratio", "close_price"
            ]
            for field in required:
                assert field in stock, f"Missing field: {field}"

    def test_sync_requires_year(self):
        """sync 端点必须传 year 参数"""
        resp = client.post("/api/restricted-release/sync")
        assert resp.status_code == 422

    def test_sync_rejects_invalid_year(self):
        """sync 端点拒绝无效年份"""
        resp = client.post("/api/restricted-release/sync?year=2009")
        assert resp.status_code == 422

    def test_sync_returns_success(self):
        """sync 端点成功同步并返回结果"""
        resp = client.post("/api/restricted-release/sync?year=2025", timeout=60)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "total_count" in data
        assert "inserted_count" in data
        assert data["year"] == 2025
