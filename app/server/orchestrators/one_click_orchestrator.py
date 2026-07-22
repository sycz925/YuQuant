"""
One Click Update Orchestrator - 一键更新编排器
流程：指数同步 → 个股同步 → 板块同步 → 个股RPS → 板块RPS → PE同步 → 预计算
"""
import logging
from typing import List, Dict, Optional

from app.server.orchestrators.base import BaseOrchestrator

logger = logging.getLogger(__name__)


class OneClickUpdateOrchestrator(BaseOrchestrator):
    """
    一键更新编排器
    流程：指数同步 → 个股同步 → 板块同步 → 个股RPS → 板块RPS → PE同步 → 预计算
    7个步骤严格顺序执行，任一步骤失败则停止
    """
    
    def get_steps(self) -> List[Dict[str, str]]:
        return [
            {'key': 'sync_index', 'name': '同步指数'},
            {'key': 'sync_stocks', 'name': '同步个股'},
            {'key': 'sync_sectors', 'name': '同步板块'},
            {'key': 'rps_stock', 'name': '计算个股RPS'},
            {'key': 'rps_sector', 'name': '计算板块RPS'},
            {'key': 'sync_pe', 'name': '更新PE'},
            {'key': 'precompute', 'name': '预计算基础数据'},
        ]
    
    def execute_step(self, step_key: str, task_id: str, target_date: Optional[str]) -> None:
        """执行单个步骤"""
        from app.server.factories import (
            get_index_factory, get_stock_factory, 
            get_sector_factory, get_market_aggregator
        )
        
        step_idx = next(i for i, s in enumerate(self.get_steps()) if s['key'] == step_key)
        callback = self._make_callback(task_id, step_idx)
        
        if step_key == 'sync_index':
            factory = get_index_factory()
            factory.sync_kline(target_date, task_id=task_id, progress_callback=callback)
        
        elif step_key == 'sync_stocks':
            factory = get_stock_factory()
            factory.sync_daily(target_date, task_id=task_id, progress_callback=callback)
        
        elif step_key == 'sync_sectors':
            factory = get_sector_factory()
            factory.sync_daily(target_date, task_id=task_id, progress_callback=callback)
        
        elif step_key == 'rps_stock':
            factory = get_stock_factory()
            factory.compute_chg(target_date, callback)
            factory.compute_rps(target_date, callback)
        
        elif step_key == 'rps_sector':
            factory = get_sector_factory()
            factory.compute_chg(target_date, callback)
            factory.compute_rps(target_date, callback)
        
        elif step_key == 'sync_pe':
            factory = get_index_factory()
            factory.sync_pe(target_date, callback)
        
        elif step_key == 'precompute':
            date = target_date or self._get_today()
            aggregator = get_market_aggregator()
            aggregator.run_full_pipeline(date, callback)
    
    def _get_today(self) -> str:
        """获取今日日期"""
        from datetime import datetime
        return datetime.now().strftime('%Y%m%d')
