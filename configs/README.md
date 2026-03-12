# Magi 配置说明

## 配置文件位置

运行时主配置文件在：

```text
~/.magi/config/agent.yaml
```

首次启动时，如果该文件不存在，会从下面这份模板自动生成：

```text
backend/configs/config.example.yaml
```

## 推荐配置方式

当前版本推荐直接使用产品内的引导页或设置页完成配置，尤其是 LLM 部分。

- 供应商连接信息保存在 `llm.providers`
- 场景模型选择保存在 `llm.selections`
- 配置完成后会持久化到 `~/.magi/config/agent.yaml`

如果需要手动重置本地配置，可以重新复制模板：

```bash
mkdir -p ~/.magi/config
cp backend/configs/config.example.yaml ~/.magi/config/agent.yaml
```

## 启动后端

```bash
cd backend
python run_server.py
```

启动后可访问：

- API: `http://127.0.0.1:8000`
- 健康检查: `http://127.0.0.1:8000/api/health`
- WebSocket: `ws://127.0.0.1:8000/ws`

## 配置验证

- LLM 连通性请直接在设置页或引导页的供应商配置里使用“测试连接”
- 行为回归请优先运行仓库内自动化测试，而不是旧的临时脚本

```bash
cd backend
pytest
```

## 相关参考

- 产品配置流程：`docs/product-configuration-guide.md`
- 配置模板：`backend/configs/config.example.yaml`
- 启动入口：`backend/run_server.py`
