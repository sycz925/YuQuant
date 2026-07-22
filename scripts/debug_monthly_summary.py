"""
调试脚本：检查指定月份的周总结数据状态
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.db import get_db

TARGET_YEAR = 2026
TARGET_MONTH = 6


def main():
    db = get_db()

    print(f"=" * 60)
    print(f"检查 {TARGET_YEAR}年{TARGET_MONTH:02d}月 周总结数据")
    print(f"=" * 60)

    # 1. 查询 weekly_summary 集合中的所有文档
    week_docs = list(db['weekly_summary'].find(
        {'year': TARGET_YEAR, 'month': TARGET_MONTH},
        {'_id': 0}
    ).sort('week_index', 1))

    print(f"\n找到 {len(week_docs)} 条周总结记录:")
    for doc in week_docs:
        print(f"  - 第{doc.get('week_index')}周: dates={doc.get('dates')}, summary长度={len(doc.get('summary', ''))}字符")

    # 2. 检查 market_daily 中的 ai_analysis 状态
    print(f"\n检查 market_daily 中的 ai_analysis 状态:")
    import calendar as cal
    days_in_month = cal.monthrange(TARGET_YEAR, TARGET_MONTH)[1]

    for day in range(1, days_in_month + 1):
        date_str = f"{TARGET_YEAR}{TARGET_MONTH:02d}{day:02d}"
        market_doc = db['market_daily'].find_one(
            {'trade_date': date_str},
            {'_id': 0, 'ai_analysis': 1}
        )
        if market_doc:
            ai = market_doc.get('ai_analysis')
            has_diagnosis = ai and ai.get('market_phase_diagnosis') if ai else False
            source = ai.get('source', 'N/A') if ai else 'N/A'
            print(f"  {date_str}: has_ai_analysis={bool(ai)}, has_diagnosis={has_diagnosis}, source={source}")
        else:
            print(f"  {date_str}: 无 market_daily 记录")

    # 3. 检查 weekly_summary 集合的所有索引
    print(f"\nweekly_summary 集合索引:")
    for idx in db['weekly_summary'].list_indexes():
        print(f"  {idx['key']}")


if __name__ == '__main__':
    main()
