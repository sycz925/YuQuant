# app/server/services/restricted_release_service.py
"""限售股解禁数据 Service"""

from typing import List, Dict, Any
import akshare as ak
import pandas as pd
from app.server.repositories.restricted_release_repository import (
    get_restricted_release_repository
)


class RestrictedReleaseService:
    """限售股解禁数据服务层"""

    def __init__(self):
        self.repo = get_restricted_release_repository()

    @staticmethod
    def _get_market(code: str) -> str:
        """根据股票代码判断市场板块"""
        code = str(code).strip()
        if code.startswith(('600', '601', '603', '605')):
            return '上证'
        elif code.startswith(('000', '001', '002', '003')):
            return '深综'
        elif code.startswith('300'):
            return '创业板'
        elif code.startswith('688'):
            return '科创板'
        else:
            return '其他'

    def get_monthly_summary(self, year: int) -> Dict[str, Any]:
        """获取指定年份的月度汇总"""
        months = self.repo.get_monthly_summary(year)
        
        # 获取各月板块分布
        monthly_market = self.repo.get_monthly_market_distribution(year)
        
        # 补充12个月，没有数据的月份显示为0
        month_map = {m["month"]: m for m in months}
        market_map = {m["month"]: m.get("markets", {}) for m in monthly_market}
        
        full_months = []
        for m in range(1, 13):
            month_data = month_map.get(m, {"month": m, "total_value": 0, "stock_count": 0})
            markets = market_map.get(m, {})
            
            # 计算板块比例
            total = month_data["total_value"]
            market_ratio = {}
            for market_name in ['上证', '深综', '创业板', '科创板']:
                market_value = markets.get(market_name, 0)
                market_ratio[market_name] = round(market_value / total * 100, 1) if total > 0 else 0
            
            full_months.append({
                **month_data,
                "market_ratio": market_ratio
            })
        
        return {"year": year, "months": full_months}

    def get_monthly_detail(self, year: int, month: int) -> Dict[str, Any]:
        """获取指定月份的解禁详情"""
        stocks = self.repo.get_monthly_detail(year, month)
        return {"year": year, "month": month, "stocks": stocks}

    def sync_year_data(self, year: int) -> Dict[str, Any]:
        """同步指定年份的解禁数据"""
        try:
            # 获取汇总数据
            start_date = f"{year}0101"
            end_date = f"{year}1231"
            
            # 调用 akshare 获取全市场解禁汇总
            summary_df = ak.stock_restricted_release_summary_em(
                symbol="全部股票",
                start_date=start_date,
                end_date=end_date
            )
            
            if summary_df is None or len(summary_df) == 0:
                return {"success": False, "message": "未获取到数据"}
            
            # 获取详情数据
            detail_df = ak.stock_restricted_release_detail_em(
                start_date=start_date,
                end_date=end_date
            )
            
            # 转换为字典列表
            records = []
            if detail_df is not None and len(detail_df) > 0:
                for _, row in detail_df.iterrows():
                    record = {
                        "stock_code": str(row.get("股票代码", "")),
                        "stock_name": str(row.get("股票简称", "")),
                        "release_date": str(row.get("解禁时间", "")),
                        "release_type": str(row.get("限售股类型", "")),
                        "release_shares": float(row.get("解禁数量", 0)) / 10000,  # 转换为万股
                        "release_market_value": float(row.get("实际解禁市值", 0)) / 1e8,  # 转换为亿元
                        "float_ratio": float(row.get("占解禁前流通市值比例", 0)),
                        "close_price": float(row.get("解禁前一交易日收盘价", 0)),
                        "created_at": pd.Timestamp.now(),
                        "updated_at": pd.Timestamp.now()
                    }
                    records.append(record)
            
            # 先删除旧数据，再插入新数据
            self.repo.delete_by_year(year)
            inserted_count = self.repo.upsert_many(records)
            
            return {
                "success": True,
                "message": f"同步成功",
                "year": year,
                "total_count": len(records),
                "inserted_count": inserted_count
            }
            
        except Exception as e:
            return {"success": False, "message": str(e)}


# 单例
_service_instance = None

def get_restricted_release_service() -> RestrictedReleaseService:
    global _service_instance
    if _service_instance is None:
        _service_instance = RestrictedReleaseService()
    return _service_instance
