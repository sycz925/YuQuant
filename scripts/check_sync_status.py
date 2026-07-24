#!/usr/bin/env python3
"""
检查数据同步状态脚本
"""
import os
import sys
from datetime import datetime, timedelta
from pymongo import MongoClient
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def check_sync_status():
    """检查数据同步状态"""
    # 连接数据库
    mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
    db_name = os.getenv('MONGODB_DB_NAME', 'yuquant')
    
    try:
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, socketTimeoutMS=5000)
        # 测试连接
        client.admin.command('ping')
        db = client[db_name]
    except Exception as e:
        print(f"数据库连接失败: {e}")
        print("请确保MongoDB服务正在运行")
        return
    
    print("=" * 60)
    print(f"数据同步状态检查 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 1. 检查股票基础信息
    print("\n1. 股票基础信息统计:")
    total_stocks = db['stock_basics'].count_documents({})
    enabled_stocks = db['stock_basics'].count_documents({'is_disable': {'$ne': True}})
    disabled_stocks = db['stock_basics'].count_documents({'is_disable': True})
    
    print(f"   总股票数: {total_stocks}")
    print(f"   启用股票数: {enabled_stocks}")
    print(f"   禁用股票数: {disabled_stocks}")
    
    # 2. 检查日线数据同步状态
    print("\n2. 日线数据同步状态:")
    
    # 获取今天日期
    today = datetime.now().strftime('%Y%m%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    
    # 检查个股日线数据
    stock_daily_count = db['stock_daily'].count_documents({})
    stock_today_count = db['stock_daily'].count_documents({'trade_date': today})
    stock_yesterday_count = db['stock_daily'].count_documents({'trade_date': yesterday})
    stock_today_final_count = db['stock_daily'].count_documents({'trade_date': today, 'is_final': True})
    
    print(f"   个股日线总记录数: {stock_daily_count}")
    print(f"   今日({today})记录数: {stock_today_count}")
    print(f"   今日已收盘(is_final=True)记录数: {stock_today_final_count}")
    print(f"   昨日({yesterday})记录数: {stock_yesterday_count}")
    
    # 检查板块日线数据
    sector_daily_count = db['sector_daily'].count_documents({})
    sector_today_count = db['sector_daily'].count_documents({'trade_date': today})
    sector_yesterday_count = db['sector_daily'].count_documents({'trade_date': yesterday})
    
    print(f"\n   板块日线总记录数: {sector_daily_count}")
    print(f"   今日({today})记录数: {sector_today_count}")
    print(f"   昨日({yesterday})记录数: {sector_yesterday_count}")
    
    # 检查指数日线数据
    index_daily_count = db['index_daily'].count_documents({})
    index_today_count = db['index_daily'].count_documents({'trade_date': today})
    
    print(f"\n   指数日线总记录数: {index_daily_count}")
    print(f"   今日({today})记录数: {index_today_count}")
    
    # 3. 检查数据源统计
    print("\n3. 数据源统计:")
    pipeline = [
        {'$group': {'_id': '$data_source', 'count': {'$sum': 1}}}
    ]
    source_stats = list(db['stock_daily'].aggregate(pipeline))
    
    for stat in source_stats:
        source = stat['_id'] or 'unknown'
        count = stat['count']
        print(f"   {source}: {count} 条")
    
    # 4. 检查同步时间窗口
    print("\n4. 同步时间窗口:")
    now = datetime.now()
    hour, minute = now.hour, now.minute
    t = hour * 60 + minute
    
    if 690 <= t < 780:  # 11:30 - 13:00
        print("   当前状态: 盘中同步窗口 (11:30-13:00)")
    elif 900 <= t <= 1439:  # 15:00 - 23:59
        print("   当前状态: 盘后同步窗口 (15:00-24:00)")
    else:
        print("   当前状态: 非同步时间")
    
    # 5. 检查启用的股票最新数据日期
    print("\n5. 启用股票最新数据日期:")
    enabled_codes = [
        doc['stock_code'] for doc in db['stock_basics'].find(
            {'is_disable': {'$ne': True}},
            {'_id': 0, 'stock_code': 1}
        )
    ]
    
    if enabled_codes:
        # 随机抽样几个股票检查
        sample_size = min(10, len(enabled_codes))
        sample_codes = enabled_codes[:sample_size]
        
        for code in sample_codes:
            latest = db['stock_daily'].find_one(
                {'stock_code': code},
                sort=[('trade_date', -1)],
                projection={'trade_date': 1, 'is_final': 1, '_id': 0}
            )
            if latest:
                status = "已收盘" if latest.get('is_final') else "盘中数据"
                print(f"   {code}: {latest['trade_date']} ({status})")
            else:
                print(f"   {code}: 无数据")
    
    # 6. 检查是否有未完成的同步任务
    print("\n6. 同步任务状态:")
    if 'tasks' in db.list_collection_names():
        pending_tasks = db['tasks'].count_documents({'status': 'in_progress'})
        completed_tasks = db['tasks'].count_documents({'status': 'completed'})
        failed_tasks = db['tasks'].count_documents({'status': 'failed'})
        
        print(f"   进行中任务: {pending_tasks}")
        print(f"   已完成任务: {completed_tasks}")
        print(f"   失败任务: {failed_tasks}")
    else:
        print("   无任务集合")
    
    print("\n" + "=" * 60)
    print("检查完成")
    print("=" * 60)

if __name__ == '__main__':
    check_sync_status()