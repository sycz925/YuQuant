"""
Index Factory - 指数工厂
管理指数数据的同步与衍生计算
"""
import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional

from app.server.factories.base import SyncResult, ComputeResult, PipelineResult, ProgressCallback
from app.server.repositories.index_repository import IndexRepository

logger = logging.getLogger(__name__)


class IndexFactory:
    """指数工厂 — 管理指数数据的同步与衍生计算"""
    
    def __init__(self, index_repo: IndexRepository = None):
        self.repo = index_repo or IndexRepository()
        self._config_cache = {}  # 配置缓存
    
    def get_config_from_db(self) -> List[Dict[str, Any]]:
        """从数据库获取指数配置"""
        cache_key = 'index_config'
        if cache_key in self._config_cache:
            return self._config_cache[cache_key]
        
        from app.data.db import get_db
        from app.server.api.constants import INDEX_CONFIG_SEED
        
        db = get_db()
        cursor = db['index_basics'].find({}, {'_id': 0}).sort('code', 1)
        results = list(cursor)
        
        if results:
            self._config_cache[cache_key] = results
            return results
        
        # 回退：用种子数据初始化
        for cfg in INDEX_CONFIG_SEED:
            db['index_basics'].update_one(
                {'code': cfg['code']},
                {'$set': cfg},
                upsert=True
            )
        
        fallback = [dict(c) for c in INDEX_CONFIG_SEED]
        self._config_cache[cache_key] = fallback
        return fallback
    
    def get_sync_config(self) -> List[Dict[str, Any]]:
        """获取同步配置"""
        cfgs = self.get_config_from_db()
        return [
            {
                'code': c.get('code', ''),
                'name': c.get('name', ''),
                'tdx_code': c.get('tdx_code', c.get('code', '')),
                'market': c.get('market', 1),
            }
            for c in cfgs
        ]
    
    def get_index_data(self, index_code: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """获取指数历史数据"""
        from app.data.db import get_db
        
        db = get_db()
        pipeline = [
            {'$match': {
                'stock_code': index_code,
                'trade_date': {'$gte': start_date, '$lte': end_date}
            }},
            {'$sort': {'trade_date': 1}},
            {'$project': {
                '_id': 0, 'trade_date': 1, 'close': 1,
                'open': 1, 'high': 1, 'low': 1
            }}
        ]
        return list(db.index_daily.aggregate(pipeline))
    
    def normalize_index_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """标准化指数数据"""
        if not data:
            return []
        base_value = data[0]['close']
        return [
            {
                'trade_date': item['trade_date'],
                'value': ((item['close'] / base_value) - 1) * 100 + 50,
                'close': item['close']
            }
            for item in data
        ]
    
    def aggregate_by_period(self, daily_data: List[Dict[str, Any]], period: str) -> List[Dict[str, Any]]:
        """按周期聚合数据"""
        from datetime import date, timedelta
        import calendar
        
        if period == "day":
            return daily_data
        
        bucket_map = {}
        for item in daily_data:
            d = item['trade_date']
            y, m, day = int(d[0:4]), int(d[4:6]), int(d[6:8])
            
            if period == "week":
                iso_year, iso_week, _ = date(y, m, day).isocalendar()
                key = f"{iso_year}W{iso_week:02d}"
                week_end = date(y, m, day) + timedelta(days=(6 - date(y, m, day).weekday()))
                sort_key = week_end.strftime("%Y%m%d")
            elif period == "month":
                key = f"{y}-{m:02d}"
                last_day = calendar.monthrange(y, m)[1]
                sort_key = f"{y}{m:02d}{last_day:02d}"
            elif period == "quarter":
                q = (m - 1) // 3 + 1
                key = f"{y}Q{q}"
                quarter_end_month = q * 3
                last_day = calendar.monthrange(y, quarter_end_month)[1]
                sort_key = f"{y}{quarter_end_month:02d}{last_day:02d}"
            else:
                key = f"{y}"
                sort_key = f"{y}1231"
            
            if key not in bucket_map or d > bucket_map[key]['original_date']:
                bucket_map[key] = {
                    'trade_date': key, 'value': item['value'],
                    'original_date': d, 'sort_key': sort_key
                }
        
        result = sorted(bucket_map.values(), key=lambda x: x['sort_key'])
        for item in result:
            del item['sort_key']
            del item['original_date']
        
        return result
    
    def aggregate_index_by_period(self, normalized: List[Dict[str, Any]], period: str) -> List[Dict[str, Any]]:
        """按周期聚合指数数据"""
        from datetime import date, timedelta
        import calendar
        
        if period == "day":
            return normalized
        
        bucket_map = {}
        for item in normalized:
            d = item['trade_date']
            y, m, day = int(d[0:4]), int(d[4:6]), int(d[6:8])
            
            if period == "week":
                iso_year, iso_week, _ = date(y, m, day).isocalendar()
                key = f"{iso_year}W{iso_week:02d}"
                week_end = date(y, m, day) + timedelta(days=(6 - date(y, m, day).weekday()))
                sort_key = week_end.strftime("%Y%m%d")
            elif period == "month":
                key = f"{y}-{m:02d}"
                last_day = calendar.monthrange(y, m)[1]
                sort_key = f"{y}{m:02d}{last_day:02d}"
            elif period == "quarter":
                q = (m - 1) // 3 + 1
                key = f"{y}Q{q}"
                quarter_end_month = q * 3
                last_day = calendar.monthrange(y, quarter_end_month)[1]
                sort_key = f"{y}{quarter_end_month:02d}{last_day:02d}"
            else:
                key = f"{y}"
                sort_key = f"{y}1231"
            
            if key not in bucket_map or d > bucket_map[key]['original_date']:
                bucket_map[key] = {
                    'trade_date': key, 'value': item['value'],
                    'close': item.get('close'),
                    'original_date': d, 'sort_key': sort_key
                }
        
        result = sorted(bucket_map.values(), key=lambda x: x['sort_key'])
        for item in result:
            del item['sort_key']
            del item['original_date']
        
        return result
    
    def get_cr5_data(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                     include_index: bool = True, period: str = 'day') -> Optional[Dict[str, Any]]:
        """获取 CR5 数据"""
        from datetime import timedelta
        from app.data.db import get_db
        
        now = datetime.now()
        if not start_date or not end_date:
            period_days = {"day": 120, "week": 365, "month": 365 * 3,
                           "quarter": 365 * 5, "year": 365 * 10}
            default_start = now - timedelta(days=period_days.get(period, 120))
            if not start_date:
                start_date = default_start.strftime("%Y%m%d")
            if not end_date:
                end_date = now.strftime("%Y%m%d")
        
        # 优先从 base_data_daily 读取
        db = get_db()
        cached = list(db['base_data_daily'].find(
            {'date': {'$gte': start_date, '$lte': end_date}, 'cr5_pct': {'$exists': True}},
            {'_id': 0, 'date': 1, 'cr5_pct': 1, 'cr10_pct': 1}
        ).sort('date', 1))
        
        if cached:
            daily_data = [{'trade_date': d['date'], 'value': d['cr5_pct']} for d in cached]
            sector_daily_data = [{'trade_date': d['date'], 'value': d.get('cr10_pct', 0)} for d in cached]
        else:
            # 从 factor_engine 计算
            from app.engine.factor_engine import FactorEngine
            fe = FactorEngine()
            cr5_series = fe.get_all_cr5_history(start_date, end_date)
            sector_cr_series = fe.get_sector_cr_history(start_date, end_date, percentile=10)
            
            if len(cr5_series) == 0 and len(sector_cr_series) == 0:
                return None
            
            daily_data = [
                {'trade_date': str(idx), 'value': float(value)}
                for idx, value in cr5_series.items()
                if start_date <= str(idx) <= end_date
            ]
            sector_daily_data = [
                {'trade_date': str(idx), 'value': float(value)}
                for idx, value in sector_cr_series.items()
                if start_date <= str(idx) <= end_date
            ]
        
        data = self.aggregate_by_period(daily_data, period)
        sector_data = self.aggregate_by_period(sector_daily_data, period)
        extra_data = {}
        
        db_index_list = self.get_config_from_db()
        
        if include_index and daily_data:
            dates = [d['trade_date'] for d in daily_data]
            date_start, date_end = min(dates), max(dates)
            for config in db_index_list:
                index_code = config['code']
                index_raw = self.get_index_data(index_code, date_start, date_end)
                if index_raw:
                    normalized = self.normalize_index_data(index_raw)
                    extra_data[index_code] = self.aggregate_index_by_period(normalized, period)
        
        data.sort(key=lambda x: x['trade_date'])
        sector_data.sort(key=lambda x: x['trade_date'])
        for idx in extra_data:
            extra_data[idx].sort(key=lambda x: x['trade_date'])
        
        total_stocks = 0
        if data:
            latest_date = data[-1]['trade_date']
            db = get_db()
            stock_count_result = list(db['stock_daily'].aggregate([
                {'$match': {'trade_date': latest_date, 'amount': {'$exists': True, '$gt': 0}}},
                {'$count': 'count'}
            ]))
            total_stocks = stock_count_result[0]['count'] if stock_count_result else 0
        
        return {
            'total': len(data),
            'period': period,
            'data': data,
            'sector_cr_data': sector_data,
            'index_data': extra_data,
            'index_config': [{'code': c['code'], 'name': c['name']} for c in db_index_list],
            'total_stocks': total_stocks,
        }
    
    def get_indices_list(self, page: Optional[int] = None, page_size: int = 50,
                         keyword: Optional[str] = None, filter_mode: Optional[str] = None) -> Dict[str, Any]:
        """获取指数列表"""
        from app.data.db import get_db
        
        db = get_db()
        query = {}
        
        if keyword:
            query['$or'] = [
                {'code': {'$regex': keyword, '$options': 'i'}},
                {'name': {'$regex': keyword, '$options': 'i'}}
            ]
        
        if filter_mode == 'enabled':
            query['is_disable'] = False
        elif filter_mode == 'disabled':
            query['is_disable'] = True
        
        total = db['index_basics'].count_documents(query)
        cursor = db['index_basics'].find(query, {'_id': 0}).sort('code', 1)
        
        if page is not None:
            skip = (page - 1) * page_size
            cursor = cursor.skip(skip).limit(page_size)
        
        data = list(cursor)
        
        return {
            'total': total,
            'data': data,
            'page': page,
            'page_size': page_size
        }
    
    def search_indices(self, keyword: str) -> Dict[str, Any]:
        """搜索指数"""
        return self.get_indices_list(keyword=keyword)
    
    def sync_kline(self, target_date: Optional[str] = None,
                   task_id: str = None,
                   progress_callback: Callable = None) -> SyncResult:
        """
        同步指数 K 线数据（TDX 数据源）
        :param target_date: 指定日期 YYYYMMDD，None 同步到最新
        :param task_id: 任务ID，用于更新进度
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            enabled_indices = self.repo.get_enabled_list()
            total = len(enabled_indices)
            
            if total == 0:
                return SyncResult(success=True, message='无启用指数', total=0)
            
            callback.update(0, total, '开始同步指数K线...')
            
            # 调用 factor_service 的同步逻辑
            from app.server.services.factor_service import get_factor_service
            fs = get_factor_service()
            
            # 获取同步配置
            sync_cfg = self.get_sync_config()
            enabled_codes = set(idx['code'] for idx in enabled_indices)
            sync_cfg = [c for c in sync_cfg if c.get('code') in enabled_codes]
            
            # 如果没有传入 task_id，生成临时的
            if not task_id:
                import uuid
                task_id = str(uuid.uuid4())
            
            # 调用同步方法 - 只同步目标日期的数据
            end_date = target_date or datetime.now().strftime('%Y%m%d')
            start_date = end_date  # 只同步目标日期
            
            fs._run_sync_indices(task_id, sync_cfg, start_date, end_date, is_external=True)
            
            callback.complete(f'指数K线同步完成: {total} 个')
            return SyncResult(
                success=True,
                message=f'指数K线同步完成: {total} 个',
                total=total,
                synced=total
            )
        except Exception as e:
            logger.error(f'同步指数K线失败: {e}')
            return SyncResult(success=False, message=str(e))
    
    def sync_pe(self, target_date: Optional[str] = None,
                progress_callback: Callable = None) -> SyncResult:
        """
        同步指数 PE（legulegu.com 数据源）
        :param target_date: 指定日期，None 同步最新
        """
        callback = ProgressCallback(progress_callback)
        
        try:
            from app.server.config import get_settings
            settings = get_settings()
            
            if not settings.LEGULEGU_TOKEN:
                return SyncResult(success=True, message='未配置PE Token，跳过', skipped=True)
            
            callback.update(0, 1, '开始同步PE数据...')
            
            # 调用 factor_service 的 PE 同步逻辑
            from app.server.services.factor_service import get_factor_service
            fs = get_factor_service()
            
            import uuid
            temp_task_id = str(uuid.uuid4())
            fs._run_sync_pe(temp_task_id, settings.LEGULEGU_TOKEN, is_external=True)
            
            callback.complete('PE同步完成')
            return SyncResult(success=True, message='PE同步完成')
        except Exception as e:
            logger.error(f'同步PE失败: {e}')
            return SyncResult(success=False, message=str(e))
    
    def compute_rps(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """计算指数 RPS（当前系统指数无 RPS，此方法预留）"""
        return ComputeResult(skipped=True, skip_reason='指数不计算 RPS')
    
    def compute_chg(self, target_date: Optional[str] = None,
                    progress_callback: Callable = None) -> ComputeResult:
        """计算指数区间涨幅"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算指数涨幅...')
            
            # 调用 data_manager 的涨幅计算
            from app.data.manager import get_data_manager
            dm = get_data_manager()
            dm.calculate_chg_fields(target='index', trade_date=target_date)
            
            callback.complete('指数涨幅计算完成')
            return ComputeResult(success=True, message='指数涨幅计算完成')
        except Exception as e:
            logger.error(f'计算指数涨幅失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def compute_ma(self, target_date: Optional[str] = None,
                   progress_callback: Callable = None) -> ComputeResult:
        """计算指数均线"""
        callback = ProgressCallback(progress_callback)
        
        try:
            callback.update(0, 1, '计算指数均线...')
            
            # 指数暂不计算均线
            callback.complete('指数均线计算完成（跳过）')
            return ComputeResult(success=True, message='指数均线计算完成（跳过）')
        except Exception as e:
            logger.error(f'计算指数均线失败: {e}')
            return ComputeResult(success=False, message=str(e))
    
    def run_full_pipeline(self, target_date: Optional[str] = None,
                          progress_callback: Callable = None) -> PipelineResult:
        """
        执行指数全流程：sync_kline → sync_pe → compute_chg → compute_ma
        一键更新时调用此方法
        """
        result = PipelineResult()
        
        result.add_step('sync_kline', self.sync_kline(target_date, progress_callback))
        result.add_step('sync_pe', self.sync_pe(target_date, progress_callback))
        result.add_step('compute_chg', self.compute_chg(target_date, progress_callback))
        result.add_step('compute_ma', self.compute_ma(target_date, progress_callback))
        
        return result
