"""
Sector Factory - 板块工厂
管理板块数据的同步与衍生计算
"""
import io
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from app.server.factories.base import SyncResult, ComputeResult, PipelineResult, ProgressCallback
from app.server.repositories.sector_repository import SectorRepository

logger = logging.getLogger(__name__)


class SectorFactory:
    """板块工厂 — 管理板块数据的同步与衍生计算"""
    
    def __init__(self, sector_repo: SectorRepository = None):
        self.repo = sector_repo or SectorRepository()
    
    def get_sector_list(self, page: Optional[int] = None, page_size: int = 50,
                        keyword: Optional[str] = None, filter_mode: Optional[str] = None,
                        limit: Optional[int] = None, min_stock_count: int = 0,
                        sort_by: Optional[str] = None, sort_order: str = 'desc',
                        rps_red: Optional[str] = None) -> Dict[str, Any]:
        """获取板块列表（含最新行情数据）"""
        from app.data.db import get_db
        
        db = get_db()
        query = {}
        
        if min_stock_count:
            query['stock_count'] = {'$gte': min_stock_count}
        
        if filter_mode == 'enabled':
            query['is_disable'] = False
        elif filter_mode == 'disabled':
            query['is_disable'] = True
        
        cursor = db['sector_basics'].find(
            query,
            {'_id': 0, 'code': 1, 'name': 1, 'source': 1, 'stock_count': 1, 'is_disable': 1}
        )
        items = list(cursor)
        
        # 获取最新行情数据（含 RPS / 涨跌幅 / 区间涨幅）
        sector_coll = db['sector_daily']
        latest_doc = sector_coll.find_one({}, sort=[('trade_date', -1)], projection={'trade_date': 1, '_id': 0})
        if latest_doc:
            latest_date = latest_doc['trade_date']
            daily_cursor = sector_coll.find(
                {'trade_date': latest_date},
                {'_id': 0, 'stock_code': 1, 'close': 1, 'chg_pct': 1,
                 'chg_5d': 1, 'chg_10d': 1, 'chg_20d': 1, 'chg_50d': 1, 'chg_120d': 1,
                 'rps_10': 1, 'rps_50': 1, 'rps_120': 1},
            )
            daily_map = {d['stock_code']: d for d in daily_cursor}
            for item in items:
                daily = daily_map.get(item['code'], {})
                item['close'] = daily.get('close')
                item['change_pct'] = daily.get('chg_pct')
                item['chg_5d'] = daily.get('chg_5d')
                item['chg_10d'] = daily.get('chg_10d')
                item['chg_20d'] = daily.get('chg_20d')
                item['chg_50d'] = daily.get('chg_50d')
                item['chg_120d'] = daily.get('chg_120d')
                item['rps_10'] = daily.get('rps_10')
                item['rps_50'] = daily.get('rps_50')
                item['rps_120'] = daily.get('rps_120')
                item['exclude_sync'] = item.get('is_disable', False)
        
        # 关键词搜索
        if keyword:
            from pypinyin import lazy_pinyin, Style
            kw = keyword.lower()
            
            def get_pinyin(name: str) -> str:
                try:
                    return ''.join(lazy_pinyin(name, style=Style.FIRST_LETTER)).lower()
                except Exception:
                    return ''
            
            items = [i for i in items if
                     kw in i.get('code', '').lower() or
                     kw in i.get('name', '').lower() or
                     kw in get_pinyin(i.get('name', ''))]
        
        # 排序
        if sort_by and sort_by in ('code', 'name', 'close', 'change_pct',
                                   'chg_5d', 'chg_10d', 'chg_20d', 'chg_50d', 'chg_120d',
                                    'rps_10', 'rps_50', 'rps_120'):
            reverse = sort_order == 'desc'
            items.sort(key=lambda i: (i.get(sort_by) if i.get(sort_by) is not None else (float('-inf') if reverse else float('inf'))), reverse=reverse)

        # RPS红筛选
        if rps_red in ('one', 'two', 'three'):
            rps_threshold = 87
            filtered = []
            for item in items:
                rps_values = [v for v in (item.get('rps_10'), item.get('rps_50'), item.get('rps_120')) if v is not None]
                red_count = sum(1 for v in rps_values if v > rps_threshold)
                if rps_red == 'one' and red_count >= 1:
                    filtered.append(item)
                elif rps_red == 'two' and red_count >= 2:
                    filtered.append(item)
                elif rps_red == 'three' and red_count >= 3:
                    filtered.append(item)
            items = filtered
        
        total = len(items)
        if limit and page is None:
            items = items[:limit]
        elif page is not None:
            start = (page - 1) * page_size
            items = items[start:start + page_size]
        
        return {"success": True, "total": total, "items": items}
    
    def import_sector_codes(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """导入板块代码"""
        import pandas as pd
        from app.data.db import get_db
        
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(file_content))
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(file_content))
        else:
            return {"success": False, "message": "请上传 Excel (.xlsx/.xls) 或 CSV 文件"}
        
        cols = [str(c).strip() for c in df.columns]
        code_col = name_col = None
        for c in cols:
            cl = c.lower()
            if cl in ('code', '代码', '板块代码', 'tdx_code', '数字代码'):
                code_col = c
            elif cl in ('name', '名称', '板块名称', '板块名'):
                name_col = c
        
        if not code_col or not name_col:
            if len(cols) >= 2:
                code_col, name_col = cols[0], cols[1]
            else:
                return {"success": False, "message": "无法识别代码和名称列"}
        
        mapping = {}
        skipped = 0
        for _, row in df.iterrows():
            code = str(row[code_col]).strip()
            name = str(row[name_col]).strip()
            if code and name and code != 'nan' and name != 'nan':
                if code.startswith('880') or code.startswith('881'):
                    mapping[name] = code
                else:
                    skipped += 1
        
        if not mapping:
            return {"success": False, "message": "文件中没有有效的880/881板块代码"}
        
        db = get_db()
        updated = added = migrated = 0
        for name, code in mapping.items():
            existing = db['sector_basics'].find_one({'$or': [{'code': code}, {'name': name}]})
            if existing:
                if existing.get('code') != code:
                    old_code = existing['code']
                    db['sector_basics'].update_one({'_id': existing['_id']}, {'$set': {'code': code, 'tdx_code': code}})
                    result = db['sector_daily'].update_many({'stock_code': old_code}, {'$set': {'stock_code': code}})
                    migrated += result.modified_count
                    updated += 1
            else:
                db['sector_basics'].insert_one({
                    'code': code, 'tdx_code': code, 'name': name,
                    'source': '导入', 'stock_count': 0, 'stock_codes': [],
                    'block_type': 2, 'update_time': datetime.utcnow(),
                })
                added += 1
        
        return {
            "success": True,
            "message": f"导入完成: 新增 {added} 个板块, 更新 {updated} 个, 迁移 {migrated} 条日线数据",
            "added": added, "updated": updated,
            "migrated": migrated, "total_mapping": len(mapping),
        }
    
    def sync_daily(self, target_date: Optional[str] = None,
                   task_id: str = None,
                   progress_callback: Callable = None) -> SyncResult:
        """
        同步板块日线数据
        :param target_date: 指定日期 YYYYMMDD，None 同步到最新
        :param task_id: 任务ID，用于更新进度
        :return: SyncResult，失败率超过5%则标记失败
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            enabled_sectors = self.repo.get_enabled_codes()
            total = len(enabled_sectors)
            
            if total == 0:
                return SyncResult(success=True, message='无启用板块', total=0)
            
            callback.update(0, total, '开始同步板块日线...')
            
            # 调用 data_manager 的板块同步逻辑
            from app.data.manager import get_data_manager
            dm = get_data_manager()
            
            result = dm.sync_sector_indices(
                task_id=task_id,
                enabled_codes=enabled_sectors,
                is_external=True
            )
            
            # 计算冗余字段
            dm.calculate_all_derived_fields(target='sector')
            
            # 检查失败率
            success_count = result.get('block_count', 0)
            fail_count = total - success_count
            if total > 0:
                fail_rate = fail_count / total
                if fail_rate > 0.05:
                    callback.complete(f'板块日线同步失败: 失败率 {fail_rate:.1%} 超过阈值')
                    return SyncResult(
                        success=False,
                        message=f'失败率 {fail_rate:.1%} 超过5%阈值',
                        total=total,
                        synced=success_count,
                        failed=fail_count
                    )
            
            callback.complete(f'板块日线同步完成: {total} 个')
            return SyncResult(
                success=True,
                message=f'板块日线同步完成: {total} 个',
                total=total,
                synced=total
            )
        except Exception as e:
            logger.error(f'同步板块日线失败: {e}')
            return SyncResult(success=False, message=str(e))
    
    def compute_rps(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """
        计算板块 RPS
        :param target_date: 指定日期重算，None 从最新日期回溯
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算板块RPS...')
            
            # 调用 factor_engine 的 RPS 计算
            from app.engine.factor_engine import FactorEngine
            engine = FactorEngine()
            result = engine.calculate_rps(data_type='sector', max_dates=None, target_date=target_date)
            
            callback.complete(f'板块RPS计算完成: {result}')
            return ComputeResult(success=True, message=f'板块RPS计算完成: {result}')
        except Exception as e:
            logger.error(f'计算板块RPS失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def compute_chg(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """计算板块区间涨幅"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算板块涨幅...')
            
            # 调用 data_manager 的涨幅计算
            from app.data.manager import get_data_manager
            dm = get_data_manager()
            dm.calculate_chg_fields(target='sector', trade_date=target_date)
            
            callback.complete('板块涨幅计算完成')
            return ComputeResult(success=True, message='板块涨幅计算完成')
        except Exception as e:
            logger.error(f'计算板块涨幅失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def compute_ma(self, target_date: Optional[str] = None,
                   progress_callback: Callable = None) -> ComputeResult:
        """计算板块均线"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算板块均线...')
            
            # 调用 data_manager 的均线计算
            from app.data.manager import get_data_manager
            dm = get_data_manager()
            dm.calculate_all_derived_fields(target='sector', trade_date=target_date)
            
            callback.complete('板块均线计算完成')
            return ComputeResult(success=True, message='板块均线计算完成')
        except Exception as e:
            logger.error(f'计算板块均线失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def run_full_pipeline(self, target_date: Optional[str] = None,
                          progress_callback: Callable = None) -> PipelineResult:
        """
        执行板块全流程：sync_daily → compute_chg → compute_ma → compute_rps
        """
        result = PipelineResult()
        
        result.add_step('sync_daily', self.sync_daily(target_date, progress_callback))
        result.add_step('compute_chg', self.compute_chg(target_date, progress_callback))
        result.add_step('compute_ma', self.compute_ma(target_date, progress_callback))
        result.add_step('compute_rps', self.compute_rps(target_date, progress_callback))
        
        return result
