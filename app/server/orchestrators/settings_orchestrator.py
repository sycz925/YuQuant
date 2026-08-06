"""
Settings Orchestrator - 设置页面任务编排器
用于处理 Settings 页面的同步、计算等操作
"""
import logging
from typing import List, Dict, Optional

from app.server.orchestrators.base import BaseOrchestrator

logger = logging.getLogger(__name__)


class SettingsOrchestrator(BaseOrchestrator):
    """
    设置页面任务编排器
    支持单步执行各种同步/计算任务
    """

    def get_steps(self) -> List[Dict[str, str]]:
        # Settings 页面的步骤在执行时动态确定
        return [{'key': 'settings_task', 'name': '设置任务'}]

    def execute(self, task_type: str, **kwargs) -> str:
        """执行设置页面任务"""
        import uuid
        name_by_type = {
            'sync_indices': '同步指数',
            'sync_daily': '同步个股',
            'calculate_rps': '计算个股RPS',
            'sync_sectors': '同步板块',
            'calculate_sector_rps': '计算板块RPS',
            'sync_index_pe': '更新PE',
            'precompute_base': '预计算基础数据',
        }
        steps = self._get_steps_for_type(task_type)
        task_id = str(uuid.uuid4())
        self.task_repo.create_task(task_id, steps, name=name_by_type.get(task_type, task_type))

        import threading
        thread = threading.Thread(
            target=self._run_task,
            args=(task_id, task_type, kwargs),
            daemon=True
        )
        thread.start()

        return task_id

    def execute_step(self, step_key: str, task_id: str, target_date: Optional[str]) -> None:
        """此编排器不使用标准步骤执行"""
        pass

    def _get_steps_for_type(self, task_type: str) -> List[Dict]:
        """根据任务类型获取步骤定义"""
        if task_type == 'sync_indices':
            return [{'key': 'sync_index', 'name': '同步指数', 'total_count': 1, 'completed_count': 0}]
        elif task_type == 'sync_daily':
            return [{'key': 'sync_stocks', 'name': '同步个股', 'total_count': 1, 'completed_count': 0}]
        elif task_type == 'calculate_rps':
            return [{'key': 'rps_stock', 'name': '计算个股RPS', 'total_count': 1, 'completed_count': 0}]
        elif task_type == 'sync_sectors':
            return [{'key': 'sync_sectors', 'name': '同步板块', 'total_count': 1, 'completed_count': 0}]
        elif task_type == 'calculate_sector_rps':
            return [{'key': 'rps_sector', 'name': '计算板块RPS', 'total_count': 1, 'completed_count': 0}]
        elif task_type == 'sync_index_pe':
            return [{'key': 'sync_pe', 'name': '更新PE', 'total_count': 1, 'completed_count': 0}]
        elif task_type == 'precompute_base':
            return [{'key': 'precompute', 'name': '预计算基础数据', 'total_count': 1, 'completed_count': 0}]
        else:
            return [{'key': 'unknown', 'name': '未知任务', 'total_count': 1, 'completed_count': 0}]

    def _run_task(self, task_id: str, task_type: str, kwargs: dict) -> None:
        """后台执行任务"""
        from app.data.task_manager import get_task_manager
        tm = get_task_manager()

        try:
            logger.info(f"[设置任务] 开始执行 {task_type}")

            if task_type == 'sync_indices':
                self._sync_indices(task_id, **kwargs)
            elif task_type == 'sync_daily':
                self._sync_daily(task_id, **kwargs)
            elif task_type == 'calculate_rps':
                self._calculate_rps(task_id, target='stock', **kwargs)
            elif task_type == 'sync_sectors':
                self._sync_sectors(task_id, **kwargs)
            elif task_type == 'calculate_sector_rps':
                self._calculate_rps(task_id, target='sector', **kwargs)
            elif task_type == 'sync_index_pe':
                self._sync_index_pe(task_id, **kwargs)
            elif task_type == 'precompute_base':
                self._precompute_base(task_id, **kwargs)
            else:
                self.task_repo.fail_task(task_id, f'未知任务类型: {task_type}')
                return

            self.task_repo.complete_task(task_id, f'{task_type} 完成')
            logger.info(f"[设置任务] {task_type} 完成")
        except Exception as e:
            logger.error(f"[设置任务] {task_type} 失败: {e}", exc_info=True)
            self.task_repo.fail_task(task_id, str(e)[:200])

    def _sync_indices(self, task_id: str, **kwargs) -> None:
        """同步指数数据"""
        from app.server.factories import get_index_factory

        self.task_repo.update_step_progress(task_id, 0, status='running', message='同步指数K线...')

        factory = get_index_factory()
        factory.sync_kline()

        self.task_repo.update_step_progress(task_id, 0, message='计算指数涨跌幅...')
        factory.compute_chg()

        self.task_repo.update_step_progress(task_id, 0, status='completed', message='指数同步完成')

    def _sync_daily(self, task_id: str, **kwargs) -> None:
        """同步个股日线数据"""
        from app.server.factories import get_stock_factory

        max_workers = kwargs.get('max_workers', 16)

        self.task_repo.update_step_progress(task_id, 0, status='running', message='同步个股日线...')

        factory = get_stock_factory()
        factory.sync_daily(task_id=task_id, max_workers=max_workers)

        self.task_repo.update_step_progress(task_id, 0, message='计算涨幅字段...')
        factory.compute_chg()

        self.task_repo.update_step_progress(task_id, 0, status='completed', message='个股同步完成')

    def _calculate_rps(self, task_id: str, target: str = 'stock', **kwargs) -> None:
        """计算RPS"""
        from app.server.factories import get_market_aggregator

        self.task_repo.update_step_progress(task_id, 0, status='running', message=f'计算{target}RPS...')

        aggregator = get_market_aggregator()
        result = aggregator.calculate_rps(target=target)

        self.task_repo.update_step_progress(task_id, 0, status='completed', message=f'{target}RPS计算完成')

    def _sync_sectors(self, task_id: str, **kwargs) -> None:
        """同步板块数据"""
        from app.server.factories import get_sector_factory

        self.task_repo.update_step_progress(task_id, 0, status='running', message='同步板块日线...')

        factory = get_sector_factory()
        factory.sync_daily(task_id=task_id)

        self.task_repo.update_step_progress(task_id, 0, message='计算板块衍生字段...')
        factory.compute_chg()

        self.task_repo.update_step_progress(task_id, 0, status='completed', message='板块同步完成')

    def _sync_index_pe(self, task_id: str, **kwargs) -> None:
        """同步指数PE数据"""
        from app.server.config import get_settings

        settings = get_settings()
        if not settings.LEGULEGU_TOKEN:
            self.task_repo.update_step_progress(task_id, 0, status='completed', message='未配置PE Token，跳过')
            return

        self.task_repo.update_step_progress(task_id, 0, status='running', message='同步PE数据...')

        from app.server.services.factors_service import _run_sync_pe
        _run_sync_pe(task_id, settings.LEGULEGU_TOKEN, is_external=True)

        self.task_repo.update_step_progress(task_id, 0, status='completed', completed_count=1, message='PE同步完成')

    def _precompute_base(self, task_id: str, **kwargs) -> None:
        """预计算基础数据"""
        from app.data.db import get_db

        self.task_repo.update_step_progress(task_id, 0, status='running', message='预计算基础数据...')

        from app.server.services.factors_service import _run_precompute_base_for_date
        db = get_db()

        # 获取最新交易日
        dates = sorted(db['stock_daily'].distinct('trade_date', {'close': {'$gt': 0}}), reverse=True)
        latest = dates[0] if dates else None

        if not latest:
            self.task_repo.fail_task(task_id, "无交易数据")
            return

        _run_precompute_base_for_date(task_id, latest, is_external=True)

        # 更新步骤进度（覆盖 _run_precompute_base_for_date 设置的 current_stock_name）
        self.task_repo.update_step_progress(task_id, 0, status='completed', completed_count=1, message='预计算完成')
        self.task_repo.update_task_progress(task_id, current_stock_name='预计算完成', completed_count=1)
