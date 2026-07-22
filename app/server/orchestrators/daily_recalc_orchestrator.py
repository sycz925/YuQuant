"""
Daily Recalc Orchestrator - 单日重算编排器
流程：个股RPS → 板块RPS → 预计算基础数据
"""
import logging
from typing import List, Dict, Optional

from app.server.orchestrators.base import BaseOrchestrator

logger = logging.getLogger(__name__)


class DailyRecalcOrchestrator(BaseOrchestrator):
    """
    单日重算编排器
    流程：个股RPS → 板块RPS → 预计算基础数据
    用于补算指定历史日期的数据
    """
    
    def get_steps(self) -> List[Dict[str, str]]:
        return [
            {'key': 'rps_stock', 'name': '计算个股RPS'},
            {'key': 'rps_sector', 'name': '计算板块RPS'},
            {'key': 'precompute', 'name': '预计算基础数据'},
        ]
    
    def execute(self, target_date: str) -> str:
        """单日重算必须指定日期"""
        if not target_date:
            raise ValueError('单日重算必须指定 target_date')
        return super().execute(target_date)
    
    def execute_step(self, step_key: str, task_id: str, target_date: Optional[str]) -> None:
        """执行单个步骤"""
        from app.server.factories import get_stock_factory, get_sector_factory, get_market_aggregator
        
        step_idx = next(i for i, s in enumerate(self.get_steps()) if s['key'] == step_key)
        callback = self._make_callback(task_id, step_idx)
        
        if step_key == 'rps_stock':
            factory = get_stock_factory()
            factory.compute_chg(target_date, callback)
            factory.compute_rps(target_date, callback)
        
        elif step_key == 'rps_sector':
            factory = get_sector_factory()
            factory.compute_chg(target_date, callback)
            factory.compute_rps(target_date, callback)
        
        elif step_key == 'precompute':
            aggregator = get_market_aggregator()
            aggregator.run_full_pipeline(target_date, callback)
