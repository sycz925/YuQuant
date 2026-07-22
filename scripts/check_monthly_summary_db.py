"""
检查月总结是否已保存到数据库
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.db import get_db

TARGET_YEAR = 2026
TARGET_MONTH = 6


def main():
    db = get_db()

    print(f"检查 {TARGET_YEAR}年{TARGET_MONTH:02d}月 月总结数据库记录")
    print("=" * 60)

    # 查询 monthly_summary 集合
    doc = db['monthly_summary'].find_one(
        {'year': TARGET_YEAR, 'month': TARGET_MONTH},
        {'_id': 0}
    )

    if doc:
        print(f"\n找到月总结记录:")
        print(f"  - 生成时间: {doc.get('generated_at')}")
        print(f"  - 周数: {doc.get('week_count')}")
        print(f"  - 内容长度: {len(doc.get('summary', ''))} 字符")
        print(f"\n内容预览 (前500字符):")
        print("-" * 60)
        print(doc.get('summary', '')[:500])
        print("-" * 60)
    else:
        print("\n未找到月总结记录")

    # 列出所有月总结记录
    print(f"\n\n所有月总结记录:")
    for doc in db['monthly_summary'].find({}, {'_id': 0, 'year': 1, 'month': 1, 'generated_at': 1}):
        print(f"  - {doc.get('year')}-{doc.get('month'):02d}: {doc.get('generated_at')}")


if __name__ == '__main__':
    main()
