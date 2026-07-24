"""
Stock Factory - 个股工厂
管理个股数据的同步与衍生计算
"""
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from app.server.factories.base import SyncResult, ComputeResult, PipelineResult, ProgressCallback
from app.server.repositories.stock_repository import StockRepository

logger = logging.getLogger(__name__)


class StockFactory:
    """个股工厂 — 管理个股数据的同步与衍生计算"""
    
    def __init__(self, stock_repo: StockRepository = None):
        self.repo = stock_repo or StockRepository()
    
    def get_stock_rps(self, code: str, start_date: Optional[str] = None,
                      end_date: Optional[str] = None, period: str = 'day') -> Optional[Dict[str, Any]]:
        """获取个股/板块/指数的 RPS 数据"""
        from app.data.db import get_db
        
        db = get_db()
        
        # 根据代码前缀判断集合
        if code.startswith('88'):
            coll = db['sector_daily']
        elif code.startswith(('00', '30', '60', '68')):
            coll = db['stock_daily']
        else:
            coll = db['index_daily']
        
        query = {"stock_code": code}
        if start_date or end_date:
            query["trade_date"] = {}
            if start_date:
                query["trade_date"]["$gte"] = start_date
            if end_date:
                query["trade_date"]["$lte"] = end_date
        
        cursor = coll.find(
            query,
            {"_id": 0, "stock_code": 1, "trade_date": 1,
             "rps_10": 1, "rps_20": 1, "rps_50": 1, "rps_120": 1, "rps_250": 1,
             "chg_10": 1, "chg_20": 1, "chg_50": 1, "chg_120": 1, "chg_250": 1}
        ).sort("trade_date", 1)
        data = list(cursor)
        
        if not data:
            return None
        
        result = [
            {
                "date": item["trade_date"], "code": item["stock_code"],
                "rps_10": item.get("rps_10"), "rps_20": item.get("rps_20"),
                "rps_50": item.get("rps_50"), "rps_120": item.get("rps_120"),
                "rps_250": item.get("rps_250"),
                "chg_10": item.get("chg_10"), "chg_20": item.get("chg_20"),
                "chg_50": item.get("chg_50"), "chg_120": item.get("chg_120"),
                "chg_250": item.get("chg_250"),
            }
            for item in data
        ]
        
        # 按周期聚合
        if period == "week":
            result = self._aggregate_by_week(result)
        elif period == "month":
            result = self._aggregate_by_month(result)
        
        return {"code": code, "period": period, "total": len(result), "data": result}
    
    def _aggregate_by_week(self, data: List[Dict]) -> List[Dict]:
        """按周聚合 RPS 数据"""
        aggregated = []
        current_week = None
        week_items = []
        
        for item in data:
            dt = datetime.strptime(item["date"], "%Y%m%d")
            year, week_num, _ = dt.isocalendar()
            week_key = f"{year}-W{week_num:02d}"
            
            if current_week != week_key and week_items:
                last_rps = week_items[-1].copy()
                last_rps["date"] = week_items[0]["date"]
                aggregated.append(last_rps)
                week_items = []
            
            current_week = week_key
            week_items.append(item)
        
        if week_items:
            last_rps = week_items[-1].copy()
            last_rps["date"] = week_items[0]["date"]
            aggregated.append(last_rps)
        
        return aggregated
    
    def _aggregate_by_month(self, data: List[Dict]) -> List[Dict]:
        """按月聚合 RPS 数据"""
        aggregated = []
        current_month = None
        month_items = []
        
        for item in data:
            month_key = item["date"][:6]
            
            if current_month != month_key and month_items:
                last_rps = month_items[-1].copy()
                last_rps["date"] = month_items[0]["date"]
                aggregated.append(last_rps)
                month_items = []
            
            current_month = month_key
            month_items.append(item)
        
        if month_items:
            last_rps = month_items[-1].copy()
            last_rps["date"] = month_items[0]["date"]
            aggregated.append(last_rps)
        
        return aggregated
    
    def get_rps_by_date(self, trade_date: str, min_rps: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """获取指定日期的 RPS 数据"""
        from app.data.db import get_db
        
        db = get_db()
        query = {"trade_date": trade_date}
        rps_projection = {
            "_id": 0, "stock_code": 1, "trade_date": 1,
            "rps_10": 1, "rps_20": 1, "rps_50": 1, "rps_120": 1, "rps_250": 1,
            "chg_10": 1, "chg_20": 1, "chg_50": 1, "chg_120": 1, "chg_250": 1,
        }
        
        data = []
        for coll_name in ['stock_daily', 'sector_daily', 'index_daily']:
            cursor = db[coll_name].find(query, rps_projection)
            data.extend(list(cursor))
        
        if not data:
            return None
        
        result = []
        for item in data:
            rps_record = {
                "code": item["stock_code"], "date": item["trade_date"],
                "rps_10": item.get("rps_10"), "rps_20": item.get("rps_20"),
                "rps_50": item.get("rps_50"), "rps_120": item.get("rps_120"),
                "rps_250": item.get("rps_250"),
                "chg_10": item.get("chg_10"), "chg_20": item.get("chg_20"),
                "chg_50": item.get("chg_50"), "chg_120": item.get("chg_120"),
                "chg_250": item.get("chg_250"),
            }
            if min_rps is not None:
                has_valid_rps = any(
                    rps_record[r] is not None and rps_record[r] >= min_rps
                    for r in ["rps_10", "rps_20", "rps_50", "rps_120", "rps_250"]
                )
                if not has_valid_rps:
                    continue
            result.append(rps_record)
        
        return {"trade_date": trade_date, "total": len(result), "data": result}
    
    # 数据源优先级
    DATA_SOURCES = ['pytdx', 'akshare', 'baostock', 'yfinance']
    
    def sync_daily(self, target_date: Optional[str] = None,
                   max_workers: int = 4,
                   task_id: str = None,
                   progress_callback: Callable = None) -> SyncResult:
        """
        同步个股日线数据（多数据源备份）
        数据源优先级：pytdx → akshare → baostock → yfinance
        :param target_date: 指定日期 YYYYMMDD，None 同步到最新
        :param task_id: 任务ID，用于更新进度
        :param progress_callback: 进度回调函数 (current, total, message)
        :return: SyncResult，失败率超过5%则标记失败
        """
        callback = ProgressCallback(progress_callback)

        try:
            enabled_stocks = self.repo.get_enabled_codes()
            total = len(enabled_stocks)

            if total == 0:
                return SyncResult(success=True, message='无启用股票', total=0)

            callback.update(0, total, '开始同步个股日线...')

            # 调用 data_manager 的同步逻辑（已包含多数据源备份）
            from app.data.manager import get_data_manager
            dm = get_data_manager()

            end_date = target_date or datetime.now().strftime('%Y%m%d')

            # 创建内部回调，更新步骤进度而不是顶层进度
            def step_progress_callback(current, total, message=''):
                callback.update(current, total, message)

            # 传递 task_id 和 progress_callback 给 dm.sync_daily_data()
            # progress_callback 优先更新步骤进度，而不是顶层进度
            result = dm.sync_daily_data(
                stock_codes=enabled_stocks,
                end_date=end_date,
                task_id=task_id,
                max_workers=max_workers,
                is_external=True,
                progress_callback=step_progress_callback
            )
            
            success_count = result.get('success', 0)
            fail_count = result.get('fail', 0)
            skipped_count = result.get('skipped', 0)
            sources = result.get('sources', {})
            
            # 计算失败率
            if total > 0:
                fail_rate = fail_count / total
                if fail_rate > 0.05:
                    callback.complete(f'个股日线同步失败: 失败率 {fail_rate:.1%} 超过阈值')
                    return SyncResult(
                        success=False,
                        message=f'失败率 {fail_rate:.1%} 超过5%阈值',
                        total=total,
                        synced=success_count,
                        failed=fail_count,
                        skipped=skipped_count
                    )
            
            source_msg = ', '.join([f"{k}: {v}" for k, v in sources.items()])
            callback.complete(f'个股日线同步完成: 成功 {success_count}, 失败 {fail_count}, 跳过 {skipped_count}。数据源: {source_msg}')
            return SyncResult(
                success=True,
                message=f'个股日线同步完成: 成功 {success_count}, 失败 {fail_count}, 跳过 {skipped_count}。数据源: {source_msg}',
                total=total,
                synced=success_count,
                failed=fail_count,
                skipped=skipped_count
            )
        except Exception as e:
            logger.error(f'同步个股日线失败: {e}')
            return SyncResult(success=False, message=str(e))
    
    def compute_rps(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """
        计算个股 RPS
        :param target_date: 指定日期重算，None 从最新日期回溯
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算个股RPS...')
            
            # 调用 factor_engine 的 RPS 计算
            from app.engine.factor_engine import FactorEngine
            engine = FactorEngine()
            result = engine.calculate_rps(data_type='stock', max_dates=None)
            
            callback.complete(f'个股RPS计算完成: {result}')
            return ComputeResult(success=True, message=f'个股RPS计算完成: {result}')
        except Exception as e:
            logger.error(f'计算个股RPS失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def compute_chg(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """计算个股区间涨幅（5/10/20/50/120/250日）"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算个股涨幅...')
            
            # 调用 data_manager 的涨幅计算
            from app.data.manager import get_data_manager
            dm = get_data_manager()
            dm.calculate_chg_fields(target='stock', trade_date=target_date)
            
            callback.complete('个股涨幅计算完成')
            return ComputeResult(success=True, message='个股涨幅计算完成')
        except Exception as e:
            logger.error(f'计算个股涨幅失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def compute_ma(self, target_date: Optional[str] = None,
                   progress_callback: Callable = None) -> ComputeResult:
        """计算个股均线（MA10/20/50/120 + VOL_MA5/10/20/50）"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算个股均线...')
            
            # 调用 data_manager 的均线计算
            from app.data.manager import get_data_manager
            dm = get_data_manager()
            dm.calculate_all_derived_fields(target='stock', trade_date=target_date)
            
            callback.complete('个股均线计算完成')
            return ComputeResult(success=True, message='个股均线计算完成')
        except Exception as e:
            logger.error(f'计算个股均线失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def run_full_pipeline(self, target_date: Optional[str] = None,
                          progress_callback: Callable = None) -> PipelineResult:
        """
        执行个股全流程：sync_daily → compute_chg → compute_ma → compute_rps
        一键更新时调用此方法
        注意：compute_rps 依赖 compute_chg 的结果，顺序不可调换
        """
        result = PipelineResult()
        
        result.add_step('sync_daily', self.sync_daily(target_date, progress_callback=progress_callback))
        result.add_step('compute_chg', self.compute_chg(target_date, progress_callback))
        result.add_step('compute_ma', self.compute_ma(target_date, progress_callback))
        result.add_step('compute_rps', self.compute_rps(target_date, progress_callback))
        
        return result
