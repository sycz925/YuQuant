"""
东方财富（AkShare）行情数据源
"""
from typing import Optional, Tuple
import time
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class AkShareSource:
    """AkShare 数据源封装（东方财富接口）"""

    @staticmethod
    def _to_em_df(df, code: str) -> Optional[pd.DataFrame]:
        """将 AkShare 东方财富日线 DataFrame 转为统一格式"""
        if df is None or df.empty:
            return None
        result = pd.DataFrame()
        result['trade_date'] = df['日期'].astype(str).str.replace('-', '')
        result['open'] = df['开盘']
        result['high'] = df['最高']
        result['low'] = df['最低']
        result['close'] = df['收盘']
        result['vol'] = df['成交量']
        result['amount'] = df['成交额']
        if '涨跌幅' in df.columns:
            result['change_pct'] = df['涨跌幅']
        if '涨跌额' in df.columns:
            result['change'] = df['涨跌额']
        if '振幅' in df.columns:
            result['amplitude'] = df['振幅']
        if '换手率' in df.columns:
            result['turnover'] = df['换手率']
        return result

    @staticmethod
    def get_etf_daily(code: str, start_date: str, end_date: str) -> Tuple[Optional[pd.DataFrame], str]:
        """获取ETF日线（东方财富 ETF 历史行情）"""
        import akshare as ak
        for attempt in range(3):
            try:
                df = ak.fund_etf_hist_em(
                    symbol=code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="qfq"
                )
                result = AkShareSource._to_em_df(df, code)
                if result is not None:
                    return result, 'akshare_etf'
            except Exception as e:
                logger.warning(f"AkShare ETF获取失败 {code} (尝试 {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
        return None, ''

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
                    time.sleep(3 * (attempt + 1))
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
                result = AkShareSource._to_em_df(df, stock_code)
                if result is not None:
                    return result, 'akshare'
            except Exception as e:
                print(f"AkShare 获取数据失败 {stock_code} (尝试 {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
        return None, ''

    @staticmethod
    def get_industry_list() -> Optional[pd.DataFrame]:
        """获取东方财富行业板块列表"""
        import akshare as ak
        try:
            df = ak.stock_board_industry_name_em()
            if df.empty:
                logger.warning("东方财富行业板块列表为空")
                return None
            return df[['板块名称', '板块代码']].copy()
        except Exception as e:
            logger.error(f"获取东方财富行业板块列表失败: {e}")
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

    @staticmethod
    def get_concept_hist(concept_name: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        获取东方财富概念板块历史行情（作为通达信 pytdx 的回退数据源）
        :param concept_name: 概念板块名称，如 "锂电池"
        :param start_date: 开始日期 YYYYMMDD
        :param end_date: 结束日期 YYYYMMDD
        :return: DataFrame with columns [trade_date, open, high, low, close, volume, amount]
        """
        import akshare as ak
        sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
        for attempt in range(3):
            try:
                df = ak.stock_board_concept_hist_em(
                    symbol=concept_name,
                    start_date=sd,
                    end_date=ed,
                    period="日k",
                    adjust=""
                )
                if df.empty:
                    logger.warning(f"东方财富概念 {concept_name} 无历史数据")
                    return None
                result = pd.DataFrame()
                result['trade_date'] = df['日期'].astype(str).str.replace('-', '')
                result['open'] = df['开盘']
                result['high'] = df['最高']
                result['low'] = df['最低']
                result['close'] = df['收盘']
                result['volume'] = df['成交量']
                result['amount'] = df['成交额']
                logger.info(f"获取东方财富概念 {concept_name} 历史行情成功，共 {len(result)} 条")
                return result
            except Exception as e:
                logger.warning(f"获取东方财富概念 {concept_name} 历史行情失败 (尝试 {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        return None
