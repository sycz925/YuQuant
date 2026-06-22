"""
数据迁移脚本：从 SQLite + HDF5 迁移到 MongoDB
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
from app.data.db import (
    get_db, bulk_upsert_stock_basics, bulk_upsert_daily_data,
    upsert_index_basics
)


def migrate_stock_basics():
    """迁移股票基础信息"""
    import sqlite3

    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                           'data', 'sqlite', 'quant.db')

    if not os.path.exists(db_path):
        print("旧 SQLite 数据库不存在，跳过股票基础信息迁移")
        return 0

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT stock_code, stock_name, market, list_date, delist_date, is_st, suspend FROM stock_basics')
        rows = cursor.fetchall()

        docs = []
        for row in rows:
            doc = {
                'stock_code': row[0],
                'stock_name': row[1],
                'market': row[2],
                'list_date': row[3],
                'delist_date': row[4],
                'is_st': bool(row[5]) if row[5] is not None else False,
                'suspend': bool(row[6]) if row[6] is not None else False
            }
            docs.append(doc)

        if docs:
            bulk_upsert_stock_basics(docs)
            print(f"迁移股票基础信息: {len(docs)} 条")
            return len(docs)
        return 0
    except Exception as e:
        print(f"迁移股票基础信息失败: {e}")
        return 0
    finally:
        conn.close()


def migrate_index_basics():
    """迁移指数基础信息"""
    import sqlite3

    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                           'data', 'sqlite', 'quant.db')

    if not os.path.exists(db_path):
        print("旧 SQLite 数据库不存在，添加默认指数")
        # 添加默认指数
        indexes = [
            ('000001', '上证指数', 'SH'),
            ('399001', '深证成指', 'SZ'),
            ('000300', '沪深300', 'SH'),
            ('000905', '中证500', 'SH')
        ]
        for code, name, market in indexes:
            upsert_index_basics(code, name, market)
        return len(indexes)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT index_code, index_name, market FROM index_basics')
        rows = cursor.fetchall()

        count = 0
        for row in rows:
            upsert_index_basics(row[0], row[1], row[2])
            count += 1

        print(f"迁移指数基础信息: {count} 条")
        return count
    except Exception as e:
        print(f"迁移指数基础信息失败: {e}")
        return 0
    finally:
        conn.close()


def migrate_daily_data():
    """迁移日线数据"""
    import h5py
    import pandas as pd

    hdf5_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                             'data', 'hdf5', 'daily_data.h5')

    if not os.path.exists(hdf5_path):
        print("旧 HDF5 文件不存在，跳过日线数据迁移")
        return 0

    try:
        total_count = 0

        with h5py.File(hdf5_path, 'r') as f:
            if '/daily' not in f:
                print("HDF5 中没有日线数据")
                return 0

            daily_group = f['/daily']

            for stock_code in daily_group.keys():
                subgroup = daily_group[stock_code]

                # 读取数据
                data = {}
                for col in subgroup.keys():
                    data[col] = subgroup[col][:]

                df = pd.DataFrame(data)

                if 'index' in df.columns:
                    df['trade_date'] = df['index'].astype(str)
                else:
                    continue

                # 构建记录列表
                records = []
                for _, row in df.iterrows():
                    record = {
                        'trade_date': str(row['trade_date']),
                        'open': float(row['open']) if pd.notna(row['open']) else None,
                        'high': float(row['high']) if pd.notna(row['high']) else None,
                        'low': float(row['low']) if pd.notna(row['low']) else None,
                        'close': float(row['close']) if pd.notna(row['close']) else None,
                        'volume': float(row['volume']) if pd.notna(row['volume']) else None,
                        'amount': float(row['amount']) if pd.notna(row['amount']) else None,
                        'change_pct': float(row['change_pct']) if 'change_pct' in row and pd.notna(row['change_pct']) else None,
                        'change': float(row['change']) if 'change' in row and pd.notna(row['change']) else None,
                        'amplitude': float(row['amplitude']) if 'amplitude' in row and pd.notna(row['amplitude']) else None,
                        'turnover': float(row['turnover']) if 'turnover' in row and pd.notna(row['turnover']) else None
                    }
                    records.append(record)

                if records:
                    bulk_upsert_daily_data(stock_code, records, 'migrated')
                    total_count += len(records)

        print(f"迁移日线数据: {total_count} 条")
        return total_count
    except Exception as e:
        print(f"迁移日线数据失败: {e}")
        return 0


def verify_migration():
    """验证迁移结果"""
    print("\n=== 验证迁移结果 ===")

    db = get_db()

    stock_count = db['stock_basics'].count_documents({})
    index_count = db['index_basics'].count_documents({})
    universe_count = db['stock_universe'].count_documents({})
    daily_count = db['daily_data'].count_documents({})

    print(f"股票基础信息: {stock_count} 条")
    print(f"指数基础信息: {index_count} 条")
    print(f"日线数据记录: {daily_count} 条")

    # 检查峰岹科技数据
    fengtiao_count = db['daily_data'].count_documents({'stock_code': '688279'})
    print(f"峰岹科技日线数据: {fengtiao_count} 条")

    if fengtiao_count > 0:
        sample = db['daily_data'].find_one({'stock_code': '688279'}, sort=[('trade_date', -1)])
        print(f"最新一条峰岹科技数据: {sample.get('trade_date')}, 收盘价: {sample.get('close')}")


def run_migration():
    """运行完整迁移"""
    print("=== 开始数据迁移 ===\n")

    # 确保索引存在
    get_db()

    stock_count = migrate_stock_basics()
    index_count = migrate_index_basics()
    daily_count = migrate_daily_data()

    print("\n=== 迁移完成 ===")
    print(f"股票基础信息: {stock_count}")
    print(f"指数基础信息: {index_count}")
    print(f"日线数据: {daily_count}")

    verify_migration()


if __name__ == '__main__':
    run_migration()
