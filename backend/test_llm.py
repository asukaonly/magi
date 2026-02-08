#!/usr/bin/env python3
"""
LLM连接测试脚本

测试OpenAI和Anthropic的连接和基本功能
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from magi.llm import OpenAIAdapter, AnthropicAdapter


def print_header(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


async def test_openai(api_key: str, base_url: str = None):
    """测试OpenAI连接"""
    print_header("测试 OpenAI")

    adapter = OpenAIAdapter(
        api_key=api_key,
        model="gpt-3.5-turbo",
        base_url=base_url,
    )

    print(f"模型: {adapter.model_name}")
    print(f"Base URL: {base_url or '默认 (https://api.openai.com/v1)'}")

    try:
        # 测试简单生成
        print("\n测试1: 简单文本生成...")
        response = await adapter.generate(
            prompt="Say 'Hello from OpenAI!' in one sentence.",
            max_tokens=50,
            temperature=0.7
        )
        print(f"✓ 响应: {response}")

        # 测试对话
        print("\n测试2: 对话功能...")
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is 2+2? Answer in one word."},
        ]
        response = await adapter.chat(messages=messages)
        print(f"✓ 响应: {response}")

        # 测试流式生成
        print("\n测试3: 流式生成...")
        print("  输出: ", end="", flush=True)
        async for chunk in adapter.generate_stream(
            prompt="Count from 1 to 5, separated by spaces.",
            max_tokens=50
        ):
            print(chunk, end="", flush=True)
        print("\n✓ 流式生成完成")

        print("\n✅ OpenAI 测试全部通过！")
        return True

    except Exception as e:
        print(f"\n❌ OpenAI 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_anthropic(api_key: str, base_url: str = None):
    """测试Anthropic连接"""
    print_header("测试 Anthropic Claude")

    adapter = AnthropicAdapter(
        api_key=api_key,
        model="claude-3-haiku-20240307",  # 使用快速便宜的模型
        base_url=base_url,
    )

    print(f"模型: {adapter.model_name}")
    print(f"Base URL: {base_url or '默认 (https://api.anthropic.com)'}")

    try:
        # 测试简单生成
        print("\n测试1: 简单文本生成...")
        response = await adapter.generate(
            prompt="Say 'Hello from Anthropic!' in one sentence.",
            max_tokens=50,
            temperature=0.7
        )
        print(f"✓ 响应: {response}")

        # 测试对话
        print("\n测试2: 对话功能...")
        messages = [
            {"role": "user", "content": "What is 3+3? Answer in one word."},
        ]
        response = await adapter.chat(messages=messages)
        print(f"✓ 响应: {response}")

        # 测试流式生成
        print("\n测试3: 流式生成...")
        print("  输出: ", end="", flush=True)
        async for chunk in adapter.generate_stream(
            prompt="Count from 1 to 5, separated by spaces.",
            max_tokens=50
        ):
            print(chunk, end="", flush=True)
        print("\n✓ 流式生成完成")

        print("\n✅ Anthropic 测试全部通过！")
        return True

    except Exception as e:
        print(f"\n❌ Anthropic 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("  Magi AI Agent Framework - LLM 连接测试")
    print("=" * 60)

    # 从环境变量获取API密钥
    openai_key = os.getenv("OPENAI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    openai_base_url = os.getenv("OPENAI_BASE_URL")
    anthropic_base_url = os.getenv("ANTHROPIC_BASE_URL")

    print("\n提示：可以通过环境变量设置API密钥：")
    print("  export OPENAI_API_KEY='sk-your-key'")
    print("  export ANTHROPIC_API_KEY='sk-ant-your-key'")
    print("  export OPENAI_BASE_URL='https://...' (可选)")

    # 测试OpenAI
    if openai_key:
        await test_openai(openai_key, openai_base_url)
    else:
        print("\n⚠️  未设置 OPENAI_API_KEY，跳过 OpenAI 测试")

    # 测试Anthropic
    if anthropic_key:
        await test_anthropic(anthropic_key, anthropic_base_url)
    else:
        print("\n⚠️  未设置 ANTHROPIC_API_KEY，跳过 Anthropic 测试")

    print("\n" + "=" * 60)
    print("  测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
