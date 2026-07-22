"""
Market Aggregator - 市场聚合器
跨数据域的聚合计算
"""
import logging
from typing import Any, Callable, Dict, List, Optional

from app.server.factories.base import ComputeResult, PipelineResult, ProgressCallback
from app.server.repositories.stock_repository import StockRepository
from app.server.repositories.index_repository import IndexRepository
from app.server.repositories.sector_repository import SectorRepository
from app.server.repositories.market_repository import MarketRepository

logger = logging.getLogger(__name__)


class MarketAggregator:
    """
    市场聚合器 — 跨数据域的聚合计算
    依赖三大工厂提供的数据，不直接操作原始集合
    """
    
    def __init__(self, stock_repo: StockRepository = None,
                 index_repo: IndexRepository = None,
                 sector_repo: SectorRepository = None,
                 market_repo: MarketRepository = None):
        self.stock_repo = stock_repo or StockRepository()
        self.index_repo = index_repo or IndexRepository()
        self.sector_repo = sector_repo or SectorRepository()
        self.market_repo = market_repo or MarketRepository()
    
    def clear_all_tasks(self) -> Dict[str, Any]:
        """清除所有任务"""
        from app.data.db import get_db
        
        db = get_db()
        result = db['sync_tasks'].delete_many({})
        return {"success": True, "message": f"已清除 {result.deleted_count} 个任务"}
    
    def delete_rps_data(self, target: str) -> Dict[str, Any]:
        """删除 RPS 数据"""
        from app.data.db import get_db
        
        db = get_db()
        
        collections = {
            'stock': 'stock_daily',
            'sector': 'sector_daily',
            'index': 'index_daily',
            'all': None
        }
        
        rps_fields = ['rps_10', 'rps_20', 'rps_50', 'rps_120', 'rps_250']
        
        if target == 'all':
            targets = ['stock_daily', 'sector_daily', 'index_daily']
        else:
            targets = [collections.get(target, 'stock_daily')]
        
        total_updated = 0
        for coll_name in targets:
            unset_doc = {field: '' for field in rps_fields}
            result = db[coll_name].update_many({}, {'$unset': unset_doc})
            total_updated += result.modified_count
        
        return {
            "success": True,
            "message": f"已清除 {total_updated} 条记录的 RPS 数据",
            "updated": total_updated
        }
    
    def calculate_rps(self, target: str = 'all', max_dates: Optional[int] = None,
                      progress_callback: Callable = None) -> Dict[str, Any]:
        """计算 RPS（支持 stock/sector/all）"""
        callback = ProgressCallback(progress_callback)
        
        try:
            from app.engine.factor_engine import FactorEngine
            engine = FactorEngine()
            
            targets = ['stock', 'sector'] if target == 'all' else [target]
            results = {}
            
            for t in targets:
                callback.update(0, 1, f'计算 {t} RPS...')
                result = engine.calculate_rps(data_type=t, max_dates=max_dates)
                results[t] = result
            
            callback.complete('RPS 计算完成')
            return {"success": True, "results": results}
        except Exception as e:
            logger.error(f'计算 RPS 失败: {e}')
            return {"success": False, "message": str(e)}
    
    def precompute_base_data(self, target_date: str,
                             task_id: str = None,
                             progress_callback: Callable = None) -> ComputeResult:
        """
        预计算 base_data_daily + market_daily
        :param target_date: 必须指定日期
        :param task_id: 任务ID
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 100, '计算 CR5/CR10/MA/NH-NL...')
            
            # 调用原始的预计算函数
            from app.server.api.factors import _run_precompute_base_for_date
            _run_precompute_base_for_date(task_id, target_date, is_external=True)
            
            callback.complete('基础数据预计算完成')
            return ComputeResult(success=True, message='基础数据预计算完成')
        except Exception as e:
            logger.error(f'预计算基础数据失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def generate_market_overview(self, target_date: str,
                                 progress_callback: Callable = None) -> ComputeResult:
        """生成市场总览（写入 market_daily）"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 100, '生成市场总览...')
            
            # 调用原始的市场总览生成函数
            from app.server.api.market_review import generate_market_overview
            generate_market_overview(target_date)
            
            callback.complete('市场总览生成完成')
            return ComputeResult(success=True, message='市场总览生成完成')
        except Exception as e:
            logger.error(f'生成市场总览失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def analyze_new_high_blocks(self, target_date: str,
                                progress_callback: Callable = None) -> ComputeResult:
        """分析新高板块（写入 market_daily.new_high）"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 100, '分析新高板块...')
            
            # 调用原始的新高板块分析函数
            from app.server.api.market_review import analyze_new_high_blocks
            analyze_new_high_blocks(target_date)
            
            callback.complete('新高板块分析完成')
            return ComputeResult(success=True, message='新高板块分析完成')
        except Exception as e:
            logger.error(f'分析新高板块失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def run_full_pipeline(self, target_date: str,
                          task_id: str = None,
                          progress_callback: Callable = None) -> PipelineResult:
        """
        执行聚合全流程：precompute_base_data → generate_market_overview → analyze_new_high_blocks
        """
        result = PipelineResult()
        
        result.add_step('base_data', self.precompute_base_data(target_date, task_id, progress_callback))
        result.add_step('overview', self.generate_market_overview(target_date, progress_callback))
        result.add_step('new_high', self.analyze_new_high_blocks(target_date, progress_callback))
        
        return result
