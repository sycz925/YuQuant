"""
BaoStock 数据源封装
"""
import time
import pandas as pd
from typing import Optional, Tuple


class BaoStockSource:
    @staticmethod
    def to_baostock_code(stock_code: str) -> str:
        """转换为 BaoStock 格式的代码"""
        if stock_code.startswith('6'):
            return f"sh.{stock_code}"
        else:
            return f"sz.{stock_code}"

    @staticmethod
    def get_stock_basics() -> Optional[pd.DataFrame]:
        """获取股票基础信息"""
        import baostock as bs
        lg = bs.login()
        if lg.error_code != '0':
            print(f"BaoStock 登录失败: {lg.error_msg}")
            return None

        try:
            rs = bs.query_all_stock(day="")
            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())
            df = pd.DataFrame(data_list, columns=rs.fields)

            if not df.empty:
                df['stock_code'] = df['code'].apply(lambda x: x.split('.')[1])
                df['stock_name'] = df['code_name']
                df['market'] = df['code'].apply(lambda x: 'SH' if x.startswith('sh') else 'SZ')
                df['list_date'] = df.get('ipoDate', None)
                return df[['stock_code', 'stock_name', 'market', 'list_date']]
        except Exception as e:
            print(f"BaoStock 获取股票列表失败: {e}")
        finally:
            bs.logout()
        return None

    @staticmethod
    def get_daily_data(stock_code: str, start_date: str, end_date: str) -> Tuple[Optional[pd.DataFrame], str]:
        """
        获取日线行情数据
        返回: (DataFrame, data_source)
        """
        import baostock as bs
        bs_code = BaoStockSource.to_baostock_code(stock_code)

        # 转换日期格式 YYYYMMDD -> YYYY-MM-DD
        s_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}" if len(start_date) == 8 else start_date
        e_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if len(end_date) == 8 else end_date

        lg = bs.login()
        if lg.error_code != '0':
            print(f"BaoStock 登录失败: {lg.error_msg}")
            return None, ''

        try:
            for attempt in range(2):
                try:
                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        "date,open,high,low,close,volume,amount,pctChg",
                        start_date=s_date,
                        end_date=e_date,
                        frequency="d",
                        adjustflag="3"
                    )
                    data_list = []
                    while (rs.error_code == '0') & rs.next():
                        data_list.append(rs.get_row_data())
                    df = pd.DataFrame(data_list, columns=rs.fields)

                    if not df.empty:
                        # 字段映射
                        result_df = pd.DataFrame()
                        result_df['trade_date'] = df['date'].str.replace('-', '')
                        result_df['open'] = pd.to_numeric(df['open'], errors='coerce')
                        result_df['high'] = pd.to_numeric(df['high'], errors='coerce')
                        result_df['low'] = pd.to_numeric(df['low'], errors='coerce')
                        result_df['close'] = pd.to_numeric(df['close'], errors='coerce')
                        result_df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
                        result_df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
                        if 'pctChg' in df.columns:
                            result_df['change_pct'] = pd.to_numeric(df['pctChg'], errors='coerce')
                        return result_df, 'baostock'
                except Exception as e:
                    print(f"BaoStock 获取数据失败 {stock_code} (尝试 {attempt + 1}/2): {e}")
                    if attempt < 1:
                        time.sleep(1)
        finally:
            bs.logout()
        return None, ''
