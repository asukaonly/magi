# LLM 配置指南

## 📋 目录
1. [快速配置](#快速配置)
2. [配置参数说明](#配置参数说明)
3. [常见场景配置](#常见场景配置)
4. [环境变量配置](#环境变量配置)
5. [测试LLM连接](#测试llm连接)

---

## 快速配置

### 方式1: 使用配置文件（推荐）

1. **复制配置模板**
```bash
mkdir -p ~/.magi/config
cp backend/configs/config.example.yaml ~/.magi/config/agent.yaml
```

2. **编辑配置文件**
```yaml
agent:
  llm:
    provider: "openai"           # 或 "anthropic"
    model: "gpt-4"               # 模型名称
    api_key: "sk-your-api-key"   # 你的API密钥
    base_url: "https://api.openai.com/v1"  # 可选：自定义endpoint
```

3. **加载配置**
```python
from magi.config import ConfigLoader

config = ConfigLoader.load("config.yaml")
```

### 方式2: 使用环境变量（推荐用于生产环境）

```bash
# OpenAI
export OPENAI_API_KEY="sk-your-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # 可选

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-your-key"
export ANTHROPIC_BASE_URL="https://api.anthropic.com"  # 可选
```

### 方式3: 代码中直接配置

```python
from magi.llm import OpenAIAdapter, AnthropicAdapter

# OpenAI
adapter = OpenAIAdapter(
    api_key="sk-your-key",
    model="gpt-4",
    base_url="https://api.openai.com/v1",  # 可选
)

# Anthropic
adapter = AnthropicAdapter(
    api_key="sk-ant-your-key",
    model="claude-3-opus-20240229",
    base_url="https://api.anthropic.com",  # 可选
)
```

---

## 配置参数说明

### LLMConfig 完整参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `provider` | enum | ✅ | `"openai"` | LLM提供商：`openai`, `anthropic`, `local` |
| `model` | string | ✅ | `"gpt-4"` | 模型名称 |
| `api_key` | string | ✅ | - | API密钥 |
| `base_url` | string | ❌ | - | 自定义API endpoint |
| `api_base` | string | ❌ | - | 兼容旧配置，等同于`base_url` |
| `temperature` | float | ❌ | `0.7` | 温度参数（0.0-2.0） |
| `max_tokens` | int | ❌ | - | 最大生成token数 |
| `timeout` | int | ❌ | `60` | 请求超时时间（秒） |

### 关于 base_url 和 api_base

- **`base_url`**: 新的标准参数名（推荐使用）
- **`api_base`**: 旧参数名，向后兼容
- 优先级：`base_url` > `api_base`
- 两个参数只需设置一个

---

## 常见场景配置

### 1️⃣ OpenAI官方API

```yaml
llm:
  provider: "openai"
  model: "gpt-4"
  api_key: "sk-your-openai-key"
  # base_url可以省略，会使用默认的 https://api.openai.com/v1
```

**支持的模型：**
- `gpt-4` - GPT-4
- `gpt-4-turbo` - GPT-4 Turbo
- `gpt-3.5-turbo` - GPT-3.5 Turbo

### 2️⃣ 使用代理或中转服务

```yaml
llm:
  provider: "openai"
  model: "gpt-4"
  api_key: "your-proxy-key"
  base_url: "https://your-proxy.com/v1"  # 你的代理endpoint
```

**常见代理服务：**
- OpenAI中转API
- Azure OpenAI
- 国内API代理服务

### 3️⃣ Anthropic Claude

```yaml
llm:
  provider: "anthropic"
  model: "claude-3-opus-20240229"
  api_key: "sk-ant-your-key"
  # base_url可选，默认 https://api.anthropic.com
```

**支持的模型：**
- `claude-3-opus-20240229` - Claude 3 Opus（最强）
- `claude-3-sonnet-20240229` - Claude 3 Sonnet（平衡）
- `claude-3-haiku-20240307` - Claude 3 Haiku（快速）

### 4️⃣ Azure OpenAI

```yaml
llm:
  provider: "openai"
  model: "gpt-4"  # Azure deployment name
  api_key: "your-azure-key"
  base_url: "https://your-resource.openai.azure.com/openai/deployments/your-deployment"
```

### 5️⃣ 国内API中转服务

```yaml
llm:
  provider: "openai"
  model: "gpt-4"
  api_key: "your-service-key"
  base_url: "https://api.your-service.com/v1"
```

**注意：** 国内服务可能需要使用特定的模型名称，如：
- `gpt-4` → `gpt-4-turbo`
- `gpt-3.5-turbo` → `gpt-3.5-turbo-16k`

---

## 环境变量配置

### 支持的环境变量

| 变量名 | 说明 | 对应配置 |
|--------|------|----------|
| `OPENAI_API_KEY` | OpenAI API密钥 | `llm.api_key` |
| `OPENAI_BASE_URL` | OpenAI endpoint | `llm.base_url` |
| `ANTHROPIC_API_KEY` | Anthropic API密钥 | `llm.api_key` |
| `ANTHROPIC_BASE_URL` | Anthropic endpoint | `llm.base_url` |

### 使用示例

```bash
# 设置环境变量
export OPENAI_API_KEY="sk-your-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"

# 启动服务
python run_server.py
```

### 在Python中使用

```python
import os
from magi.llm import OpenAIAdapter

adapter = OpenAIAdapter(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL"),
)
```

---

## 测试LLM连接

### 创建测试脚本

创建 `test_llm.py`:

```python
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from magi.llm import OpenAIAdapter, AnthropicAdapter

async def test_openai():
    """测试OpenAI"""
    print("\n=== 测试 OpenAI ===")

    adapter = OpenAIAdapter(
        api_key="your-api-key",  # 替换为你的密钥
        model="gpt-3.5-turbo",   # 使用便宜的模型测试
        base_url="https://api.openai.com/v1",  # 可选
    )

    try:
        response = await adapter.generate(
            prompt="Say 'Hello from OpenAI!' in one sentence.",
            max_tokens=50
        )
        print(f"✓ OpenAI响应: {response}")
        return True
    except Exception as e:
        print(f"✗ OpenAI错误: {e}")
        return False

async def test_anthropic():
    """测试Anthropic"""
    print("\n=== 测试 Anthropic ===")

    adapter = AnthropicAdapter(
        api_key="sk-ant-your-key",  # 替换为你的密钥
        model="claude-3-haiku-20240307",  # 使用快速便宜的模型
    )

    try:
        response = await adapter.generate(
            prompt="Say 'Hello from Anthropic!' in one sentence.",
            max_tokens=50
        )
        print(f"✓ Anthropic响应: {response}")
        return True
    except Exception as e:
        print(f"✗ Anthropic错误: {e}")
        return False

async def test_chat():
    """测试对话功能"""
    print("\n=== 测试对话功能 ===")

    adapter = OpenAIAdapter(
        api_key="your-api-key",
        model="gpt-3.5-turbo",
    )

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is 2+2?"},
    ]

    try:
        response = await adapter.chat(messages=messages)
        print(f"✓ 对话响应: {response}")
        return True
    except Exception as e:
        print(f"✗ 对话错误: {e}")
        return False

async def main():
    print("=" * 60)
    print("LLM 连接测试")
    print("=" * 60)

    # 测试OpenAI
    # await test_openai()

    # 测试Anthropic
    # await test_anthropic()

    # 测试对话
    # await test_chat()

    print("\n提示：取消上面测试的注释来测试对应的LLM")

if __name__ == "__main__":
    asyncio.run(main())
```

### 运行测试

```bash
cd backend
python test_llm.py
```

---

## 常见问题

### Q1: 如何使用国内API代理？

A: 配置`base_url`指向你的代理服务：

```yaml
llm:
  provider: "openai"
  api_key: "your-proxy-key"
  base_url: "https://your-proxy.com/v1"
```

### Q2: API密钥应该写在哪里？

A: 推荐使用环境变量，不要硬编码在代码中：

```bash
export OPENAI_API_KEY="sk-your-key"
```

### Q3: 如何配置多个LLM？

A: 可以创建多个配置文件或Adapter实例：

```python
openai_adapter = OpenAIAdapter(api_key="...")
anthropic_adapter = AnthropicAdapter(api_key="...")
```

### Q4: 连接超时怎么办？

A: 增加`timeout`参数：

```yaml
llm:
  timeout: 120  # 增加到120秒
```

### Q5: 如何验证配置是否正确？

A: 运行上面的`test_llm.py`测试脚本

---

## 下一步

1. ✅ 配置LLM
2. 🧪 运行测试脚本验证连接
3. 🚀 启动服务器
4. 📝 创建你的第一个Agent

需要帮助？查看完整文档或提Issue！
