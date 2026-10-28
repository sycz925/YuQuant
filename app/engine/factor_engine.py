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
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pymongo import UpdateOne

from app.data.db import get_db, get_collection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BJ_TZ = ZoneInfo('Asia/Shanghai')

PERIODS = {
    'rps_10': 10,
    'rps_20': 20,
    'rps_50': 50,
    'rps_120': 120,
    'rps_250': 250
}

# 个股RPS周期：10/20/50/120/250
STOCK_RPS_FIELDS = ['rps_10', 'rps_20', 'rps_50', 'rps_120', 'rps_250']
STOCK_RPS_PERIODS = {'rps_10': 10, 'rps_20': 20, 'rps_50': 50, 'rps_120': 120, 'rps_250': 250}

# 板块RPS周期：10/20/50/120/250
SECTOR_RPS_FIELDS = ['rps_10', 'rps_20', 'rps_50', 'rps_120', 'rps_250']
SECTOR_RPS_PERIODS = {'rps_10': 10, 'rps_20': 20, 'rps_50': 50, 'rps_120': 120, 'rps_250': 250}

# 均线周期
MA_PERIODS = [10, 20, 50, 120, 250]
VOL_MA_PERIODS = [5, 10, 20, 50]

# 区间涨幅周期
CHG_PERIODS = [5, 10, 20, 50, 120, 250]


class FactorEngine:
    def __init__(self, data_manager=None):
        self.data_manager = data_manager
        logger.info("FactorEngine 初始化完成")

    def calculate_rps(self, data_type: str = 'stock', max_dates: Optional[int] = None,
                       progress_callback=None, excluded_codes: Optional[List[str]] = None,
                       target_date: Optional[str] = None) -> Dict[str, int]:
        """
        计算 RPS（相对强度）— 递归边界模式

        从最新交易日往前：
        - chg_* 缺失 → 跳过该记录
        - 有 chg_* 无 RPS → 计算
        - 有 RPS → 停止

        Args:
            target_date: 指定日期时只计算该日期的RPS（单日模式），None 为递归模式
        """
        from app.data.db import get_collection
        from pymongo import UpdateOne
        from datetime import timedelta

        coll = get_collection(data_type)

        if data_type == 'sector':
            rps_check_field = 'rps_10'
            chg_fields = ['chg_10d', 'chg_20d', 'chg_50d', 'chg_120d', 'chg_250d']
            chg_field_map = {'chg_10d': 'rps_10', 'chg_20d': 'rps_20', 'chg_50d': 'rps_50', 'chg_120d': 'rps_120', 'chg_250d': 'rps_250'}
        else:
            rps_check_field = 'rps_10'
            chg_fields = ['chg_10d', 'chg_20d', 'chg_50d', 'chg_120d', 'chg_250d']
            chg_field_map = {'chg_10d': 'rps_10', 'chg_20d': 'rps_20', 'chg_50d': 'rps_50', 'chg_120d': 'rps_120', 'chg_250d': 'rps_250'}

        # 单日模式：只计算指定日期的RPS
        if target_date:
            return self._calculate_rps_for_date(coll, target_date, data_type, rps_check_field, chg_fields, chg_field_map, progress_callback, excluded_codes)

        # 递归模式：从最新交易日往前
        latest = coll.find_one(
            {'close': {'$exists': True, '$gt': 0}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0}
        )
        if not latest:
            return {'dates': 0, 'codes': 0, 'updates': 0, 'skipped': 0}

        total_updates = 0
        days_calculated = 0
        day = latest['trade_date']
        is_first_day = True

        while True:
            # 超过10年停止
            try:
                day_dt = datetime.strptime(day, '%Y%m%d')
                if (datetime.now(BJ_TZ).date() - day_dt.date()).days > 3650:
                    break
            except Exception:
                break

            # 检查这天有没有交易数据
            day_count = coll.count_documents({'trade_date': day, 'close': {'$gt': 0}})
            if day_count == 0:
                # 交易日没有交易数据，报错
                from app.data.holidays import is_workday
                if is_workday(day):
                    raise ValueError(f"{day} 是交易日但没有交易数据，请先同步该天数据。")
                # 非交易日，跳到上一天
                day = (day_dt - timedelta(days=1)).strftime('%Y%m%d')
                continue

            # 检查这天 chg_* 是否完整
            projection = {'_id': 0, 'stock_code': 1, 'trade_date': 1}
            for f in chg_fields:
                projection[f] = 1
            projection[rps_check_field] = 1  # 需要检查RPS字段

            query = {'trade_date': day, 'close': {'$gt': 0}}
            if excluded_codes:
                query['stock_code'] = {'$nin': excluded_codes}

            day_data = list(coll.find(query, projection))
            if not day_data:
                day = (day_dt - timedelta(days=1)).strftime('%Y%m%d')
                continue

            # 过滤掉完全没有chg字段的记录（单个字段缺失靠per-field的NaN处理跳过）
            day_data = [d for d in day_data if any(d.get(f) is not None for f in chg_fields)]

            # 检查 RPS 是否已存在（>= 95% 有RPS则停止）
            # 最新交易日永远重算，只有上一天也有才停止
            if not is_first_day:
                with_rps = sum(1 for d in day_data if d.get(rps_check_field) is not None and d.get(rps_check_field) >= 0)
                if with_rps >= len(day_data) * 0.95:
                    logger.info(f"[RPS-{data_type}] {day} RPS 已有 {with_rps}/{len(day_data)}（>=95%），停止")
                    break
            is_first_day = False

            # 计算当天 RPS
            if progress_callback:
                progress_callback(f"{day} 计算中...", days_calculated + 1, 0)

            logger.info(f"[RPS-{data_type}] 计算 {day}（{len(day_data)} 条）")

            set_doc_base = {'update_time': datetime.utcnow()}
            ops = []

            for chg_field, rps_field in chg_field_map.items():
                vals = np.array([d.get(chg_field) for d in day_data], dtype=float)
                valid_mask = ~np.isnan(vals) & (vals != 0)
                valid_count = valid_mask.sum()

                if valid_count == 0:
                    continue

                valid_indices = np.where(valid_mask)[0]
                valid_vals = vals[valid_mask]
                sorted_idx = np.argsort(valid_vals)
                rank_positions = np.empty_like(sorted_idx)
                rank_positions[sorted_idx] = np.arange(1, len(sorted_idx) + 1)
                ranks = np.round(rank_positions / valid_count * 100).astype(int)
                ranks = np.clip(ranks, 1, 100)

                for result_idx, i in enumerate(valid_indices):
                    code = day_data[i]['stock_code']
                    ops.append(UpdateOne(
                        {'stock_code': code, 'trade_date': day},
                        {'$set': {rps_field: int(ranks[result_idx]), **set_doc_base}}
                    ))

            if ops:
                coll.bulk_write(ops, ordered=False)
                total_updates += len(ops)

            days_calculated += 1

            # 返回上一天继续
            day = (day_dt - timedelta(days=1)).strftime('%Y%m%d')

        if progress_callback:
            progress_callback("RPS计算完成", days_calculated, days_calculated)

        logger.info(f"[RPS-{data_type}] 计算完成: {days_calculated} 天, {total_updates} 条更新")
        return {'dates': days_calculated, 'codes': 0, 'updates': total_updates, 'skipped': 0}

    def _calculate_rps_for_date(self, coll, target_date: str, data_type: str,
                                 rps_check_field: str, chg_fields: list, chg_field_map: dict,
                                 progress_callback=None, excluded_codes: Optional[List[str]] = None) -> Dict[str, int]:
        """单日模式：只计算指定日期的RPS"""
        from pymongo import UpdateOne
        from datetime import timedelta

        query = {'trade_date': target_date, 'close': {'$gt': 0}}
        if excluded_codes:
            query['stock_code'] = {'$nin': excluded_codes}

        projection = {'_id': 0, 'stock_code': 1, 'trade_date': 1}
        for f in chg_fields:
            projection[f] = 1
        projection[rps_check_field] = 1

        day_data = list(coll.find(query, projection))
        if not day_data:
            logger.info(f"[RPS-{data_type}] {target_date} 无交易数据，跳过")
            return {'dates': 0, 'codes': 0, 'updates': 0, 'skipped': 0}

        day_data = [d for d in day_data if any(d.get(f) is not None for f in chg_fields)]

        if progress_callback:
            progress_callback(f"{target_date} 计算中...", 1, 1)

        logger.info(f"[RPS-{data_type}] 计算 {target_date}（{len(day_data)} 条）")

        set_doc_base = {'update_time': datetime.utcnow()}
        ops = []

        for chg_field, rps_field in chg_field_map.items():
            vals = np.array([d.get(chg_field) for d in day_data], dtype=float)
            valid_mask = ~np.isnan(vals) & (vals != 0)
            valid_count = valid_mask.sum()

            if valid_count == 0:
                continue

            valid_indices = np.where(valid_mask)[0]
            valid_vals = vals[valid_mask]
            sorted_idx = np.argsort(valid_vals)
            rank_positions = np.empty_like(sorted_idx)
            rank_positions[sorted_idx] = np.arange(1, len(sorted_idx) + 1)
            ranks = np.round(rank_positions / valid_count * 100).astype(int)
            ranks = np.clip(ranks, 1, 100)

            for result_idx, i in enumerate(valid_indices):
                code = day_data[i]['stock_code']
                ops.append(UpdateOne(
                    {'stock_code': code, 'trade_date': target_date},
                    {'$set': {rps_field: int(ranks[result_idx]), **set_doc_base}}
                ))

        if ops:
            coll.bulk_write(ops, ordered=False)

        if progress_callback:
            progress_callback(f"{target_date} RPS计算完成", 1, 1)

        logger.info(f"[RPS-{data_type}] {target_date} 计算完成: {len(ops)} 条更新")
        return {'dates': 1, 'codes': 0, 'updates': len(ops), 'skipped': 0}

    def calculate_derived_fields(self, data_type: str = 'stock', trade_date: str = None,
                                  progress_callback=None, backfill: bool = False,
                                  missing_only: bool = False) -> Dict[str, int]:
        """
        批量计算冗余字段：涨跌幅、均线、成交量均线、区间涨幅

        使用向量化操作一次性计算所有日期，性能比回刷模式高10倍以上。

        Args:
            missing_only: True 时只为「派生字段缺失」的交易日补算（新增标的/历史缺口），
                已有数据的日期跳过。用于增量同步，避免每次全量重算历史。
        """
        coll = get_collection(data_type)

        # 确定计算日期
        missing_pairs = None  # missing_only 模式下精确到 (代码, 日期)
        if trade_date:
            dates_to_calc = [trade_date]
        elif missing_only:
            # 只补缺字段的记录（chg_pct / ma10 / vol_ma5 任一缺失）
            missing_query = {
                'close': {'$gt': 0},
                'derived_skipped': {'$exists': False},
                '$or': [
                    {'chg_pct': {'$exists': False}},
                    {'ma10': {'$exists': False}},
                    {'vol_ma5': {'$exists': False}},
                ],
            }
            missing_pairs = {
                (d['stock_code'], d['trade_date'])
                for d in coll.find(missing_query, {'_id': 0, 'stock_code': 1, 'trade_date': 1})
            }
            if not missing_pairs:
                logger.info(f"[Derived-{data_type}] 派生字段无缺失，跳过")
                return {'dates': 0, 'updates': 0}
            dates_to_calc = sorted({p[1] for p in missing_pairs})
            logger.info(
                f"[Derived-{data_type}] 缺字段补算模式，{len(missing_pairs)} 条记录 / {len(dates_to_calc)} 天")
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

        # 确定成交量字段（统一使用 vol 字段）
        vol_field = 'vol'

        cursor = coll.find(
            {'trade_date': {'$in': dates_to_calc}, 'close': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, vol_field: 1, 'amount': 1,
             'rps_10': 1, 'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
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
                if missing_pairs is not None and (code, d) not in missing_pairs:
                    continue

                set_doc = {'update_time': datetime.utcnow()}
                # 上市最初几天历史不足、均线数学上无法计算：标记跳过，避免每次全量扫描
                if i < max_period - 1:
                    set_doc['derived_skipped'] = True

                # 1. 涨跌幅 chg_pct
                if i >= 1:
                    prev_close = close_arr[i - 1]
                    curr_close = close_arr[i]
                    if prev_close > 0:
                        set_doc['chg_pct'] = round((curr_close - prev_close) / prev_close * 100, 2)

                # 2. 均线 MA（etf 保留 3 位小数，其他 2 位）
                ma_decimals = 3 if data_type == 'etf' else 2
                for period in MA_PERIODS:
                    if i >= period - 1:
                        ma_val = np.mean(close_arr[i - period + 1:i + 1])
                        set_doc[f'ma{period}'] = round(float(ma_val), ma_decimals)

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

    # ==================== 均线 + 二阶段（合并计算） ====================

    # 二阶段与均线所需的完整周期（含 150/200）
    STAGE2_MA_PERIODS = [10, 20, 50, 120, 150, 200, 250]
    # 开盘/昨收偏离超过该比例视为除权跳空（与 watchlist_alert / manager 一致）
    XDXR_GAP_THRESHOLD = 0.15

    @staticmethod
    def _adjust_closes_for_xdxr(closes, opens):
        """检测除权跳空并对历史 close 做前复权（兜底数据层可能残留的未复权历史）。

        返回 (调整后的 closes, 是否检测到除权跳空)。
        前复权为等比缩放，不改变「价格与均线」的相对关系，因此不影响二阶段结论。
        """
        n = len(closes)
        if n < 2:
            return closes, False

        prev = closes[:-1]
        cur_open = np.where(opens[1:] > 0, opens[1:], closes[1:])
        valid = (prev > 0) & (cur_open > 0)
        with np.errstate(divide='ignore', invalid='ignore'):
            ratio = np.where(valid, cur_open / prev, 1.0)
        gaps = np.abs(ratio - 1) > FactorEngine.XDXR_GAP_THRESHOLD
        if not gaps.any():
            return closes, False

        # 从新到旧累计复权因子
        boundaries = []
        cum = 1.0
        for i in range(n - 1, 0, -1):
            pc = closes[i - 1]
            op = opens[i] if opens[i] > 0 else closes[i]
            if pc <= 0 or op <= 0:
                continue
            if abs(op / pc - 1) > FactorEngine.XDXR_GAP_THRESHOLD:
                cum *= pc / op
                boundaries.append((i, cum))

        adjusted = closes.copy()
        boundaries.reverse()  # 转为按时间升序
        prev_idx = 0
        for idx, factor in boundaries:
            if prev_idx < idx:
                adjusted[prev_idx:idx] /= factor
            prev_idx = idx
        return adjusted, True

    def calculate_daily_factors(self, data_type: str = 'stock', trade_date: Optional[str] = None,
                                progress_callback=None) -> Dict[str, int]:
        """一次加载历史，计算 MA(10/20/50/120/150/200/250) + 52周高低点 + 二阶段，一次写库。

        - 先按除权跳空做前复权，再算均线（避免未复权历史污染均线）
        - 8 条标准全部满足 is_stage2=True：
          1. close > ma150 且 close > ma200
          2. ma150 > ma200
          3. ma200 向上（对比 20 个交易日前）
          4. ma50 > ma150 且 ma50 > ma200
          5. close > ma50
          6. close >= 52周低点 * 1.25
          7. close >= 52周高点 * 0.75
          8. rps_120 >= 90
        """
        coll = get_collection(data_type)

        if not trade_date:
            latest = coll.find_one(
                {'close': {'$gt': 0}},
                sort=[('trade_date', -1)],
                projection={'trade_date': 1, '_id': 0}
            )
            if not latest:
                return {'dates': 0, 'updates': 0}
            trade_date = latest['trade_date']

        # 历史窗口：约 420 自然日（≈285 个交易日），覆盖 200 日均线 + 20 日偏移 + 52 周
        try:
            start_dt = datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=420)
            hist_start = start_dt.strftime('%Y%m%d')
        except Exception:
            return {'dates': 0, 'updates': 0}

        hist = list(coll.find(
            {'trade_date': {'$gte': hist_start, '$lte': trade_date}, 'close': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'trade_date': 1, 'close': 1, 'open': 1, 'rps_120': 1}
        ))
        if not hist:
            return {'dates': 0, 'updates': 0}

        if progress_callback:
            progress_callback("计算均线与二阶段...", 0, 1, "均线+二阶段")

        df = pd.DataFrame(hist).sort_values(['stock_code', 'trade_date'])
        ma_dec = 3 if data_type == 'etf' else 2
        periods = self.STAGE2_MA_PERIODS

        ops = []
        adjusted_cnt = 0
        for code, g in df.groupby('stock_code', sort=False):
            # 只处理目标日有数据的标的（停牌/无当日行情的不参与）
            if str(g['trade_date'].iloc[-1]) != str(trade_date):
                continue

            closes = g['close'].to_numpy(dtype=float)
            opens = g['open'].to_numpy(dtype=float) if 'open' in g.columns else closes
            opens = np.where(np.isnan(opens), closes, opens)
            n = len(closes)
            if n < 50:
                continue

            # 数据已由 pytdx 数据源做前复权，且 500 天窗口已统一重拉，序列连续。
            # 不再用「跳空检测」兜底：跳空可能是真实大跌（-20% 跌停 / 退市整理 / 复牌暴跌），
            # 当作除权做等比缩放会篡改均线，属于错误修复。
            adj = closes
            was_adjusted = False

            set_doc = {'update_time': datetime.utcnow()}

            # 均线（复权后序列）
            for p in periods:
                if n >= p:
                    set_doc[f'ma{p}'] = round(float(np.mean(adj[-p:])), ma_dec)

            # 二阶段（需 220 日：200 日均线 + 20 日偏移）
            if n >= 220:
                close_now = float(adj[-1])
                ma50 = float(np.mean(adj[-50:]))
                ma150 = float(np.mean(adj[-150:]))
                ma200 = float(np.mean(adj[-200:]))
                ma200_prev = float(np.mean(adj[-220:-20]))
                window = adj[-250:] if n >= 250 else adj
                high52 = float(np.max(window))
                low52 = float(np.min(window))
                rps120_raw = g['rps_120'].iloc[-1]
                rps120 = None if pd.isna(rps120_raw) else int(rps120_raw)

                c1 = close_now > ma150 and close_now > ma200
                c2 = ma150 > ma200
                c3 = ma200 > ma200_prev
                c4 = ma50 > ma150 and ma50 > ma200
                c5 = close_now > ma50
                c6 = close_now >= low52 * 1.25
                c7 = close_now >= high52 * 0.75
                c8 = rps120 is not None and rps120 >= 90

                set_doc['is_stage2'] = bool(c1 and c2 and c3 and c4 and c5 and c6 and c7 and c8)
                set_doc['stage2_detail'] = {
                    'close': round(close_now, 3),
                    'ma50': round(ma50, 3),
                    'ma150': round(ma150, 3),
                    'ma200': round(ma200, 3),
                    'ma200_prev20': round(ma200_prev, 3),
                    'high52': round(high52, 3),
                    'low52': round(low52, 3),
                    'rps120': rps120,
                    'xdxr_adjusted': bool(was_adjusted),
                    'checks': {
                        'c1_close_over_ma150_200': bool(c1),
                        'c2_ma150_over_ma200': bool(c2),
                        'c3_ma200_rising': bool(c3),
                        'c4_ma50_over_ma150_200': bool(c4),
                        'c5_close_over_ma50': bool(c5),
                        'c6_above_52w_low': bool(c6),
                        'c7_near_52w_high': bool(c7),
                        'c8_rps120_ge_90': bool(c8),
                    },
                }

            ops.append(UpdateOne(
                {'stock_code': code, 'trade_date': trade_date},
                {'$set': set_doc}
            ))

        if ops:
            coll.bulk_write(ops, ordered=False)

        logger.info(
            f"[DailyFactors-{data_type}] {trade_date} 完成: {len(ops)} 条"
            + (f"（其中 {adjusted_cnt} 只做了前复权修正）" if adjusted_cnt else "")
        )
        return {'dates': 1, 'updates': len(ops), 'adjusted': adjusted_cnt}

    def calculate_stage2(self, data_type: str = 'stock', trade_date: Optional[str] = None,
                         progress_callback=None) -> Dict[str, int]:
        """兼容旧调用：等价于 calculate_daily_factors（同时刷新均线与二阶段）。"""
        return self.calculate_daily_factors(data_type, trade_date, progress_callback)

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

            cr5 = round((top5_amount / total_amount) * 100, 2)
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
