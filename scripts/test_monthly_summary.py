"""
测试脚本：直接调用月总结生成逻辑，捕获详细错误
"""
import sys
import os
import traceback

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.db import get_db
from app.server.api.deepseek_analyst import get_deepseek_analyst, is_deepseek_available

TARGET_YEAR = 2026
TARGET_MONTH = 6


def main():
    db = get_db()

    print(f"=" * 60)
    print(f"测试 {TARGET_YEAR}年{TARGET_MONTH:02d}月 月总结生成")
    print(f"=" * 60)

    # 1. 检查周总结数据
    week_docs = list(db['weekly_summary'].find(
        {'year': TARGET_YEAR, 'month': TARGET_MONTH},
        {'_id': 0, 'week_index': 1, 'dates': 1, 'summary': 1}
    ).sort('week_index', 1))

    print(f"\n1. 找到 {len(week_docs)} 条周总结记录")
    if not week_docs:
        print("   错误: 无周总结数据")
        return

    for doc in week_docs:
        print(f"   - 第{doc.get('week_index')}周: {len(doc.get('summary', ''))} 字符")

    # 2. 拼接周总结
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
    print(f"\n2. 拼接后周总结总长度: {len(weekly_summaries)} 字符")

    # 3. 检查 DeepSeek 配置
    analyst = get_deepseek_analyst()
    print(f"\n3. DeepSeek 配置:")
    print(f"   - API Key 已配置: {bool(analyst.api_key)}")
    print(f"   - Base URL: {analyst.base_url}")
    print(f"   - Model: {analyst.model}")

    # 4. 检查时间窗口
    available, msg = is_deepseek_available()
    print(f"\n4. DeepSeek 时间窗口:")
    print(f"   - 可用: {available}")
    if not available:
        print(f"   - 原因: {msg}")

    # 5. 尝试构建请求（不实际发送）
    if analyst.api_key and available:
        try:
            import openai
            client = openai.OpenAI(api_key=analyst.api_key, base_url=analyst.base_url)

            from app.server.api.calendar import MONTHLY_SUMMARY_PROMPT
            user_message = MONTHLY_SUMMARY_PROMPT.format(weekly_summaries=weekly_summaries)

            print(f"\n5. 构建请求:")
            print(f"   - User message 长度: {len(user_message)} 字符")
            print(f"   - 前500字符预览:")
            print(f"     {user_message[:500]}...")

            # 实际调用（取消注释以测试）
            # print(f"\n6. 调用 DeepSeek API...")
            # kwargs = {
            #     'model': analyst.model,
            #     'messages': [
            #         {'role': 'system', 'content': '你是一位专业的A股量化策略分析师，输出中文月度总结报告。'},
            #         {'role': 'user', 'content': user_message},
            #     ],
            #     'max_tokens': 4096,
            #     'timeout': 120,
            # }
            # if analyst.enable_thinking:
            #     kwargs['reasoning_effort'] = 'high'
            #     kwargs['extra_body'] = {'thinking': {'type': 'enabled'}}
            # else:
            #     kwargs['temperature'] = analyst.temperature
            #
            # response = client.chat.completions.create(**kwargs)
            # content = response.choices[0].message.content
            # print(f"   - 响应长度: {len(content) if content else 0} 字符")
            # print(f"   - 响应预览: {content[:200] if content else '空'}...")

        except Exception as e:
            print(f"\n   错误: {type(e).__name__}: {e}")
            traceback.print_exc()
    else:
        print(f"\n5. 跳过 API 调用（API Key 未配置或时间窗口不可用）")


if __name__ == '__main__':
    main()
