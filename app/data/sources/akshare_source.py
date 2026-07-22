"""
AkShare 数据源封装
"""
import logging
import time
import pandas as pd
from typing import Optional, Tuple, List, Dict

logger = logging.getLogger(__name__)


class AkShareSource:
    @staticmethod
    def get_stock_basics() -> Optional[pd.DataFrame]:
        """获取股票基础信息"""
        import akshare as ak
        for attempt in range(3):
            try:
                df = ak.stock_info_a_code_name()
                if not df.empty:
                    df.columns = ['stock_code', 'stock_name']
                    df['market'] = df['stock_code'].apply(
                        lambda x: 'SH' if x.startswith('6') else 'SZ'
                    )
                    df['list_date'] = None
                    return df
            except Exception as e:
                print(f"AkShare 获取股票列表失败 (尝试 {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))  # 指数退避
        return None

    @staticmethod
    def get_daily_data(stock_code: str, start_date: str, end_date: str) -> Tuple[Optional[pd.DataFrame], str]:
        """
        获取日线行情数据
        返回: (DataFrame, data_source)
        """
        import akshare as ak
        for attempt in range(3):
            try:
                df = ak.stock_zh_a_hist(
                    symbol=stock_code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="qfq"
                )
                if not df.empty:
                    # 字段映射
                    result_df = pd.DataFrame()
                    result_df['trade_date'] = df['日期'].astype(str).str.replace('-', '')
                    result_df['open'] = df['开盘']
                    result_df['high'] = df['最高']
                    result_df['low'] = df['最低']
                    result_df['close'] = df['收盘']
                    result_df['volume'] = df['成交量']
                    result_df['amount'] = df['成交额']
                    if '涨跌幅' in df.columns:
                        result_df['change_pct'] = df['涨跌幅']
                    if '涨跌额' in df.columns:
                        result_df['change'] = df['涨跌额']
                    if '振幅' in df.columns:
                        result_df['amplitude'] = df['振幅']
                    if '换手率' in df.columns:
                        result_df['turnover'] = df['换手率']
                    return result_df, 'akshare'
            except Exception as e:
                print(f"AkShare 获取数据失败 {stock_code} (尝试 {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))  # 指数退避
        return None, ''

    @staticmethod
    def get_industry_list() -> Optional[pd.DataFrame]:
        """获取东方财富行业板块列表"""
        import akshare as ak
        for attempt in range(3):
            try:
                df = ak.stock_board_industry_name_em()
                if not df.empty:
                    # 返回格式: ['板块名称', '板块代码', '最新价', '涨跌幅', '涨跌额', '总市值', '换手率', '上涨家数', '下跌家数', '领涨股票', '涨跌幅.1']
                    logger.info(f"获取东方财富行业板块列表成功，共 {len(df)} 个行业")
                    return df[['板块名称', '板块代码']]
            except Exception as e:
                logger.error(f"获取东方财富行业板块列表失败 (尝试 {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
        return None

    @staticmethod
    def get_industry_hist(industry_name: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        获取东方财富行业板块历史行情
        :param industry_name: 行业板块名称，如 "银行"
        :param start_date: 开始日期 YYYYMMDD
        :param end_date: 结束日期 YYYYMMDD
        :return: DataFrame with columns [trade_date, open, high, low, close, volume, amount]
        """
        import akshare as ak
        # akshare 需要 YYYY-MM-DD 格式
        sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
        for attempt in range(3):
            try:
                df = ak.stock_board_industry_hist_em(
                    symbol=industry_name,
                    start_date=sd,
                    end_date=ed,
                    period="日k",
                    adjust=""
                )
                if df.empty:
                    logger.warning(f"东方财富行业 {industry_name} 无历史数据")
                    return None
                result = pd.DataFrame()
                result['trade_date'] = df['日期'].astype(str).str.replace('-', '')
                result['open'] = df['开盘']
                result['high'] = df['最高']
                result['low'] = df['最低']
                result['close'] = df['收盘']
                result['volume'] = df['成交量']
                result['amount'] = df['成交额']
                logger.info(f"获取东方财富行业 {industry_name} 历史行情成功，共 {len(result)} 条")
                return result
            except Exception as e:
                logger.error(f"获取东方财富行业 {industry_name} 历史行情失败 (尝试 {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        return None
