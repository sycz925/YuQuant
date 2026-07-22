"""
一键更新API - 统一任务接口
步骤：1.并行同步数据(指数/个股/板块) → 2.计算RPS(个股/板块) → 3.更新PE → 4.同步基础数据
"""
import logging
import threading
import time
from datetime import datetime
from fastapi import APIRouter, Query
from app.data.db import get_db
from app.server.cache import refresh_trade_dates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/one-click-update", tags=["一键更新"])

# 全局任务状态
_task_status = {
    'running': False,
    'current_step': 0,
    'total_steps': 4,
    'step_name': '',
    'step_progress': '',
    'error': None
}
_lock = threading.Lock()


def _update_status(step, name, progress='', error=None):
    with _lock:
        _task_status['current_step'] = step
        _task_status['step_name'] = name
        _task_status['step_progress'] = progress
        if error:
            _task_status['error'] = error


def _get_task_progress(tm, task_id):
    """从task_manager获取任务进度"""
    try:
        task = tm.get_task_dict(task_id)
        if task:
            total = task.get('total_count', 0)
            completed = task.get('completed_count', 0) + task.get('skipped_count', 0)
            failed = task.get('failed_count', 0)
            current_name = task.get('current_stock_name', '')
            status = task.get('status', '')
            return {
                'total': total,
                'completed': completed,
                'failed': failed,
                'current_name': current_name,
                'status': status
            }
    except Exception:
        pass
    return None


def _run_update_task(task_id: str):
    """后台执行一键更新任务（严格按顺序执行，同步调用，任一步骤失败则停止）"""
    try:
        from app.data.task_manager import get_task_manager
        from app.data.db import get_db
        from app.data.manager import get_data_manager

        tm = get_task_manager()
        db = get_db()
        dm = get_data_manager()

        today = datetime.now().strftime('%Y%m%d')
        
        # 获取步骤信息
        task_doc = db['sync_tasks'].find_one({'task_id': task_id}, {'_id': 0, 'steps': 1})
        steps_list = task_doc.get('steps', []) if task_doc else []
        step_keys = [s.get('key', '') for s in steps_list]

        # ====== 步骤1：同步指数（同步调用） ======
        step_idx = step_keys.index('sync_index') if 'sync_index' in step_keys else 0
        tm.start_step(task_id, step_idx)
        try:
            from app.server.services.factor_service import get_factor_service
            fs = get_factor_service()
            # 同步执行：直接调用 _run_sync_indices 而不是启动线程
            index_cfg = fs._get_sync_index_config()
            enabled_codes = set(
                doc['code'] for doc in db['index_basics'].find(
                    {'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1}
                )
            )
            sync_cfg = [c for c in index_cfg if c.get('code') in enabled_codes]
            fs._run_sync_indices(task_id, sync_cfg, None, None, is_external=True)
            tm.complete_step(task_id, step_idx, f'{today} 指数同步完成')
        except Exception as e:
            logger.warning(f"同步指数失败: {e}")
            tm.fail_step(task_id, step_idx, str(e)[:200])
            tm.fail_task(task_id, f"步骤失败: {str(e)[:200]}")
            return

        # ====== 步骤2：同步个股（同步调用） ======
        step_idx = step_keys.index('sync_stocks') if 'sync_stocks' in step_keys else 1
        tm.start_step(task_id, step_idx)
        try:
            import threading as _thr
            _step2_done = _thr.Event()
            def _sync_step2_progress():
                while not _step2_done.is_set():
                    try:
                        t = db['sync_tasks'].find_one({'task_id': task_id}, {'_id': 0, 'completed_count': 1, 'total_count': 1, 'current_stock_name': 1})
                        if t:
                            tm._get_col().update_one(
                                {'task_id': task_id},
                                {'$set': {f'steps.{step_idx}.completed_count': t.get('completed_count', 0),
                                          f'steps.{step_idx}.total_count': t.get('total_count', 0),
                                          f'steps.{step_idx}.message': t.get('current_stock_name', '')}}
                            )
                    except Exception:
                        pass
                    _step2_done.wait(timeout=3)
            _monitor = _thr.Thread(target=_sync_step2_progress, daemon=True)
            _monitor.start()
            try:
                from app.server.api.sync import _run_sync_task
                _run_sync_task(task_id, None, 4, is_external=True)
            finally:
                _step2_done.set()
                _monitor.join(timeout=5)
            tm.complete_step(task_id, step_idx, f'{today} 个股同步完成')
        except Exception as e:
            logger.warning(f"同步个股失败: {e}")
            tm.fail_step(task_id, step_idx, str(e)[:200])
            tm.fail_task(task_id, f"步骤失败: {str(e)[:200]}")
            return

        # ====== 步骤3：同步板块（同步调用） ======
        step_idx = step_keys.index('sync_sectors') if 'sync_sectors' in step_keys else 2
        tm.start_step(task_id, step_idx)
        try:
            # 同步执行：直接调用板块同步的底层函数
            sector_db = get_db()
            enabled_sectors = set(
                doc['code'] for doc in sector_db['sector_basics'].find(
                    {'is_disable': {'$ne': True}}, {'_id': 0, 'code': 1}
                )
            )
            from app.data.manager import get_data_manager as _dm
            _dm_inst = _dm()
            # 直接调用同步函数，不通过fs（fs会启动线程）
            result = _dm_inst.sync_sector_indices(
                task_id=task_id,
                enabled_codes=enabled_sectors,
                is_external=True,
            )
            logger.info(f"板块同步完成: {result}")
            # 计算冗余字段
            _dm_inst.calculate_all_derived_fields(target='sector')
            tm.complete_step(task_id, step_idx, f'{today} 板块同步完成')
        except Exception as e:
            logger.warning(f"同步板块失败: {e}")
            tm.fail_step(task_id, step_idx, str(e)[:200])
            tm.fail_task(task_id, f"步骤失败: {str(e)[:200]}")
            return

        # ====== 步骤4：计算个股RPS（同步调用） ======
        step_idx = step_keys.index('rps_stock') if 'rps_stock' in step_keys else 3
        tm.start_step(task_id, step_idx)
        try:
            from app.engine.factor_engine import FactorEngine
            engine = FactorEngine()
            result = engine.calculate_rps(data_type='stock', max_dates=None)
            logger.info(f"个股RPS计算完成: {result}")
            # 计算涨幅字段
            dm.calculate_chg_fields(target='stock')
            tm.complete_step(task_id, step_idx, f'{today} 个股RPS计算完成')
        except Exception as e:
            logger.warning(f"计算个股RPS失败: {e}")
            tm.fail_step(task_id, step_idx, str(e)[:200])
            tm.fail_task(task_id, f"步骤失败: {str(e)[:200]}")
            return

        # ====== 步骤5：计算板块RPS（同步调用） ======
        step_idx = step_keys.index('rps_sector') if 'rps_sector' in step_keys else 4
        tm.start_step(task_id, step_idx)
        try:
            result = engine.calculate_rps(data_type='sector', max_dates=None)
            logger.info(f"板块RPS计算完成: {result}")
            dm.calculate_chg_fields(target='sector')
            tm.complete_step(task_id, step_idx, f'{today} 板块RPS计算完成')
        except Exception as e:
            logger.warning(f"计算板块RPS失败: {e}")
            tm.fail_step(task_id, step_idx, str(e)[:200])
            tm.fail_task(task_id, f"步骤失败: {str(e)[:200]}")
            return

        # ====== 步骤6：更新PE（同步调用） ======
        step_idx = step_keys.index('sync_pe') if 'sync_pe' in step_keys else 5
        tm.start_step(task_id, step_idx)
        try:
            import os
            token = os.getenv('LEGULEGU_TOKEN', '')
            if token:
                # 同步执行：直接调用PE同步逻辑
                from app.server.api.factors import _run_sync_pe
                _run_sync_pe(task_id, token, is_external=True)
                tm.complete_step(task_id, step_idx, f'{today} PE同步完成')
            else:
                tm.complete_step(task_id, step_idx, f'{today} 未配置PE Token，跳过')
        except Exception as e:
            logger.warning(f"同步PE失败: {e}")
            tm.fail_step(task_id, step_idx, str(e)[:200])
            tm.fail_task(task_id, f"步骤失败: {str(e)[:200]}")
            return

        # ====== 步骤7：预计算基础数据（同步调用） ======
        step_idx = step_keys.index('precompute') if 'precompute' in step_keys else 6
        tm.start_step(task_id, step_idx)
        try:
            # 同步执行：直接调用预计算逻辑
            from app.server.api.factors import _run_precompute_base_for_date
            _run_precompute_base_for_date(task_id, today, is_external=True)
            tm.complete_step(task_id, step_idx, f'{today} 基础数据预计算完成')
        except Exception as e:
            logger.warning(f"预计算基础数据失败: {e}")
            tm.fail_step(task_id, step_idx, str(e)[:200])
            tm.fail_task(task_id, f"步骤失败: {str(e)[:200]}")
            return

        # 所有步骤完成
        tm.complete_task(task_id, f"一键更新完成: {today}")
        logger.info(f"[一键更新] 全部完成")

    except Exception as e:
        logger.error(f"一键更新失败: {e}")
        try:
            tm.fail_task(task_id, str(e)[:200])
        except Exception:
            pass


@router.post("/start")
def start_update():
    """启动一键更新任务"""
    from app.data.task_manager import get_task_manager
    from app.data.db import get_db
    
    # 检查同步时间窗口
    from app.server.api.sync import _check_sync_time
    allowed, msg = _check_sync_time()
    if not allowed:
        return {
            'success': False,
            'message': msg,
            'already_running': False,
        }

    tm = get_task_manager()
    db = get_db()
    
    # 检查是否有正在运行的任务
    running_task = db['sync_tasks'].find_one(
        {'status': 'running'},
        sort=[('created_at', -1)]
    )
    
    if running_task:
        return {
            'success': True,
            'message': '更新任务正在进行中',
            'already_running': True,
            'task_id': running_task['task_id'],
        }
    
    today = datetime.now().strftime('%Y%m%d')
    
    # 查询各类型数据的数量
    index_count = db['index_basics'].count_documents({'is_disable': {'$ne': True}})
    stock_count = db['stock_basics'].count_documents({'is_disable': {'$ne': True}})
    sector_count = db['sector_basics'].count_documents({'is_disable': {'$ne': True}})
    
    # 定义步骤
    steps = [
        {'name': '同步指数', 'key': 'sync_index', 'current_date': today, 'status': 'pending', 'total_count': index_count, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        {'name': '同步个股', 'key': 'sync_stocks', 'current_date': today, 'status': 'pending', 'total_count': stock_count, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        {'name': '同步板块', 'key': 'sync_sectors', 'current_date': today, 'status': 'pending', 'total_count': sector_count, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        {'name': '计算个股RPS', 'key': 'rps_stock', 'current_date': today, 'status': 'pending', 'total_count': 1, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        {'name': '计算板块RPS', 'key': 'rps_sector', 'current_date': today, 'status': 'pending', 'total_count': 1, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        {'name': '更新PE', 'key': 'sync_pe', 'current_date': today, 'status': 'pending', 'total_count': 1, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        {'name': '预计算基础数据', 'key': 'precompute', 'current_date': today, 'status': 'pending', 'total_count': 1, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
    ]
    
    # 创建带步骤的任务
    task_id = tm.create_task_with_steps(steps)
    
    thread = threading.Thread(target=_run_update_task, args=(task_id,), daemon=True)
    thread.start()
    
    return {'success': True, 'message': '一键更新已启动', 'task_id': task_id}


@router.get("/status")
def get_status():
    """获取更新任务状态"""
    with _lock:
        return dict(_task_status)


@router.get("/sync-time-check")
def check_sync_time():
    """检查当前是否在允许同步的时间窗口内"""
    from app.server.api.sync import _check_sync_time
    allowed, msg = _check_sync_time()
    return {'allowed': allowed, 'message': msg}


# ==================== 按日期重算 ====================

# 按日期重算的全局任务状态
_recalc_task_status = {
    'running': False,
    'current_step': 0,
    'total_steps': 3,
    'step_name': '',
    'step_progress': '',
    'error': None,
    'target_date': None
}
_recalc_lock = threading.Lock()


def _recalc_update_status(step, name, progress='', error=None):
    with _recalc_lock:
        _recalc_task_status['current_step'] = step
        _recalc_task_status['step_name'] = name
        _recalc_task_status['step_progress'] = progress
        if error:
            _recalc_task_status['error'] = error


def _run_recalc_task(task_id: str, target_date: str):
    """后台执行按日期重算任务"""
    try:
        from app.data.task_manager import get_task_manager
        from app.data.db import get_db
        tm = get_task_manager()
        db = get_db()
        
        def get_task_progress_text(tid):
            if not tid:
                return None
            try:
                task = tm.get_task_dict(tid)
                if task:
                    total = task.get('total_count', 0)
                    completed = task.get('completed_count', 0) + task.get('skipped_count', 0)
                    status = task.get('status', '')
                    if status == 'completed':
                        return '已完成'
                    elif status == 'failed':
                        return '失败'
                    elif total > 0:
                        return f'{completed}/{total}'
                    else:
                        return '准备中'
            except Exception:
                pass
            return None
        
        # ====== 第一步：计算个股RPS ======
        rps_stock_step_idx = 0
        tm.start_step(task_id, rps_stock_step_idx)
        try:
            from app.server.services.factor_service import get_factor_service
            fs = get_factor_service()
            fs.calculate_rps(
                start_date=None, end_date=None, target_date=target_date,
                target='stock', max_workers=4, min_days=200,
                external_task_id=task_id
            )
            tm.complete_step(task_id, rps_stock_step_idx, f'{target_date} 个股RPS 计算完成')
        except Exception as e:
            logger.warning(f"计算个股RPS失败: {e}")
            tm.fail_step(task_id, rps_stock_step_idx, str(e)[:200])
            return

        # ====== 第二步：计算板块RPS ======
        rps_sector_step_idx = 1
        tm.start_step(task_id, rps_sector_step_idx)
        try:
            fs.calculate_rps(
                start_date=None, end_date=None, target_date=target_date,
                target='sector', max_workers=4, min_days=20,
                external_task_id=task_id
            )
            # 完成板块RPS步骤
            tm.complete_step(task_id, rps_sector_step_idx, f'{target_date} 板块RPS计算完成')
        except Exception as e:
            logger.warning(f"计算板块RPS失败: {e}")
            tm.fail_step(task_id, rps_sector_step_idx, str(e)[:200])
            return

        # ====== 第三步：预计算基础数据（base_data_daily + market_daily）======
        precompute_step_idx = 2
        tm.start_step(task_id, precompute_step_idx)
        try:
            from app.server.api.factors import _run_precompute_base_for_date
            precompute_task_id = tm.create_task()
            _run_precompute_base_for_date(precompute_task_id, target_date)
            tm.complete_step(task_id, precompute_step_idx, f'{target_date} 预计算完成')
        except Exception as e:
            logger.warning(f"预计算基础数据失败: {e}")
            tm.fail_step(task_id, precompute_step_idx, str(e)[:200])
            return

        # 刷新缓存
        refresh_trade_dates()

        tm.complete_task(task_id, f"{target_date} 数据重算完成")
        logger.info(f"[数据重算] {target_date} 全部完成")

    except Exception as e:
        logger.error(f"数据重算失败: {e}")
        tm.fail_task(task_id, str(e)[:200])


@router.post("/recalculate-date")
def recalculate_date(target_date: str = Query(..., description="目标日期 YYYYMMDD")):
    """启动按日期重算任务"""
    from app.data.task_manager import get_task_manager
    from app.data.db import get_db
    
    tm = get_task_manager()
    db = get_db()
    
    # 检查是否有正在运行的任务
    running_task = db['sync_tasks'].find_one(
        {'status': 'running'},
        sort=[('created_at', -1)]
    )
    
    if running_task:
        return {
            'success': True,
            'message': '重算任务正在进行中',
            'already_running': True,
            'task_id': running_task['task_id'],
        }
    
    # 查询个股和板块数量
    stock_count = db['stock_basics'].count_documents({'is_disable': {'$ne': True}})
    sector_count = db['sector_basics'].count_documents({'is_disable': {'$ne': True}})
    
    # 定义步骤：3个步骤
    steps = [
        {'name': '计算个股RPS', 'key': 'rps_stock', 'current_date': target_date, 'status': 'pending', 'total_count': stock_count, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        {'name': '计算板块RPS', 'key': 'rps_sector', 'current_date': target_date, 'status': 'pending', 'total_count': sector_count, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
        {'name': '预计算基础数据', 'key': 'precompute', 'current_date': target_date, 'status': 'pending', 'total_count': 1, 'completed_count': 0, 'failed_count': 0, 'skipped_count': 0},
    ]
    
    # 创建带步骤的任务
    task_id = tm.create_task_with_steps(steps)
    
    thread = threading.Thread(target=_run_recalc_task, args=(task_id, target_date), daemon=True)
    thread.start()

    return {'success': True, 'message': f'{target_date} 数据重算已启动', 'already_running': False, 'task_id': task_id}


