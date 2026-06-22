"""
股票数据API
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
import pandas as pd
from pypinyin import lazy_pinyin, Style

from app.data.manager import get_data_manager
from app.data.db import get_db
from app.server.models import (
    StockBasic, StockListResponse, DailyDataResponse, DailyBar
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


def get_pinyin_initials(name: str) -> str:
    """获取中文名称的拼音首字母"""
    if not name:
        return ''
    try:
        initials = lazy_pinyin(name, style=Style.FIRST_LETTER)
        return ''.join(initials).lower()
    except:
        return ''


@router.get("/search", response_model=StockListResponse)
def search_stocks(keyword: str = Query(..., description="搜索关键词（代码、名称或拼音首字母）")):
    """模糊搜索股票（支持代码、名称、拼音首字母）"""
    try:
        dm = get_data_manager()
        df = dm.get_stock_list()

        if df.empty:
            return StockListResponse(total=0, data=[])

        keyword_lower = keyword.lower()
        
        # 构建拼音首字母映射（缓存到临时列）
        df['_pinyin'] = df['stock_name'].apply(get_pinyin_initials)
        
        # 多条件匹配：代码、名称、拼音首字母
        mask = (
            df["stock_code"].str.lower().str.contains(keyword_lower, na=False) |
            df["stock_name"].str.lower().str.contains(keyword_lower, na=False) |
            df["_pinyin"].str.contains(keyword_lower, na=False)
        )
        matched_df = df[mask].head(50)

        stocks = []
        for _, row in matched_df.iterrows():
            stocks.append(StockBasic(
                code=row["stock_code"],
                name=row["stock_name"],
                market=row["market"]
            ))

        return StockListResponse(total=len(stocks), data=stocks)

    except Exception as e:
        logger.error(f"搜索股票失败: {e}")
        raise HTTPException(status_code=500, detail="搜索股票失败")


@router.get("", response_model=StockListResponse)
def get_stock_list(
    page: Optional[int] = Query(None, ge=1, description="页码"),
    page_size: Optional[int] = Query(50, ge=1, le=500, description="每页数量"),
    keyword: Optional[str] = Query(None, description="搜索关键词（代码、名称或拼音首字母）"),
    filter_mode: Optional[str] = Query(None, description="筛选模式: enabled/disabled")
):
    """获取股票列表（支持分页、搜索和状态筛选）"""
    try:
        dm = get_data_manager()
        df = dm.get_stock_list()

        if df.empty:
            raise HTTPException(status_code=404, detail="暂无股票数据，请先同步")

        if keyword:
            keyword_lower = keyword.lower()
            df['_pinyin'] = df['stock_name'].apply(get_pinyin_initials)
            mask = (
                df["stock_code"].str.lower().str.contains(keyword_lower, na=False) |
                df["stock_name"].str.lower().str.contains(keyword_lower, na=False) |
                df["_pinyin"].str.contains(keyword_lower, na=False)
            )
            df = df[mask].drop(columns=["_pinyin"], errors="ignore")

        if filter_mode in ('enabled', 'disabled'):
            db = get_db()
            excl_docs = list(db['exclusions'].find(
                {'category': 'stock', 'exclude_sync': True},
                {'_id': 0, 'code': 1}
            ))
            disabled_codes = {d['code'] for d in excl_docs if d.get('code')}
            if filter_mode == 'disabled':
                df = df[df['stock_code'].isin(disabled_codes)]
            else:
                df = df[~df['stock_code'].isin(disabled_codes)]

        total = len(df)

        if page is not None:
            start = (page - 1) * page_size
            df = df.iloc[start:start + page_size]

        stocks = []
        for _, row in df.iterrows():
            stocks.append(StockBasic(
                code=row["stock_code"],
                name=row["stock_name"],
                market=row["market"]
            ))

        return StockListResponse(total=total, data=stocks)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取股票列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取股票列表失败")


@router.post("/scan")
def scan_new_stocks():
    """扫描TDX获取所有股票，与stock_basics对比，返回新增的股票"""
    try:
        import sys
        if '_vendor/pytdx' not in sys.path:
            sys.path.insert(0, '_vendor/pytdx')
        from pytdx.hq import TdxHq_API

        db = get_db()

        # 获取已有股票代码
        existing_codes = set()
        for doc in db['stock_basics'].find({}, {'_id': 0, 'stock_code': 1}):
            existing_codes.add(doc.get('stock_code', ''))

        # 从TDX扫描所有股票
        new_stocks = []
        api = TdxHq_API()
        servers = [
            ('180.153.18.170', 7709),
            ('119.147.212.81', 7709),
            ('60.12.136.250', 7709),
        ]

        for host, port in servers:
            try:
                if api.connect(host, port, time_out=5):
                    for market in [0, 1]:  # 0=深市, 1=沪市
                        count = api.get_security_count(market) or 0
                        for start in range(0, count, 1000):
                            items = api.get_security_list(market, start)
                            if not items:
                                continue
                            for s in items:
                                code = s.get('code', '')
                                name = s.get('name', '')
                                # 只要A股：沪深主板(00/60)、创业板(30)、科创板(68)
                                if (len(code) == 6
                                    and code[:2] in ('00', '60', '30', '68')
                                    and code not in existing_codes
                                    and name and not name.startswith('*')):
                                    new_stocks.append({
                                        'stock_code': code,
                                        'stock_name': name,
                                        'market': '沪市' if market == 1 else '深市'
                                    })
                                    existing_codes.add(code)
                    api.disconnect()
                    break
            except Exception as e:
                logger.warning(f"TDX服务器 {host} 扫描失败: {e}")
                continue

        return {
            'success': True,
            'new_count': len(new_stocks),
            'new_stocks': new_stocks[:100],  # 最多返回100条预览
            'total_existing': len(existing_codes) - len(new_stocks)
        }

    except Exception as e:
        logger.error(f"扫描新股票失败: {e}")
        return {'success': False, 'message': str(e), 'new_count': 0, 'new_stocks': []}


@router.get("/{code}", response_model=StockBasic)
def get_stock_detail(code: str):
    """获取股票详情"""
    try:
        dm = get_data_manager()
        df = dm.get_stock_list()

        if df.empty:
            raise HTTPException(status_code=404, detail="股票不存在")

        stock_df = df[df["stock_code"] == code]
        if stock_df.empty:
            raise HTTPException(status_code=404, detail="股票不存在")

        row = stock_df.iloc[0]
        return StockBasic(code=row["stock_code"], name=row["stock_name"], market=row["market"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取股票详情失败: {e}")
        raise HTTPException(status_code=500, detail="获取股票详情失败")


@router.get("/{code}/daily", response_model=DailyDataResponse)
def get_daily_data(
    code: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    limit: Optional[int] = Query(200, description="返回数据条数，默认200条")
):
    """获取股票日线数据（默认返回最近200条）"""
    try:
        dm = get_data_manager()

        # 设置默认日期范围
        from datetime import datetime, timedelta
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

        # 获取数据
        df = dm.get_stock_daily_data(code, start_date, end_date)

        if df.empty:
            raise HTTPException(status_code=404, detail=f"股票 {code} 暂无数据")

        # 按日期降序排序，只返回最近 limit 条
        df = df.sort_index(ascending=False).head(limit)

        # 转换为DailyBar列表
        bars = []
        for trade_date, row in df.iterrows():
            # 兼容 volume / vol 两种字段名
            # pytdx 用 vol（单位：手），其他用 volume（单位：股）
            # 统一返回股数（vol * 100）
            vol_val = row.get("volume")
            if vol_val is None or pd.isna(vol_val):
                vol_val = row.get("vol")
                if vol_val is not None and not pd.isna(vol_val):
                    vol_val = vol_val * 100  # 手转换为股
            
            bar = DailyBar(
                trade_date=str(trade_date),
                open=float(row["open"]) if "open" in row and not pd.isna(row["open"]) else None,
                high=float(row["high"]) if "high" in row and not pd.isna(row["high"]) else None,
                low=float(row["low"]) if "low" in row and not pd.isna(row["low"]) else None,
                close=float(row["close"]) if "close" in row and not pd.isna(row["close"]) else None,
                volume=int(vol_val) if vol_val is not None and not pd.isna(vol_val) else None,
                amount=float(row["amount"]) if "amount" in row and not pd.isna(row["amount"]) else None,
                amplitude=float(row.get("amplitude", 0)) if "amplitude" in row and not pd.isna(row.get("amplitude")) else None,
                change_pct=float(row.get("change_pct", 0)) if "change_pct" in row and not pd.isna(row.get("change_pct")) else None,
                change=float(row.get("change", 0)) if "change" in row and not pd.isna(row.get("change")) else None,
                turnover=float(row.get("turnover", 0)) if "turnover" in row and not pd.isna(row.get("turnover")) else None
            )
            bars.append(bar)

        # 返回时按日期升序排列（图表需要）
        bars.reverse()

        return DailyDataResponse(code=code, total=len(bars), data=bars)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取日线数据失败: {e}")
        raise HTTPException(status_code=500, detail="获取日线数据失败")
