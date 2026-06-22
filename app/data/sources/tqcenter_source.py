
"""
TqCenterSource - 基于通达信客户端 DLL 的数据源（仅 Windows 平台可用）

核心能力（对比 pytdx 直连 + akshare）：
1. 完整的板块列表（概念/行业/风格/地区），约 500+ 板块
2. 板块成分股映射（每只股票所属的板块）
3. 板块指数K线数据（行业/概念板块指数日线）
4. 股票基础信息、财务数据、资金流向等

注意：该模块依赖通达信客户端 + TPythClient.dll，仅在 Windows 环境可用。
非 Windows 环境下所有方法均返回 None，调用方应自行降级到其他数据源。
"""
import sys
import platform
import time
import pandas as pd
from typing import Optional, List, Dict, Tuple


_IS_WINDOWS = platform.system() == 'Windows'


class TqCenterSource:
    """通达信客户端数据源（TQ Python SDK 封装）"""

    # 板块类型映射（与 tqcenter 中 get_stock_list 的 list_type 参数对应）
    SECTOR_TYPE_CONCEPT = 12    # 概念板块
    SECTOR_TYPE_INDUSTRY = 11   # 行业板块
    SECTOR_TYPE_STYLE = 13      # 风格板块
    SECTOR_TYPE_REGION = 14     # 地区板块

    # 板块代码格式映射
    _block_code_cache: Dict[str, str] = {}

    @staticmethod
    def is_available() -> bool:
        """检查 TqCenter 是否可用"""
        if not _IS_WINDOWS:
            return False
        try:
            # 查找 tqcenter 模块（可能在 PYPlugins/sys 目录）
            import importlib
            importlib.util.find_spec('tqcenter')
            return True
        except (ImportError, ModuleNotFoundError):
            # 再尝试从 logs 目录导入
            try:
                import os
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs'))
                import importlib
                spec = importlib.util.find_spec('tqcenter')
                return spec is not None
            except Exception:
                return False
        except Exception:
            return False

    @staticmethod
    def _get_tq():
        """获取并初始化 tq 对象"""
        try:
            import tqcenter
            tq = tqcenter.tq
            # 初始化连接（如果尚未初始化）
            if not getattr(tq, '_initialized', False):
                try:
                    tq.initialize(__file__)
                except Exception:
                    # 如果 __file__ 不适用，尝试其他方式
                    try:
                        tq.initialize(sys.argv[0] if sys.argv else 'tqcenter')
                    except Exception:
                        pass
            return tq
        except Exception as e:
            print(f"  tqcenter 初始化失败: {e}")
            return None

    @staticmethod
    def get_concept_sectors() -> Optional[pd.DataFrame]:
        """
        获取概念板块列表（约 300-500 个）
        返回: DataFrame - block_name, block_code, source, stock_codes, stock_count
        """
        tq = TqCenterSource._get_tq()
        if tq is None:
            return None

        try:
            print("  [TqCenter] 获取概念板块列表...")
            block_list = tq.get_sector_list(list_type=TqCenterSource.SECTOR_TYPE_CONCEPT)
            if not block_list or len(block_list) == 0:
                print("  [TqCenter] 概念板块列表为空")
                return None

            rows = []
            for item in block_list:
                # tq 返回格式可能是 dict 或 list，兼容处理
                if isinstance(item, dict):
                    bname = item.get('BlockName') or item.get('block_name') or item.get('Name') or str(item)
                    bcode = item.get('BlockCode') or item.get('block_code') or item.get('Code') or ''
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    bcode = str(item[0])
                    bname = str(item[1])
                else:
                    bname = str(item)
                    bcode = ''

                if bname and bname.strip():
                    rows.append({
                        'block_name': bname.strip(),
                        'block_code': bcode.strip() if bcode else f'GN_{len(rows):04d}',
                        'source': '概念',
                        'stock_codes': [],
                        'stock_count': 0,
                    })

            df = pd.DataFrame(rows)
            print(f"  [TqCenter] 概念板块: {len(df)} 个")
            return df
        except Exception as e:
            print(f"  [TqCenter] 获取概念板块失败: {e}")
            return None

    @staticmethod
    def get_industry_sectors() -> Optional[pd.DataFrame]:
        """
        获取行业板块列表（约 80-120 个）
        返回: DataFrame - block_name, block_code, source, stock_codes, stock_count
        """
        tq = TqCenterSource._get_tq()
        if tq is None:
            return None

        try:
            print("  [TqCenter] 获取行业板块列表...")
            block_list = tq.get_sector_list(list_type=TqCenterSource.SECTOR_TYPE_INDUSTRY)
            if not block_list or len(block_list) == 0:
                print("  [TqCenter] 行业板块列表为空")
                return None

            rows = []
            for item in block_list:
                if isinstance(item, dict):
                    bname = item.get('BlockName') or item.get('block_name') or item.get('Name') or str(item)
                    bcode = item.get('BlockCode') or item.get('block_code') or item.get('Code') or ''
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    bcode = str(item[0])
                    bname = str(item[1])
                else:
                    bname = str(item)
                    bcode = ''

                if bname and bname.strip():
                    rows.append({
                        'block_name': bname.strip(),
                        'block_code': bcode.strip() if bcode else f'HY_{len(rows):04d}',
                        'source': '行业',
                        'stock_codes': [],
                        'stock_count': 0,
                    })

            df = pd.DataFrame(rows)
            print(f"  [TqCenter] 行业板块: {len(df)} 个")
            return df
        except Exception as e:
            print(f"  [TqCenter] 获取行业板块失败: {e}")
            return None

    @staticmethod
    def get_all_sectors(include_style: bool = False, include_region: bool = False) -> Optional[pd.DataFrame]:
        """
        获取全部板块（概念 + 行业，可选风格、地区）
        """
        concept_df = TqCenterSource.get_concept_sectors()
        industry_df = TqCenterSource.get_industry_sectors()

        all_dfs = []
        if concept_df is not None and len(concept_df) > 0:
            all_dfs.append(concept_df)
        if industry_df is not None and len(industry_df) > 0:
            all_dfs.append(industry_df)

        if include_style:
            style_df = TqCenterSource._get_sectors_by_type(TqCenterSource.SECTOR_TYPE_STYLE, '风格')
            if style_df is not None and len(style_df) > 0:
                all_dfs.append(style_df)

        if include_region:
            region_df = TqCenterSource._get_sectors_by_type(TqCenterSource.SECTOR_TYPE_REGION, '地区')
            if region_df is not None and len(region_df) > 0:
                all_dfs.append(region_df)

        if not all_dfs:
            return None

        result_df = pd.concat(all_dfs, ignore_index=True)
        result_df = result_df.drop_duplicates(subset=['block_name'], keep='first').reset_index(drop=True)
        print(f"  [TqCenter] 全部板块: {len(result_df)} 个")
        return result_df

    @staticmethod
    def _get_sectors_by_type(list_type: int, source_label: str) -> Optional[pd.DataFrame]:
        """通用的按类型获取板块方法"""
        tq = TqCenterSource._get_tq()
        if tq is None:
            return None

        try:
            block_list = tq.get_sector_list(list_type=list_type)
            if not block_list or len(block_list) == 0:
                return None

            rows = []
            for item in block_list:
                if isinstance(item, dict):
                    bname = item.get('BlockName') or item.get('block_name') or item.get('Name') or str(item)
                    bcode = item.get('BlockCode') or item.get('block_code') or item.get('Code') or ''
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    bcode = str(item[0])
                    bname = str(item[1])
                else:
                    bname = str(item)
                    bcode = ''

                if bname and bname.strip():
                    rows.append({
                        'block_name': bname.strip(),
                        'block_code': bcode.strip() if bcode else f'{source_label}_{len(rows):04d}',
                        'source': source_label,
                        'stock_codes': [],
                        'stock_count': 0,
                    })

            return pd.DataFrame(rows)
        except Exception as e:
            print(f"  [TqCenter] 获取{source_label}板块失败: {e}")
            return None

    @staticmethod
    def get_sector_stocks(block_name: str) -> List[str]:
        """
        获取板块成分股列表
        返回: 股票代码列表（如 ['600519.SH', '000858.SZ', ...]）
        """
        tq = TqCenterSource._get_tq()
        if tq is None:
            return []

        try:
            stocks = tq.get_stock_list_in_sector(block_name, block_type=0, list_type=1)
            if not stocks:
                return []

            # 格式化股票代码（tq 返回格式可能需要规范化）
            result = []
            for s in stocks:
                if isinstance(s, dict):
                    code = s.get('Code') or s.get('code') or s.get('stock_code') or ''
                    market = s.get('Market') or s.get('market') or ''
                    if code:
                        result.append(TqCenterSource._normalize_stock_code(code, market))
                elif isinstance(s, str):
                    result.append(TqCenterSource._normalize_stock_code(s))
                elif isinstance(s, (list, tuple)) and len(s) >= 1:
                    result.append(TqCenterSource._normalize_stock_code(str(s[0])))

            return [c for c in result if c]
        except Exception as e:
            print(f"  [TqCenter] 获取板块 {block_name} 成分股失败: {e}")
            return []

    @staticmethod
    def _normalize_stock_code(code: str, market: str = '') -> str:
        """
        规范化股票代码格式为 6位数+市场后缀
        输入: '600519' 或 '600519.SH' 或 '1#600519'
        输出: '600519.SH'
        """
        if not code:
            return ''
        code = code.strip()

        # 已有后缀格式
        if '.' in code and len(code.split('.')[0]) == 6:
            return code.upper()

        # 通达信市场#代码格式
        if '#' in code:
            parts = code.split('#')
            if len(parts) >= 2 and len(parts[1]) == 6:
                market_flag = parts[0]
                pure_code = parts[1]
                suffix = '.SH' if market_flag == '1' else '.SZ' if market_flag == '0' else '.BJ'
                return f'{pure_code}{suffix}'

        # 纯6位数字代码
        if len(code) == 6 and code.isdigit():
            # 6开头=上海，0/3开头=深圳，8/4开头=北交所
            if code.startswith('6') or code.startswith('9'):
                return f'{code}.SH'
            elif code.startswith('0') or code.startswith('3'):
                return f'{code}.SZ'
            elif code.startswith('8') or code.startswith('4'):
                return f'{code}.BJ'
            return f'{code}.SH'

        # market 参数辅助判断
        if market:
            market = str(market)
            if market in ('1', 'SH', 'sh', '上海'):
                return f'{code}.SH'
            elif market in ('0', 'SZ', 'sz', '深圳'):
                return f'{code}.SZ'
            elif market in ('2', 'BJ', 'bj', '北交所'):
                return f'{code}.BJ'

        return code

    @staticmethod
    def get_sector_daily(block_name: str, block_code: str = '',
                         start_date: str = '', end_date: str = '',
                         max_count: int = 5000) -> Optional[pd.DataFrame]:
        """
        获取板块日线K线数据
        Args:
            block_name: 板块名称（优先用名称查找）
            block_code: 板块代码（如 880660，备用）
            start_date: 起始日期 YYYYMMDD（可选）
            end_date: 结束日期 YYYYMMDD（可选）
            max_count: 最大数据条数
        返回: DataFrame - trade_date, open, high, low, close, volume, amount
        """
        tq = TqCenterSource._get_tq()
        if tq is None:
            return None

        try:
            # 优先用板块代码（880XXX 指数）获取K线
            # 注意：tq 的 get_market_data 需要标准股票代码格式
            query_code = ''
            if block_code and len(block_code) == 6 and block_code.isdigit():
                # 板块指数通常用 .SH 后缀
                query_code = f'{block_code}.SH'
            elif block_code:
                query_code = block_code

            if not query_code:
                # 无代码，无法获取K线（tqcenter 需要代码获取K线）
                return None

            try:
                data_dict = tq.get_market_data(
                    stock_list=[query_code],
                    period='1d',
                    start_time=start_date if start_date else '',
                    end_time=end_date if end_date else '',
                    count=max_count,
                    dividend_type='none',
                    fill_data=False,
                )
            except Exception as inner_e:
                # 如果 .SH 不行，尝试不带后缀
                try:
                    data_dict = tq.get_market_data(
                        stock_list=[block_code],
                        period='1d',
                        start_time=start_date if start_date else '',
                        end_time=end_date if end_date else '',
                        count=max_count,
                        dividend_type='none',
                        fill_data=False,
                    )
                except Exception:
                    return None

            if not data_dict or query_code not in data_dict:
                # 尝试直接用板块名获取成分股聚合后的指数
                # （tq 某些版本支持按板块名取指数）
                try:
                    alt_codes = [f'88{block_code[-4:]}.SH' if block_code.isdigit() else block_code]
                    for alt_code in alt_codes:
                        try:
                            data_dict = tq.get_market_data(
                                stock_list=[alt_code],
                                period='1d',
                                count=max_count,
                                dividend_type='none',
                            )
                            if data_dict and alt_code in data_dict:
                                query_code = alt_code
                                break
                        except Exception:
                            continue
                    if not data_dict or query_code not in data_dict:
                        return None
                except Exception:
                    return None

            # 解析返回数据
            df_raw = data_dict.get(query_code)
            if df_raw is None or (isinstance(df_raw, pd.DataFrame) and df_raw.empty):
                return None

            # 解析 DataFrame（tq 返回格式可能有差异，统一处理）
            if isinstance(df_raw, pd.DataFrame):
                df = df_raw.copy()
                # 列名映射
                col_map = {
                    'Date': 'trade_date', 'date': 'trade_date', '日期': 'trade_date',
                    'Open': 'open', 'open': 'open', '开盘': 'open', '开盘价': 'open',
                    'High': 'high', 'high': 'high', '最高': 'high', '最高价': 'high',
                    'Low': 'low', 'low': 'low', '最低': 'low', '最低价': 'low',
                    'Close': 'close', 'close': 'close', '收盘': 'close', '收盘价': 'close',
                    'Volume': 'volume', 'volume': 'volume', '成交量': 'volume',
                    'Amount': 'amount', 'amount': 'amount', '成交额': 'amount',
                }
                df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

                required_cols = ['trade_date', 'open', 'high', 'low', 'close']
                if not all(c in df.columns for c in required_cols):
                    # 尝试按索引解析
                    if df.index.name == 'date' or df.index.name == 'Date' or isinstance(df.index, pd.DatetimeIndex):
                        df = df.reset_index()
                        df = df.rename(columns={df.columns[0]: 'trade_date'})
                        # 重新检查
                        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

                if 'trade_date' not in df.columns:
                    return None

                # 确保 volume/amount 存在（缺失则补0）
                for col in ['volume', 'amount']:
                    if col not in df.columns:
                        df[col] = 0.0

                # 格式化日期
                df['trade_date'] = df['trade_date'].apply(
                    lambda x: x.strftime('%Y%m%d') if hasattr(x, 'strftime')
                    else str(x).replace('-', '').replace('/', '').replace('.', '')[:8]
                )

                # 过滤日期范围
                if start_date:
                    df = df[df['trade_date'] >= start_date]
                if end_date:
                    df = df[df['trade_date'] <= end_date]

                df = df.sort_values('trade_date').reset_index(drop=True)
                return df[['trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount']]

            return None

        except Exception as e:
            print(f"  [TqCenter] 获取板块 {block_name}({block_code}) 日线失败: {e}")
            return None

    @staticmethod
    def get_stock_basics() -> Optional[pd.DataFrame]:
        """
        获取 A 股股票列表
        返回: DataFrame - stock_code, stock_name, market, list_date
        """
        tq = TqCenterSource._get_tq()
        if tq is None:
            return None

        try:
            print("  [TqCenter] 获取股票列表...")
            # list_type=5: 所有A股
            stock_list = tq.get_stock_list('SH', list_type=5)
            if not stock_list or len(stock_list) == 0:
                # 再尝试深圳
                stock_list = tq.get_stock_list('SZ', list_type=5)
            if not stock_list or len(stock_list) == 0:
                return None

            rows = []
            for item in stock_list:
                if isinstance(item, dict):
                    code = item.get('Code') or item.get('code') or item.get('stock_code') or ''
                    name = item.get('Name') or item.get('name') or item.get('stock_name') or ''
                    market = str(item.get('Market') or item.get('market') or '')
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    code = str(item[0])
                    name = str(item[1])
                    market = str(item[2]) if len(item) > 2 else ''
                else:
                    continue

                if code:
                    normalized = TqCenterSource._normalize_stock_code(code, market)
                    if '.' in normalized:
                        pure_code = normalized.split('.')[0]
                        market_suffix = normalized.split('.')[1]
                        rows.append({
                            'stock_code': pure_code,
                            'stock_name': name,
                            'market': market_suffix,
                            'is_st': 'ST' in name,
                            'suspend': False,
                        })

            df = pd.DataFrame(rows)
            df = df.drop_duplicates(subset=['stock_code'], keep='first').reset_index(drop=True)
            print(f"  [TqCenter] 股票列表: {len(df)} 只")
            return df
        except Exception as e:
            print(f"  [TqCenter] 获取股票列表失败: {e}")
            return None

    @staticmethod
    def get_stock_daily(stock_code: str, start_date: str = '',
                        end_date: str = '', max_count: int = 5000) -> Tuple[Optional[pd.DataFrame], str]:
        """
        获取股票日线K线
        返回: (DataFrame, 数据源标记)
        """
        tq = TqCenterSource._get_tq()
        if tq is None:
            return None, 'tqcenter_unavailable'

        try:
            # 规范化股票代码（确保有后缀）
            if '.' not in stock_code:
                normalized = TqCenterSource._normalize_stock_code(stock_code)
            else:
                normalized = stock_code.upper()

            data_dict = tq.get_market_data(
                stock_list=[normalized],
                period='1d',
                start_time=start_date,
                end_time=end_date,
                count=max_count,
                dividend_type='front',  # 前复权
                fill_data=True,
            )

            if not data_dict or normalized not in data_dict:
                return None, 'tqcenter_no_data'

            df_raw = data_dict[normalized]
            if not isinstance(df_raw, pd.DataFrame) or df_raw.empty:
                return None, 'tqcenter_empty'

            # 列名映射
            df = df_raw.copy()
            col_map = {
                'Date': 'trade_date', 'date': 'trade_date', '日期': 'trade_date',
                'Open': 'open', 'open': 'open',
                'High': 'high', 'high': 'high',
                'Low': 'low', 'low': 'low',
                'Close': 'close', 'close': 'close',
                'Volume': 'volume', 'volume': 'volume', '成交量': 'volume',
                'Amount': 'amount', 'amount': 'amount', '成交额': 'amount',
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

            if 'trade_date' not in df.columns:
                if isinstance(df.index, pd.DatetimeIndex) or df.index.name in ('date', 'Date'):
                    df = df.reset_index()
                    df = df.rename(columns={df.columns[0]: 'trade_date'})
                else:
                    return None, 'tqcenter_bad_format'

            # 日期格式化
            df['trade_date'] = df['trade_date'].apply(
                lambda x: x.strftime('%Y%m%d') if hasattr(x, 'strftime')
                else str(x).replace('-', '').replace('/', '').replace('.', '')[:8]
            )

            # 确保 volume/amount
            for col in ['volume', 'amount']:
                if col not in df.columns:
                    df[col] = 0.0

            if start_date:
                df = df[df['trade_date'] >= start_date]
            if end_date:
                df = df[df['trade_date'] <= end_date]

            df = df.sort_values('trade_date').reset_index(drop=True)
            return df[['trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount']], 'tqcenter'

        except Exception as e:
            print(f"  [TqCenter] 获取股票 {stock_code} 日线失败: {e}")
            return None, f'tqcenter_error:{str(e)[:30]}'

    @staticmethod
    def close():
        """断开 tqcenter 连接"""
        try:
            import tqcenter
            tqcenter.tq.close()
        except Exception:
            pass
