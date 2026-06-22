"""
统一 code 格式迁移脚本
- 指数: sh000001 → 000001, sz399006 → 399006 (纯数字, market 字段存市场)
- 板块: SECTOR_xxx → xxx (纯板块名)
"""
import sys
sys.path.insert(0, '.')

from app.data.db import get_db
from pymongo import UpdateOne


def migrate_index_basics(db):
    """index_basics: sh/sz 前缀 → 纯数字"""
    docs = list(db['index_basics'].find({}))
    ops = []
    for doc in docs:
        old_code = doc['code']
        if old_code.startswith('sh'):
            new_code = old_code[2:]
            market = 1
        elif old_code.startswith('sz'):
            new_code = old_code[2:]
            market = 0
        else:
            new_code = old_code
            market = doc.get('market', 1)

        tdx_code = doc.get('tdx_code', new_code)
        if tdx_code.startswith('sh') or tdx_code.startswith('sz'):
            tdx_code = tdx_code[2:]

        if new_code != old_code:
            ops.append(UpdateOne(
                {'_id': doc['_id']},
                {'$set': {
                    'code': new_code,
                    'market': market,
                    'tdx_code': tdx_code,
                }}
            ))
            print(f'  index_basics: {old_code} → {new_code} (market={market})')

    if ops:
        db['index_basics'].bulk_write(ops, ordered=False)
    print(f'  index_basics 迁移完成: {len(ops)} 条更新')


def migrate_daily_data_index(db):
    """daily_data 中指数: sh/sz 前缀 → 纯数字"""
    index_codes = list(db['daily_data'].distinct('stock_code', {'data_type': 'index'}))
    ops = []
    for old_code in index_codes:
        if old_code.startswith('sh'):
            new_code = old_code[2:]
        elif old_code.startswith('sz'):
            new_code = old_code[2:]
        elif old_code == 'avg_price':
            new_code = '880003'
        else:
            new_code = old_code

        if new_code != old_code:
            ops.append(UpdateOne(
                {'stock_code': old_code, 'data_type': 'index'},
                {'$set': {'stock_code': new_code}},
                upsert=False
            ))
            count = db['daily_data'].count_documents({'stock_code': old_code, 'data_type': 'index'})
            print(f'  daily_data 指数: {old_code} → {new_code} ({count} 条)')

    if ops:
        for old_code in index_codes:
            if old_code.startswith('sh') or old_code.startswith('sz') or old_code == 'avg_price':
                if old_code.startswith('sh'):
                    new_code = old_code[2:]
                elif old_code.startswith('sz'):
                    new_code = old_code[2:]
                else:
                    new_code = '880003'
                if new_code != old_code:
                    result = db['daily_data'].update_many(
                        {'stock_code': old_code, 'data_type': 'index'},
                        {'$set': {'stock_code': new_code}}
                    )
                    print(f'  daily_data 更新 {old_code} → {new_code}: {result.modified_count} 条')

    print(f'  daily_data 指数迁移完成')


def migrate_sector_basics(db):
    """sector_basics: SECTOR_xxx → xxx"""
    docs = list(db['sector_basics'].find({}))
    ops = []
    for doc in docs:
        old_code = doc['code']
        if old_code.startswith('SECTOR_'):
            new_code = old_code[7:]
            ops.append(UpdateOne(
                {'_id': doc['_id']},
                {'$set': {'code': new_code}}
            ))

    if ops:
        db['sector_basics'].bulk_write(ops, ordered=False)
    print(f'  sector_basics 迁移完成: {len(ops)} 条更新')


def migrate_daily_data_sector(db):
    """daily_data 中板块: SECTOR_xxx → xxx"""
    sector_codes = list(db['daily_data'].distinct('stock_code', {'data_type': 'sector'}))
    updated = 0
    for old_code in sector_codes:
        if old_code.startswith('SECTOR_'):
            new_code = old_code[7:]
            result = db['daily_data'].update_many(
                {'stock_code': old_code, 'data_type': 'sector'},
                {'$set': {'stock_code': new_code}}
            )
            updated += result.modified_count
    print(f'  daily_data 板块迁移完成: {updated} 条更新')


def migrate_sector_stock_codes(db):
    """sector_basics 中的 stock_codes 字段保持不变（个股代码已经是纯数字）"""
    print(f'  sector_basics stock_codes 无需迁移（已是纯数字）')


def migrate_exclusions(db):
    """exclusions: sh/sz/SECTOR_ 前缀 → 纯数字"""
    docs = list(db['exclusions'].find({}))
    ops = []
    for doc in docs:
        old_code = doc['code']
        new_code = old_code
        if old_code.startswith('sh'):
            new_code = old_code[2:]
        elif old_code.startswith('sz'):
            new_code = old_code[2:]
        elif old_code.startswith('SECTOR_'):
            new_code = old_code[7:]

        if new_code != old_code:
            ops.append(UpdateOne(
                {'_id': doc['_id']},
                {'$set': {'code': new_code}}
            ))
            print(f'  exclusions: {old_code} → {new_code}')

    if ops:
        db['exclusions'].bulk_write(ops, ordered=False)
    print(f'  exclusions 迁移完成: {len(ops)} 条更新')


def main():
    db = get_db()

    print('=== 迁移 index_basics ===')
    migrate_index_basics(db)

    print('\n=== 迁移 daily_data (指数) ===')
    migrate_daily_data_index(db)

    print('\n=== 迁移 sector_basics ===')
    migrate_sector_basics(db)

    print('\n=== 迁移 daily_data (板块) ===')
    migrate_daily_data_sector(db)

    print('\n=== 迁移 exclusions ===')
    migrate_exclusions(db)

    print('\n=== 迁移完成 ===')


if __name__ == '__main__':
    main()
