"""限售股解禁数据 Repository"""

from typing import List, Dict, Any
from datetime import datetime
from app.data.db import get_db


class RestrictedReleaseRepository:
    """限售股解禁数据仓储层"""

    def __init__(self):
        self.collection = get_db()['stock_restricted_release']

    def get_monthly_summary(self, year: int) -> List[Dict[str, Any]]:
        """获取指定年份的月度汇总"""
        pipeline = [
            {
                "$match": {
                    "release_date": {
                        "$gte": f"{year}-01-01",
                        "$lte": f"{year}-12-31"
                    }
                }
            },
            {
                "$group": {
                    "_id": {"$substr": ["$release_date", 5, 2]},
                    "total_value": {"$sum": "$release_market_value"},
                    "stock_count": {"$sum": 1}
                }
            },
            {"$sort": {"_id": 1}}
        ]
        
        results = list(self.collection.aggregate(pipeline))
        return [
            {
                "month": int(r["_id"]),
                "total_value": round(r["total_value"], 2),
                "stock_count": r["stock_count"]
            }
            for r in results
        ]

    def get_monthly_detail(self, year: int, month: int) -> List[Dict[str, Any]]:
        """获取指定月份的解禁详情"""
        month_str = f"{month:02d}"
        start_date = f"{year}-{month_str}-01"
        end_date = f"{year}-{month_str}-31"
        
        results = self.collection.find(
            {"release_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0}
        ).sort("release_date", 1)
        
        return list(results)

    def upsert_many(self, records: List[Dict[str, Any]]) -> int:
        """批量插入或更新解禁数据"""
        count = 0
        for record in records:
            try:
                self.collection.update_one(
                    {
                        "stock_code": record["stock_code"],
                        "release_date": record["release_date"],
                        "release_type": record["release_type"]
                    },
                    {"$set": record},
                    upsert=True
                )
                count += 1
            except Exception as e:
                print(f"插入失败 {record.get('stock_code')}: {e}")
        return count

    def delete_by_year(self, year: int) -> int:
        """删除指定年份的数据（重新同步时使用）"""
        result = self.collection.delete_many(
            {"release_date": {"$regex": f"^{year}-"}}
        )
        return result.deleted_count


# 单例
_repo_instance = None

def get_restricted_release_repository() -> RestrictedReleaseRepository:
    global _repo_instance
    if _repo_instance is None:
        _repo_instance = RestrictedReleaseRepository()
    return _repo_instance
