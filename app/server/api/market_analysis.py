"""
市场多维统计分析 API
"""
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query

from app.data.db import get_db, get_collection
from app.server.api.exclusions import get_excluded_set

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market_analysis", tags=["market_analysis"])


def _quantile_groups(values_with_chg: List[Dict], n_groups: int = 50) -> List[Dict]:
    """按 sort_val 排序后分成 n_groups 个区间，左开右闭 (0,2], (2,4] ..."""
    if not values_with_chg:
        return []

    sorted_data = sorted(values_with_chg, key=lambda x: x['sort_val'])

    total = len(sorted_data)
    group_size = total / n_groups
    result = []

    for i in range(n_groups):
        start_idx = int(i * group_size)
        end_idx = int((i + 1) * group_size)
        group = sorted_data[start_idx:end_idx]

        if not group:
            continue

        avg_chg = sum(g['chg_pct'] for g in group) / len(group)
        # 使用百分位标签：(0,2], (2,4], ..., (98,100]
        step = 100 // n_groups
        low = i * step
        high = (i + 1) * step
        label = f'({low},{high}]'

        result.append({
            'category_label': label,
            'avg_chg': round(avg_chg, 2),
            'count': len(group)
        })

    return result


def _get_previous_trade_date(db, date: str) -> Optional[str]:
    """获取指定日期之前的最近一个交易日"""
    # 从stock_daily集合查询（数据量最大，覆盖最全）
    result = db['stock_daily'].find(
        {'trade_date': {'$lt': date}},
        {'trade_date': 1, '_id': 0}
    ).sort('trade_date', -1).limit(1)
    result_list = list(result)
    return result_list[0]['trade_date'] if result_list else None


@router.get("")
def get_market_analysis(
    date: Optional[str] = Query(None, description="交易日期 YYYYMMDD，默认最新交易日"),
    mode: Optional[str] = Query('sector', description="'sector' 板块气泡 | 'stock' 个股气泡"),
    rps_period: Optional[int] = Query(20, description="RPS周期: 10, 20, 50, 120, 250"),
):
    """
    市场多维统计分析（含 RPS/成交额/股价分组 + 气泡图数据）
    """
    # 验证 RPS 周期参数
    valid_rps_periods = [10, 20, 50, 120, 250]
    if rps_period not in valid_rps_periods:
        rps_period = 20  # 默认值
    """
    市场多维统计分析（含 RPS/成交额/股价分组 + 气泡图数据）
    """
    try:
        db = get_db()

        # 1) 确定查询日期
        if not date:
            latest_stock = db['stock_daily'].find_one(
                {'close': {'$gt': 0}},
                sort=[('trade_date', -1)],
                projection={'trade_date': 1, '_id': 0}
            )
            latest_sector = db['sector_daily'].find_one(
                {},
                sort=[('trade_date', -1)],
                projection={'trade_date': 1, '_id': 0}
            )
            candidates = [d['trade_date'] for d in (latest_stock, latest_sector) if d]
            date = min(candidates) if candidates else None
            if not date:
                raise HTTPException(status_code=404, detail="没有找到交易数据")

        # 2) 前一交易日
        prev_date = _get_previous_trade_date(db, date)

        # === 3) 个股分组统计（仅当有个股数据时）===
        excluded_display_stocks = get_excluded_set('stock', 'display')

        rps_field = f'rps_{rps_period}'
        today_stocks = {d['stock_code']: d for d in db['stock_daily'].find(
            {'trade_date': date, 'close': {'$gt': 0}, 'amount': {'$gt': 0}},
            {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1, 'chg_pct': 1,
             'rps_10': 1, 'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1}
        )}

        # 过滤排除的股票
        if excluded_display_stocks:
            today_stocks = {k: v for k, v in today_stocks.items() if k not in excluded_display_stocks}

        has_stock_data = bool(today_stocks)
        stats_response = {
            'date': date,
            'prev_date': prev_date,
            'total_stocks': 0,
            'rps_stats': [],
            'amount_stats': [],
            'price_stats': [],
        }

        if has_stock_data:
            # 直接使用预计算的chg_pct字段，无需查询前一日数据
            merged = []
            for code, row in today_stocks.items():
                chg_pct = row.get('chg_pct')
                if chg_pct is not None:
                    merged.append({
                        'stock_code': code,
                        'chg_pct': chg_pct,
                        'close': row['close'],
                        'amount': row['amount'],
                        'rps': row.get(rps_field)
                    })

            stats_response['total_stocks'] = len(merged)
            logger.info(f"交易日 {date}: 共 {len(merged)} 只股票参与统计，RPS周期: {rps_period}")

            if merged:
                # RPS 分组（使用动态周期）
                rps_data = [{'chg_pct': d['chg_pct'], 'sort_val': d['rps']} for d in merged if d.get('rps') is not None and d.get('rps') > 0]
                rps_stats = []
                for i in range(50):
                    low = i * 2
                    high = (i + 1) * 2
                    if i == 0:
                        group = [d for d in rps_data if d['sort_val'] <= 2]
                    else:
                        group = [d for d in rps_data if low < d['sort_val'] <= high]
                    if group:
                        avg_chg = sum(g['chg_pct'] for g in group) / len(group)
                        rps_stats.append({
                            'category_label': f'({low},{high}]',
                            'avg_chg': round(avg_chg, 2),
                            'count': len(group)
                        })
                stats_response['rps_stats'] = rps_stats

                # 成交额分组
                amount_data = [{'chg_pct': d['chg_pct'], 'sort_val': d['amount']} for d in merged]
                stats_response['amount_stats'] = _quantile_groups(amount_data, n_groups=50)

                # 股价分组
                price_data = [{'chg_pct': d['chg_pct'], 'sort_val': d['close']} for d in merged]
                stats_response['price_stats'] = _quantile_groups(price_data, n_groups=50)

        # === 4) 气泡图 ===
        if mode == 'stock':
            nodes = _bubble_stock_mode(db, date, prev_date, rps_period)
        else:
            nodes = _bubble_sector_mode(db, date, prev_date, rps_period)

        # 附加信息：该交易日是否已收盘 + 最近一次数据更新时间
        info_cursor = list(db['stock_daily'].find(
            {'trade_date': date},
            {'_id': 0, 'is_final': 1, 'update_time': 1, 'data_source': 1}
        ).limit(50))
        if info_cursor:
            # 多数一致就以多数为准
            final_vals = [doc.get('is_final') for doc in info_cursor if 'is_final' in doc]
            is_final = all(final_vals) if final_vals else None  # 全部 True 才算已收盘
            update_times = sorted(
                [doc['update_time'] for doc in info_cursor if doc.get('update_time')],
                reverse=True
            )
            data_sources = list({doc.get('data_source') for doc in info_cursor if doc.get('data_source')})
            stats_response['is_final'] = is_final  # True 已收盘 / False 半成品 / None 未知
            stats_response['update_time'] = update_times[0].isoformat() if update_times else None
            stats_response['data_sources'] = data_sources
        else:
            stats_response['is_final'] = None
            stats_response['update_time'] = None
            stats_response['data_sources'] = []

        stats_response['bubble'] = {
            'mode': mode,
            'total': len(nodes),
            'nodes': nodes
        }

        return stats_response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"市场分析失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"市场分析失败: {str(e)}")


@router.get("/bubble")
def get_market_bubble(
    date: Optional[str] = Query(None, description="交易日期 YYYYMMDD，默认最新交易日"),
    mode: Optional[str] = Query('sector', description="'sector' 板块气泡 | 'stock' 个股气泡"),
    rps_period: Optional[int] = Query(20, description="RPS周期: 10, 20, 50, 120, 250")
):
    """
    全市场四维动量气泡图（默认板块模式）
    """
    # 验证 RPS 周期参数
    valid_rps_periods = [10, 20, 50, 120, 250]
    if rps_period not in valid_rps_periods:
        rps_period = 20
    try:
        db = get_db()

        # 1) 确定查询日期
        if not date:
            latest_stock = db['stock_daily'].find_one(
                {'close': {'$gt': 0}},
                sort=[('trade_date', -1)],
                projection={'trade_date': 1, '_id': 0}
            )
            latest_sector = db['sector_daily'].find_one(
                {},
                sort=[('trade_date', -1)],
                projection={'trade_date': 1, '_id': 0}
            )
            # 选两者中较小的那个（同时有个股 + 板块数据）
            candidates = [d['trade_date'] for d in (latest_stock, latest_sector) if d]
            date = min(candidates) if candidates else None
            if not date:
                raise HTTPException(status_code=404, detail="没有找到交易数据")

        # 2) 前一交易日（用于计算涨跌幅）
        prev_result = db['stock_daily'].find_one(
            {'trade_date': {'$lt': date}},
            sort=[('trade_date', -1)],
            projection={'trade_date': 1, '_id': 0}
        )
        prev_date = prev_result['trade_date'] if prev_result else None

        # 3) 根据模式查询
        if mode == 'stock':
            nodes = _bubble_stock_mode(db, date, prev_date, rps_period)
        else:
            nodes = _bubble_sector_mode(db, date, prev_date, rps_period)

        if not nodes:
            raise HTTPException(status_code=404, detail=f"日期 {date} 没有找到可用的{'板块' if mode=='sector' else '个股'}数据")

        return {
            'date': date,
            'mode': mode,
            'rps_period': rps_period,
            'total': len(nodes),
            'nodes': nodes
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"bubble 失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="服务器内部错误")


def _bubble_stock_mode(db, date, prev_date, rps_period=20) -> list:
    """个股气泡：rps, close_pct, amount_pct, chg%, name, code"""
    # 获取排除列表
    excluded_display = get_excluded_set('stock', 'display')

    rps_field = f'rps_{rps_period}'
    # 直接使用预计算的 close_pct, amount_pct, chg_pct 字段
    today_cursor = db['stock_daily'].find(
        {
            'trade_date': date, 'close': {'$gt': 0}, 'amount': {'$gt': 0}
        },
        {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1, rps_field: 1,
         'close_pct': 1, 'amount_pct': 1, 'chg_pct': 1}
    )
    today_data = {d['stock_code']: d for d in today_cursor}
    if not today_data:
        return []

    # 股票名映射
    stock_names = {}
    for d in db['stock_basics'].find(
        {'stock_code': {'$in': list(today_data.keys())}},
        {'_id': 0, 'stock_code': 1, 'stock_name': 1}
    ):
        stock_names[d['stock_code']] = d['stock_name']

    nodes = []
    for code, row in today_data.items():
        if code in excluded_display:
            continue
        rps = row.get(rps_field)
        if rps is None: continue
        name = stock_names.get(code, code)
        # 直接使用预计算的百分位字段
        close_pct = row.get('close_pct') or 50
        amount_pct = row.get('amount_pct') or 50
        chg_pct = row.get('chg_pct') or 0.0
        nodes.append([rps, close_pct, amount_pct, chg_pct, name, code])

    return nodes


def _bubble_sector_mode(db, date, prev_date, rps_period=20) -> list:
    """板块气泡：RPS X 轴，板块涨跌幅 Y 轴，板块成交额做气泡大小"""
    # 获取排除列表
    excluded_display = get_excluded_set('sector', 'display')

    excluded_names = {'沪深300', '中证500', '上证50', '创业板指', '科创50',
                      '上证180', '深证成指', '上证指数', '通达信88'}

    # 1) 直接从 sector_daily 查询当日板块行情（使用预计算的chg_pct）
    today_sectors = {d['stock_code']: d for d in db['sector_daily'].find(
        {'trade_date': date, 'close': {'$gt': 0}},
        {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1, 'chg_pct': 1,
         'rps_10': 1, 'rps_20': 1, 'rps_50': 1}
    )}

    # 2) 获取板块名称映射
    name_map = {s['code']: s.get('name', s['code'])
                for s in db['sector_basics'].find(
                    {}, {'_id': 0, 'code': 1, 'name': 1})}

    # 3) 逐板块计算指标（使用预计算的chg_pct）
    sector_metrics = []

    for code, t in today_sectors.items():
        name = name_map.get(code, code)

        # 排除指数类 / 用户排除
        if any(kw in name for kw in excluded_names):
            continue
        if code in excluded_display:
            continue

        # 直接使用预计算的chg_pct
        chg_pct = t.get('chg_pct') or 0.0
        total_amount = t.get('amount') or 0.0
        if total_amount <= 0:
            continue

        rps_map = {
            'rps_10': t.get('rps_10'),
            'rps_20': t.get('rps_20'),
            'rps_50': t.get('rps_50'),
        }
        rps = rps_map.get(f'rps_{rps_period}')

        sector_metrics.append({
            'code': code,
            'name': name,
            'rps': rps if rps is not None else 50,
            'rps_10': rps_map.get('rps_10'),
            'rps_20': rps_map.get('rps_20'),
            'rps_50': rps_map.get('rps_50'),
            'chg_pct': chg_pct,
            'total_amount': total_amount,
            'amount_pct': t.get('amount_pct', 50),
        })

    # 直接使用预计算的 amount_pct 字段
    nodes = []
    for m in sector_metrics:
        nodes.append([
            m['rps'],           # 0: RPS (X轴)
            m['chg_pct'],       # 1: 涨跌幅 (Y)
            m['amount_pct'],    # 2: 成交额百分位 (大小)
            m['chg_pct'],       # 3: 涨跌幅 (颜色)
            m['name'],          # 4: 板块名
            m['code'],          # 5: 板块代码
            0,                  # 6: 成分股数（不再使用）
            m.get('rps_10'),    # 7: RPS10
            m.get('rps_20'),    # 8: RPS20
            m.get('rps_50'),    # 9: RPS50
        ])

    nodes.sort(key=lambda x: x[2], reverse=False)
    return nodes


@router.get("/active_pool")
def get_active_stock_pool(
    date: Optional[str] = Query(None, description="交易日期 YYYYMMDD，默认最新交易日"),
):
    """
    活跃股池：RPS20+RPS50+MAX(RPS120,RPS250)>270 且涨幅>5% 的股票
    使用预计算的 is_active 字段直接查询
    """
    try:
        db = get_db()

        # 确定查询日期
        if not date:
            latest = db['stock_daily'].find_one(
                {'close': {'$gt': 0}},
                sort=[('trade_date', -1)],
                projection={'trade_date': 1, '_id': 0}
            )
            date = latest['trade_date'] if latest else None
            if not date:
                raise HTTPException(status_code=404, detail="没有找到交易数据")

        # 过滤排除的股票
        excluded_display_stocks = get_excluded_set('stock', 'display')

        # 直接使用预计算的 is_active 字段查询活跃股
        query = {
            'trade_date': date,
            'close': {'$gt': 0},
            'amount': {'$gt': 0},
            'is_active': True
        }
        if excluded_display_stocks:
            query['stock_code'] = {'$nin': list(excluded_display_stocks)}

        # 查询活跃股数据
        today_stocks = list(db['stock_daily'].find(
            query,
            {'_id': 0, 'stock_code': 1, 'close': 1, 'amount': 1, 'chg_pct': 1,
             'rps_20': 1, 'rps_50': 1, 'rps_120': 1, 'rps_250': 1, 'rps_sum': 1}
        ))

        if not today_stocks:
            return {'date': date, 'stocks': [], 'total': 0}

        # 股票名称
        stock_codes = [d['stock_code'] for d in today_stocks]
        stock_names = {}
        for d in db['stock_basics'].find(
            {'stock_code': {'$in': stock_codes}},
            {'_id': 0, 'stock_code': 1, 'stock_name': 1}
        ):
            stock_names[d['stock_code']] = d['stock_name']

        # 构建返回数据
        active_stocks = []
        for row in today_stocks:
            code = row['stock_code']
            active_stocks.append({
                'code': code,
                'name': stock_names.get(code, code),
                'close': row['close'],
                'chg_pct': row.get('chg_pct') or 0,
                'amount': row['amount'],
                'rps_20': row.get('rps_20') or 0,
                'rps_50': row.get('rps_50') or 0,
                'rps_120': row.get('rps_120') or 0,
                'rps_250': row.get('rps_250') or 0,
                'rps_sum': row.get('rps_sum') or 0,
            })

        # 按涨幅降序排序
        active_stocks.sort(key=lambda x: x['chg_pct'], reverse=True)

        return {
            'date': date,
            'stocks': active_stocks[:50],  # 最多返回50只
            'total': len(active_stocks)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取活跃股池失败: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误")
