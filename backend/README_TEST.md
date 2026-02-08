# 🚀 Magi 后台快速测试指南

## 📦 快速开始

### 1️⃣ 运行快速测试（推荐首选）

验证所有核心功能是否正常工作：

```bash
cd backend
python quick_test.py
```

**预期输出：**
```
🎉 所有测试通过！后台功能正常！
```

### 2️⃣ 启动API服务器

```bash
cd backend
python run_server.py
```

启动后访问：
- 📡 API服务: http://localhost:8000
- 📚 API文档: http://localhost:8000/docs
- 🔌 WebSocket: ws://localhost:8000/ws

---

## 🧪 测试方式

### 方式A: 快速功能测试

```bash
python quick_test.py
```

**测试内容：**
- ✅ 基础工具（bash、文件读写）
- ✅ 工具执行
- ✅ 智能推荐引擎
- ✅ DAG执行计划器
- ✅ 版本管理
- ✅ 权限控制

### 方式B: 完整单元测试

```bash
# 基础工具测试
PYTHONPATH=/Users/asuka/code/magi/backend/src python examples/test_tools.py

# 高级功能测试
PYTHONPATH=/Users/asuka/code/magi/backend/src python examples/test_tool_advanced.py
```

### 方式C: API交互测试

**1. 启动服务器**
```bash
python run_server.py
```

**2. 打开浏览器访问API文档**
```
http://localhost:8000/docs
```

**3. 在Swagger UI中测试API**

或使用curl：

```bash
# 健康检查
curl http://localhost:8000/health

# 获取所有工具
curl http://localhost:8000/api/v1/tools

# 创建Agent
curl -X POST http://localhost:8000/api/v1/agents \
  -H "Content-Type: application/json" \
  -d '{"name": "test", "type": "task"}'
```

---

## 📊 测试覆盖

### 工具注册表 (100% 完成)
- [x] 工具注册和卸载
- [x] 参数验证
- [x] 权限控制
- [x] 智能推荐引擎
- [x] DAG执行计划
- [x] 版本管理
- [x] 统计监控

### 内置工具
- [x] **BashTool**: 执行Shell命令
- [x] **FileReadTool**: 读取文件
- [x] **FileWriteTool**: 写入文件
- [x] **FileListTool**: 列出目录

---

## 📝 测试文件说明

| 文件 | 说明 | 用途 |
|------|------|------|
| `quick_test.py` | 快速功能测试 | 验证核心功能 ⭐ **推荐首选** |
| `examples/test_tools.py` | 基础工具测试 | 详细工具功能测试 |
| `examples/test_tool_advanced.py` | 高级功能测试 | 推荐引擎、DAG、版本管理 |
| `run_server.py` | 服务器启动脚本 | 启动API服务 |
| `TESTING_GUIDE.md` | 完整测试指南 | 详细测试文档 |

---

## 🔧 常见问题

### Q: 测试时报错 "Module not found"?
```bash
# 确保设置了PYTHONPATH
export PYTHONPATH=/Users/asuka/code/magi/backend/src

# 或者在命令前添加
PYTHONPATH=/Users/asuka/code/magi/backend/src python your_script.py
```

### Q: 端口8000被占用?
修改 `run_server.py` 中的端口：
```python
uvicorn.run(app, host="0.0.0.0", port=8001)  # 改成其他端口
```

### Q: 权限错误?
确保测试时包含必要的权限：
```python
context = ToolExecutionContext(
    permissions=["dangerous_tools"],  # 添加这个
)
```

---

## ✅ 验证清单

测试完成后，确认以下功能正常：

- [ ] `quick_test.py` 全部通过
- [ ] 可以成功启动服务器
- [ ] 可以访问API文档 (http://localhost:8000/docs)
- [ ] 可以创建和管理Agent
- [ ] 工具执行正常
- [ ] WebSocket连接成功

---

## 🎯 下一步

1. ✅ 完成功能测试
2. 📖 阅读 [TESTING_GUIDE.md](TESTING_GUIDE.md) 了解更多
3. 🚀 编写自定义工具
4. 📊 性能测试
5. 🐛 Bug反馈

---

## 💡 提示

- 首次测试建议先运行 `quick_test.py`
- 需要API测试时再启动服务器
- 查看 `TESTING_GUIDE.md` 获取更多测试示例
- 所有测试都在开发环境配置，无需额外设置

**祝测试愉快！** 🎉
