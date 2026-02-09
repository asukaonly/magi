# Magi 配置说明

## 配置文件位置

主配置文件：**`configs/agent.yaml`**

---

## 🚀 快速配置LLM

### 方式1: 使用环境变量（推荐）

```bash
# OpenAI
export OPENAI_API_KEY="sk-your-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # 可选

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-your-key"
export ANTHROPIC_BASE_URL="https://api.anthropic.com"  # 可选
```

然后直接使用：`agent.yaml` 中已经配置为从环境变量读取：
```yaml
api_key: "${OPENAI_API_KEY}"
base_url: "${OPENAI_BASE_URL:}"
```

### 方式2: 直接修改配置文件

编辑 `configs/agent.yaml`：

```yaml
agent:
  llm:
    provider: "openai"           # 或 "anthropic"
    model: "gpt-4"               # 模型名称
    api_key: "sk-your-key"       # 直接填入密钥
    base_url: "https://..."      # 可选：代理地址
```

---

## 📝 LLM配置参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `provider` | 提供商 | `openai`, `anthropic` |
| `model` | 模型名称 | `gpt-4`, `claude-3-opus-20240229` |
| `api_key` | API密钥 | `sk-...` 或从环境变量读取 |
| `base_url` | 自定义endpoint | `https://api.openai.com/v1` |
| `temperature` | 温度 | `0.7` (0.0-2.0) |
| `max_tokens` | 最大token数 | `2000` |
| `timeout` | 超时时间 | `60` 秒 |

---

## 🔧 常见配置场景

### 1. OpenAI官方API

```yaml
llm:
  provider: "openai"
  model: "gpt-4"
  api_key: "${OPENAI_API_KEY}"
  # base_url留空，使用默认endpoint
```

### 2. 使用代理/中转服务

```yaml
llm:
  provider: "openai"
  model: "gpt-4"
  api_key: "your-proxy-key"
  base_url: "https://your-proxy.com/v1"  # 你的代理地址
```

### 3. Anthropic Claude

```yaml
llm:
  provider: "anthropic"
  model: "claude-3-opus-20240229"
  api_key: "${ANTHROPIC_API_KEY}"
```

---

## ✅ 配置完成后的测试

### 1. 测试LLM连接

```bash
# 设置API密钥
export OPENAI_API_KEY="sk-your-key"

# 运行测试
cd backend
python test_llm.py
```

### 2. 启动服务器

```bash
cd backend
python run_server.py
```

访问 http://localhost:8000/docs 查看API文档

---

## 📖 详细文档

- **完整配置指南**: `backend/LLM_CONFIG_GUIDE.md`
- **后端测试指南**: `backend/README_TEST.md`
- **快速功能测试**: 运行 `backend/quick_test.py`

---

## 💡 提示

1. **安全性**: 不要在配置文件中硬编码API密钥，使用环境变量
2. **代理设置**: 如果使用代理，只需配置 `base_url`
3. **模型选择**: 测试时使用便宜的模型（如 `gpt-3.5-turbo`）
4. **超时设置**: 如果网络慢，增加 `timeout` 值

---

## 🆘 常见问题

**Q: 找不到config.yaml？**
A: 配置文件是 `configs/agent.yaml`

**Q: 如何使用代理？**
A: 设置 `base_url` 为你的代理地址

**Q: API密钥放在哪里？**
A: 推荐使用环境变量，见上面的"方式1"

**Q: 测试时报错？**
A: 检查API密钥是否正确，网络是否通畅
