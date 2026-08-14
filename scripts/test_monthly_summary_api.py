"""
测试脚本：实际调用 DeepSeek API 生成月总结
"""
import sys
import os
import json

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.db import get_db
from app.server.api.deepseek_analyst import get_deepseek_analyst, is_deepseek_available
from app.server.api.calendar import MONTHLY_SUMMARY_SYSTEM_PROMPT, MONTHLY_SUMMARY_USER_TEMPLATE

TARGET_YEAR = 2026
TARGET_MONTH = 6


def main():
    db = get_db()

    print(f"=" * 60)
    print(f"测试 {TARGET_YEAR}年{TARGET_MONTH:02d}月 月总结 API 调用")
    print(f"=" * 60)

    # 检查时间窗口
    available, msg = is_deepseek_available()
    if not available:
        print(f"\n错误: {msg}")
        return

    # 获取周总结
    week_docs = list(db['weekly_summary'].find(
        {'year': TARGET_YEAR, 'month': TARGET_MONTH},
        {'_id': 0, 'week_index': 1, 'dates': 1, 'summary': 1}
    ).sort('week_index', 1))

    if not week_docs:
        print("\n错误: 无周总结数据")
        return

    # 拼接周总结
    weekly_parts = []
    for doc in week_docs:
        wk = doc['week_index']
        dates = doc.get('dates', [])
        date_range = f"{dates[0][:4]}-{dates[0][4:6]}-{dates[0][6:]}" if dates else ''
        date_range_end = f"{dates[-1][:4]}-{dates[-1][4:6]}-{dates[-1][6:]}" if dates else ''
        weekly_parts.append(f"【第{wk}周 ({date_range} ~ {date_range_end})】")
        weekly_parts.append(doc.get('summary', ''))
        weekly_parts.append("")

    weekly_summaries = '\n'.join(weekly_parts)

    # 构建请求
    analyst = get_deepseek_analyst()
    user_message = MONTHLY_SUMMARY_USER_TEMPLATE.format(weekly_summaries=weekly_summaries)

    print(f"\n请求参数:")
    print(f"  - Model: {analyst.model}")
    print(f"  - System message 长度: {len(MONTHLY_SUMMARY_SYSTEM_PROMPT)} 字符")
    print(f"  - User message 长度: {len(user_message)} 字符")
    print(f"  - Enable thinking: {analyst.enable_thinking}")

    try:
        import openai
        client = openai.OpenAI(api_key=analyst.api_key, base_url=analyst.base_url)

        kwargs = {
            'model': analyst.model,
            'messages': [
                {'role': 'system', 'content': MONTHLY_SUMMARY_SYSTEM_PROMPT},
                {'role': 'user', 'content': user_message},
            ],
            'max_tokens': 4096,
            'timeout': 120,
        }
        if analyst.enable_thinking:
            kwargs['reasoning_effort'] = 'high'
            kwargs['extra_body'] = {'thinking': {'type': 'enabled'}}
        else:
            kwargs['temperature'] = analyst.temperature

        print(f"\n调用 DeepSeek API...")
        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content

        if content:
            print(f"\n成功! 响应长度: {len(content)} 字符")
            print(f"\n响应内容预览 (前500字符):")
            print("-" * 60)
            print(content[:500])
            print("-" * 60)
        else:
            print(f"\n警告: DeepSeek 返回空内容")

    except Exception as e:
        print(f"\n错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
