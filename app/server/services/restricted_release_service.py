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

    def get_monthly_summary(self, year: int) -> Dict[str, Any]:
        """获取指定年份的月度汇总"""
        months = self.repo.get_monthly_summary(year)
        
        # 补充12个月，没有数据的月份显示为0
        month_map = {m["month"]: m for m in months}
        full_months = []
        for m in range(1, 13):
            if m in month_map:
                full_months.append(month_map[m])
            else:
                full_months.append({"month": m, "total_value": 0, "stock_count": 0})
        
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
