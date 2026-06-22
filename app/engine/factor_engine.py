"""
因子引擎 - RPS 计算 + 冗余字段批量计算
设计目标：
1. 高效计算 RPS（相对强度百分比排名）
2. 支持个股（data_type='stock'）和行业板块（data_type='sector'）
3. 增量计算：只计算缺失的日期
4. 批量计算冗余字段：MA/VOL_MA/区间涨幅/涨跌幅/百分位
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

import numpy as np
import pandas as pd
from pymongo import UpdateOne

from app.data.db import get_db, get_collection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PERIODS = {
    'rps_10': 10,
    'rps_20': 20,
    'rps_50': 50,
    'rps_120': 120,
    'rps_250': 250
}

# 个股RPS周期：20/50/120/250（不含10日）
STOCK_RPS_FIELDS = ['rps_20', 'rps_50', 'rps_120', 'rps_250']
STOCK_RPS_PERIODS = {'rps_20': 20, 'rps_50': 50, 'rps_120': 120, 'rps_250': 250}

# 板块RPS周期：10/20/50
SECTOR_RPS_FIELDS = ['rps_10', 'rps_20', 'rps_50']
SECTOR_RPS_PERIODS = {'rps_10': 10, 'rps_20': 20, 'rps_50': 50}

# 均线周期
MA_PERIODS = [10, 20, 50, 120]
VOL_MA_PERIODS = [5, 10, 20, 50]

# 区间涨幅周期
CHG_PERIODS = [5, 10, 20, 50, 120, 250]


class FactorEngine:
    def __init__(self, data_manager=None):
        self.data_manager = data_manager
        logger.info("FactorEngine 初始化完成")

    def calculate_rps(self, data_type: str = 'stock', max_dates: Optional[int] = None,
                       progress_callback=None, excluded_codes: Optional[List[str]] = None) -> Dict[str, int]:
        """
        计算 RPS（相对强度）— 窗口批量模式

        核心思路：
        1. 找出有空RPS数据的最小日期（需要计算的起始日期）
        2. 加载全部历史数据构建价格矩阵
        3. 批量计算所有日期的RPS
        4. 数据不足的周期记为-1
        5. 批量写入
        """
        from app.data.db import get_collection
        coll = get_collection(data_type)

        # 1. 扫描日期范围
        if progress_callback:
            progress_callback("正在扫描日期范围...", 0, 100, "扫描")

        all_dates = sorted(coll.distinct(
            'trade_date', {'close': {'$exists': True, '$gt': 0}}
        ))
        if not all_dates:
            return {'dates': 0, 'codes': 0, 'updates': 0, 'skipped': 0}

        # 根据类型选择判断字段和周期
        if data_type == 'sector':
            periods = SECTOR_RPS_PERIODS
            rps_check_field = 'rps_10'
        else:
            periods = STOCK_RPS_PERIODS
            rps_check_field = 'rps_20'

        # 找出有空RPS数据的最小日期
        # 查询每个日期的rps_check_field是否存在（排除-1，-1表示数据不足）
        pipeline = [
            {'$match': {'close': {'$exists': True, '$gt': 0}}},
            {'$group': {
                '_id': '$trade_date',
                'total': {'$sum': 1},
                'with_rps': {'$sum': {'$cond': [{'$and': [
                    {'$gte': [f'${rps_check_field}', 0]},
                    {'$ne': [f'${rps_check_field}', -1]}
                ]}, 1, 0]}}
            }}
        ]
        date_stats = {r['_id']: (r['total'], r['with_rps']) for r in coll.aggregate(pipeline)}

        # 找出需要计算的日期（有空RPS数据的）
        # 只检查最近30天，历史日期跳过
        recent_dates = [d for d in all_dates if d >= all_dates[-30]] if len(all_dates) > 30 else all_dates
        dates_to_calc = []
        for d in recent_dates:
            if d in date_stats:
                total, with_rps = date_stats[d]
                if total != with_rps:
                    dates_to_calc.append(d)

        if not dates_to_calc:
            logger.info(f"[RPS-{data_type}] 无需更新")
            return {'dates': 0, 'codes': 0, 'updates': 0, 'skipped': len(all_dates)}

        logger.info(f"[RPS-{data_type}] 需计算 {len(dates_to_calc)} 天: {dates_to_calc[0]}~{dates_to_calc[-1]}")

        # 2. 加载数据：所有缺失日期 + 前250天历史（用于chg_250d排名）
        if progress_callback:
            progress_callback(f"正在加载数据...", 0, len(dates_to_calc))

        from datetime import datetime as _dt, timedelta
        target_date = dates_to_calc[0]
        try:
            pre_start = (_dt.strptime(target_date, '%Y%m%d') - timedelta(days=300)).strftime('%Y%m%d')
        except Exception:
            pre_start = target_date

        query = {
            'trade_date': {'$in': dates_to_calc},
            'close': {'$exists': True, '$gt': 0}
        }
        if excluded_codes:
            query['stock_code'] = {'$nin': excluded_codes}

        # 加载涨幅字段用于RPS排名
        if data_type == 'sector':
            chg_fields = ['chg_10d', 'chg_20d', 'chg_50d']
        else:
            chg_fields = ['chg_20d', 'chg_50d', 'chg_120d', 'chg_250d']

        projection = {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1}
        for f in chg_fields:
            projection[f] = 1

        cursor = coll.find(query, projection)
        raw_data = list(cursor)
        if not raw_data:
            return {'dates': 0, 'codes': 0, 'updates': 0, 'skipped': 0}

        logger.info(f"[RPS-{data_type}] 加载 {len(raw_data)} 条记录")

        if progress_callback:
            progress_callback(f"计算 {len(raw_data)} 条数据的RPS...", 0, 1)

        df = pd.DataFrame(raw_data)
        del raw_data

        # 字段映射
        chg_field_map = {f'chg_{p}d': f'rps_{p}' for p in [20, 50, 120, 250]}
        if data_type == 'sector':
            chg_field_map = {f'chg_{p}d': f'rps_{p}' for p in [10, 20, 50]}

        total_ops = []
        total_updates = 0
        calc_dates = sorted(df['trade_date'].unique())
        n_dates = len(calc_dates)

        # 向量化计算：按日期分组后批量排名
        for d_idx, trade_date in enumerate(calc_dates):
            if progress_callback and d_idx % 10 == 0:
                progress_callback(f"{trade_date} 计算中...", d_idx + 1, n_dates)

            day_df = df[df['trade_date'] == trade_date]
            stock_codes = day_df['stock_code'].values

            # 对每个周期计算排名
            set_doc_base = {'update_time': datetime.utcnow()}
            for chg_field, rps_field in chg_field_map.items():
                if chg_field not in day_df.columns:
                    continue

                vals = day_df[chg_field].values.astype(float)
                valid_mask = ~np.isnan(vals) & (vals != 0)
                valid_count = valid_mask.sum()

                if valid_count == 0:
                    continue

                # numpy快速排名
                ranks = np.zeros(len(vals), dtype=int)
                valid_vals = vals[valid_mask]
                sorted_idx = np.argsort(valid_vals)
                rank_positions = np.empty_like(sorted_idx)
                rank_positions[sorted_idx] = np.arange(1, len(sorted_idx) + 1)
                ranks[valid_mask] = np.round(rank_positions / valid_count * 100).astype(int)
                ranks = np.clip(ranks, 1, 100)

                # 批量构建更新操作
                for i in range(len(stock_codes)):
                    total_ops.append(
                        UpdateOne(
                            {'stock_code': stock_codes[i], 'trade_date': trade_date},
                            {'$set': {rps_field: int(ranks[i]), **set_doc_base}}
                        )
                    )

            # 每10天批量写入一次
            if len(total_ops) >= 50000:
                coll.bulk_write(total_ops, ordered=False)
                total_updates += len(total_ops)
                total_ops = []

        # 写入剩余
        if total_ops:
            coll.bulk_write(total_ops, ordered=False)
            total_updates += len(total_ops)

        if progress_callback:
            progress_callback(f"RPS计算完成", n_dates, n_dates)

        logger.info(f"[RPS-{data_type}] 计算完成: {n_dates} 天, {total_updates} 条更新")
        return {'dates': n_dates, 'codes': len(df['stock_code'].unique()), 'updates': total_updates, 'skipped': 0}

    def calculate_derived_fields(self, data_type: str = 'stock', trade_date: str = None,
                                  progress_callback=None, backfill: bool = False) -> Dict[str, int]:
        """
        批量计算冗余字段：涨跌幅、均线、成交量均线、区间涨幅

        使用向量化操作一次性计算所有日期，性能比回刷模式高10倍以上。
        """
        coll = get_collection(data_type)

        # 确定计算日期
        if trade_date:
            dates_to_calc = [trade_date]
        elif backfill:
            dates_to_calc = sorted(coll.distinct('trade_date', {'close': {'$gt': 0}}))
            logger.info(f"[Derived-{data_type}] 回刷模式，共 {len(dates_to_calc)} 天")
        else:
            latest = coll.find_one(
                {'close': {'$gt': 0}},
                sort=[('trade_date', -1)],
                projection={'trade_date': 1, '_id': 0}
            )
            if not latest:
                return {'dates': 0, 'updates': 0}
            dates_to_calc = [latest['trade_date']]

        if not dates_to_calc:
            return {'dates': 0, 'updates': 0}

        logger.info(f"[Derived-{data_type}] 开始计算 {len(dates_to_calc)} 天")

        # 加载全部数据（一次性）
        if progress_callback:
            progress_callback("加载数据...", 0, 100, "加载")

        # 确定成交量字段
        vol_field = 'volume' if data_type == 'sector' else 'vol'

        cursor = coll.find(
            {'trade_date': {'$in': dates_to_calc}, 'close': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, vol_field: 1, 'amount': 1,
             'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
        )
        raw_data = list(cursor)
        if not raw_data:
            return {'dates': 0, 'updates': 0}

        df = pd.DataFrame(raw_data)
        logger.info(f"[Derived-{data_type}] 加载 {len(df)} 条记录")

        # 加载历史数据用于计算MA（向前多取1年）
        if progress_callback:
            progress_callback("加载历史数据...", 10, 100, "历史数据")

        max_period = max(MA_PERIODS + VOL_MA_PERIODS + CHG_PERIODS)
        earliest_date = min(dates_to_calc)
        try:
            start_dt = datetime.strptime(earliest_date, '%Y%m%d') - timedelta(days=int(max_period * 1.5))
            hist_start = start_dt.strftime('%Y%m%d')
        except Exception:
            hist_start = earliest_date

        hist_cursor = coll.find(
            {'trade_date': {'$gte': hist_start, '$lt': earliest_date}, 'close': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, vol_field: 1}
        )
        hist_data = list(hist_cursor)

        # 合并历史数据和目标数据
        if hist_data:
            hist_df = pd.DataFrame(hist_data)
            full_df = pd.concat([hist_df, df], ignore_index=True)
        else:
            full_df = df.copy()

        full_df = full_df.sort_values(['stock_code', 'trade_date'])

        # 确定成交量字段名
        actual_vol_field = vol_field if vol_field in full_df.columns else ('vol' if 'vol' in full_df.columns else 'volume')

        # 按stock_code分组，使用rolling计算MA和VOL_MA
        if progress_callback:
            progress_callback("计算均线...", 30, 100, "均线")

        calc_set = set(dates_to_calc)
        ops = []
        total_updates = 0

        for code in df['stock_code'].unique():
            code_df = full_df[full_df['stock_code'] == code].sort_values('trade_date')
            if len(code_df) < 2:
                continue

            close_arr = code_df['close'].values
            vol_arr = code_df[actual_vol_field].values if actual_vol_field in code_df.columns else None
            dates_arr = code_df['trade_date'].values

            # 找到目标日期在完整数据中的位置
            for i, d in enumerate(dates_arr):
                if d not in calc_set:
                    continue

                set_doc = {'update_time': datetime.utcnow()}

                # 1. 涨跌幅 chg_pct
                if i >= 1:
                    prev_close = close_arr[i - 1]
                    curr_close = close_arr[i]
                    if prev_close > 0:
                        set_doc['chg_pct'] = round((curr_close - prev_close) / prev_close * 100, 2)

                # 2. 均线 MA
                for period in MA_PERIODS:
                    if i >= period - 1:
                        ma_val = np.mean(close_arr[i - period + 1:i + 1])
                        set_doc[f'ma{period}'] = round(float(ma_val), 2)

                # 3. 成交量均线 VOL_MA
                if vol_arr is not None:
                    for period in VOL_MA_PERIODS:
                        if i >= period - 1:
                            vol_ma_val = np.mean(vol_arr[i - period + 1:i + 1])
                            set_doc[f'vol_ma{period}'] = round(float(vol_ma_val), 2)

                # 4. 区间涨幅 CHG_Xd
                for period in CHG_PERIODS:
                    if i >= period:
                        curr_close = close_arr[i]
                        prev_close = close_arr[i - period]
                        if prev_close > 0:
                            set_doc[f'chg_{period}d'] = round((curr_close - prev_close) / prev_close * 100, 2)

                # 5. RPS衍生指标（仅个股）
                if data_type == 'stock':
                    row = code_df.iloc[i]
                    rps_20 = row.get('rps_20')
                    rps_50 = row.get('rps_50')
                    rps_120 = row.get('rps_120')
                    rps_250 = row.get('rps_250')

                    rps_vals = [v for v in [rps_20, rps_50, max(rps_120 or 0, rps_250 or 0)] if v is not None and v > 0]
                    if len(rps_vals) == 3:
                        rps_sum = rps_vals[0] + rps_vals[1] + rps_vals[2]
                        set_doc['rps_sum'] = int(rps_sum)
                        chg_pct = set_doc.get('chg_pct', 0) or 0
                        set_doc['is_active'] = bool(rps_sum > 270 and chg_pct > 5)

                ops.append(
                    UpdateOne(
                        {'stock_code': code, 'trade_date': d},
                        {'$set': set_doc}
                    )
                )

            # 每5万条批量写入
            if len(ops) >= 50000:
                if progress_callback:
                    progress_callback("写入数据库...", 90, 100, "写入")
                res = coll.bulk_write(ops, ordered=False)
                total_updates += res.modified_count + res.upserted_count
                ops = []

        # 写入剩余
        if ops:
            res = coll.bulk_write(ops, ordered=False)
            total_updates += res.modified_count + res.upserted_count

        logger.info(f"[Derived-{data_type}] 计算完成: {len(dates_to_calc)} 天, {total_updates} 条更新")
        return {'dates': len(dates_to_calc), 'updates': total_updates}

    def calculate_percentile_fields(self, data_type: str = 'stock', trade_date: str = None,
                                     progress_callback=None, backfill: bool = False) -> Dict[str, int]:
        """
        计算百分位字段：close_pct, amount_pct（需要全市场排序）

        使用批量模式一次性计算所有日期。
        """
        coll = get_collection(data_type)

        # 确定计算日期
        if trade_date:
            dates_to_calc = [trade_date]
        elif backfill:
            dates_to_calc = sorted(coll.distinct('trade_date', {'close': {'$gt': 0}, 'amount': {'$gt': 0}}))
            logger.info(f"[Percentile-{data_type}] 回刷模式，共 {len(dates_to_calc)} 天")
        else:
            latest = coll.find_one(
                {'close': {'$gt': 0}},
                sort=[('trade_date', -1)],
                projection={'trade_date': 1, '_id': 0}
            )
            if not latest:
                return {'dates': 0, 'updates': 0}
            dates_to_calc = [latest['trade_date']]

        if not dates_to_calc:
            return {'dates': 0, 'updates': 0}

        logger.info(f"[Percentile-{data_type}] 开始计算 {len(dates_to_calc)} 天")

        # 加载所有目标日期的数据
        if progress_callback:
            progress_callback("加载数据...", 0, 100, "加载")

        cursor = coll.find(
            {'trade_date': {'$in': dates_to_calc}, 'close': {'$gt': 0}, 'amount': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, 'amount': 1}
        )
        raw_data = list(cursor)
        if not raw_data:
            return {'dates': 0, 'updates': 0}

        df = pd.DataFrame(raw_data)
        logger.info(f"[Percentile-{data_type}] 加载 {len(df)} 条记录")

        # 按日期分组计算百分位
        ops = []
        total_updates = 0
        calc_set = set(dates_to_calc)

        for calc_date in dates_to_calc:
            day_df = df[df['trade_date'] == calc_date]
            if len(day_df) < 10:
                continue

            # 计算百分位
            day_df = day_df.copy()
            day_df['close_rank'] = day_df['close'].rank(pct=True) * 100
            day_df['amount_rank'] = day_df['amount'].rank(pct=True) * 100

            for _, row in day_df.iterrows():
                ops.append(
                    UpdateOne(
                        {'stock_code': row['stock_code'], 'trade_date': calc_date},
                        {'$set': {
                            'close_pct': int(round(row['close_rank'])),
                            'amount_pct': int(round(row['amount_rank'])),
                            'update_time': datetime.utcnow()
                        }}
                    )
                )

            # 每5万条批量写入
            if len(ops) >= 50000:
                if progress_callback:
                    progress_callback("写入数据库...", 90, 100, "写入")
                res = coll.bulk_write(ops, ordered=False)
                total_updates += res.modified_count + res.upserted_count
                ops = []

        # 写入剩余
        if ops:
            res = coll.bulk_write(ops, ordered=False)
            total_updates += res.modified_count + res.upserted_count

        logger.info(f"[Percentile-{data_type}] 计算完成: {len(dates_to_calc)} 天, {total_updates} 条更新")
        return {'dates': len(dates_to_calc), 'updates': total_updates}

    def calculate_all_derived(self, data_type: str = 'stock', trade_date: str = None,
                               progress_callback=None, backfill: bool = False) -> Dict[str, Any]:
        """
        一键计算所有冗余字段（MA、VOL_MA、CHG、涨跌幅、百分位）

        Args:
            data_type: 'stock' 或 'sector'
            trade_date: 指定日期，None则计算最新日期
            backfill: True则回刷所有历史数据
        """
        results = {}

        # 1. 计算基础冗余字段（MA、VOL_MA、CHG、涨跌幅）
        if progress_callback:
            progress_callback("计算基础冗余字段...", 0, 100, "基础字段")
        results['derived'] = self.calculate_derived_fields(data_type, trade_date, progress_callback, backfill)

        # 2. 计算百分位字段（close_pct, amount_pct）
        if progress_callback:
            progress_callback("计算百分位字段...", 50, 100, "百分位")
        results['percentile'] = self.calculate_percentile_fields(data_type, trade_date, progress_callback, backfill)

        logger.info(f"[AllDerived-{data_type}] 全部冗余字段计算完成: {results}")
        return results

    # ==================== CR5% 拥挤度 ====================

    def calculate_cr5_percent(self, trade_date: str) -> Optional[float]:
        """计算成交额前 5% 拥挤度因子"""
        try:
            from app.data.db import get_collection
            stock_coll = get_collection('stock')
            pipeline = [
                {'$match': {'trade_date': trade_date, 'amount': {'$exists': True, '$gt': 0}}},
                {'$project': {'amount': 1, '_id': 0}},
                {'$sort': {'amount': -1}}
            ]
            results = list(stock_coll.aggregate(pipeline))
            if len(results) < 100:
                return None

            amounts = [r['amount'] for r in results]
            n_top = max(1, int(len(amounts) * 0.05))
            top5_amount = sum(amounts[:n_top])
            total_amount = sum(amounts)

            if total_amount == 0:
                return None

            cr5 = (top5_amount / total_amount) * 100
            logger.info(f"CR5% {trade_date}: {cr5:.2f}% ({len(amounts)} 只)")
            return cr5
        except Exception as e:
            logger.error(f"计算CR5%失败: {e}")
            return None

    def get_all_cr5_history(self, start_date: str, end_date: str) -> dict:
        """获取指定日期范围内的个股 CR5% 历史数据（使用聚合管道优化）"""
        from app.data.db import get_collection
        stock_coll = get_collection('stock')

        dates = sorted(stock_coll.distinct(
            'trade_date',
            {'trade_date': {'$gte': start_date, '$lte': end_date}}
        ))
        if not dates:
            return {}

        # 使用聚合管道直接计算CR5%，避免Python端排序
        pipeline = [
            {'$match': {
                'trade_date': {'$in': dates},
                'amount': {'$exists': True, '$gt': 0}
            }},
            {'$group': {
                '_id': '$trade_date',
                'amounts': {'$push': '$amount'},
                'total': {'$sum': '$amount'},
                'count': {'$sum': 1}
            }},
            {'$match': {'count': {'$gte': 100}}}  # 至少100只股票
        ]
        
        cr5_series = {}
        for r in stock_coll.aggregate(pipeline, allowDiskUse=True):
            date = r['_id']
            amounts = r['amounts']
            total_amount = r['total']
            
            if total_amount <= 0:
                continue
            
            # 快速获取top5%（用numpy代替Python排序）
            amounts_arr = np.array(amounts)
            threshold = np.percentile(amounts_arr, 95)
            top5_amount = amounts_arr[amounts_arr >= threshold].sum()
            
            cr5_series[date] = round((top5_amount / total_amount) * 100, 4)

        logger.info(f"CR5% 历史数据: {len(cr5_series)} 天 ({start_date}~{end_date})")
        return cr5_series

    def get_sector_cr_history(self, start_date: str, end_date: str, percentile: int = 15) -> dict:
        """获取指定日期范围内的板块 CR% 历史数据
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            percentile: 百分位，默认15（CR15%）
        """
        from app.data.db import get_collection
        sector_coll = get_collection('sector')

        dates = sorted(sector_coll.distinct(
            'trade_date',
            {'trade_date': {'$gte': start_date, '$lte': end_date}}
        ))
        if not dates:
            return {}

        pipeline = [
            {'$match': {
                'trade_date': {'$in': dates},
                'amount': {'$exists': True, '$gt': 0}
            }},
            {'$group': {
                '_id': '$trade_date',
                'amounts': {'$push': '$amount'},
                'total': {'$sum': '$amount'},
                'count': {'$sum': 1}
            }},
            {'$match': {'count': {'$gte': 10}}}
        ]

        threshold_pct = 100 - percentile  # CR15% = 前15% = percentile(85)
        cr_series = {}
        for r in sector_coll.aggregate(pipeline, allowDiskUse=True):
            date = r['_id']
            amounts = r['amounts']
            total_amount = r['total']

            if total_amount <= 0:
                continue

            amounts_arr = np.array(amounts)
            threshold = np.percentile(amounts_arr, threshold_pct)
            top_amount = amounts_arr[amounts_arr >= threshold].sum()

            cr_series[date] = round((top_amount / total_amount) * 100, 4)

        logger.info(f"板块 CR{percentile}% 历史数据: {len(cr_series)} 天 ({start_date}~{end_date})")
        return cr_series
