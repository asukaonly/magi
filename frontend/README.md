# Magi Frontend

Magi AI Agent Framework的前端应用，基于React + TypeScript + Vite构建。

## 技术栈

- **框架**: React 18 + TypeScript
- **构建工具**: Vite 5
- **UI库**: Ant Design 5
- **样式**: TailwindCSS 3
- **路由**: React Router 6
- **状态管理**: Zustand 4
- **HTTP客户端**: Axios
- **图表**: Recharts 2
- **WebSocket**: Socket.IO Client

## 项目结构

```
src/
├── api/              # API客户端和模块
│   ├── client.ts     # Axios配置
│   ├── modules/      # API模块（agents、tasks、tools等）
│   └── index.ts
├── components/       # 组件
│   ├── layout/       # 布局组件（Header、Sidebar、MainLayout）
│   ├── agents/       # Agent相关组件
│   ├── tasks/        # 任务相关组件
│   └── ...
├── pages/            # 页面组件
│   ├── Dashboard.tsx
│   ├── Agents.tsx
│   ├── Tasks.tsx
│   └── ...
├── stores/           # Zustand状态管理
│   ├── agentsStore.ts
│   ├── tasksStore.ts
│   └── index.ts
├── router/           # 路由配置
│   └── index.tsx
├── hooks/            # 自定义Hooks
├── utils/            # 工具函数
├── types/            # TypeScript类型定义
├── App.tsx           # 根组件
├── main.tsx          # 应用入口
└── index.css         # 全局样式
```

## 开发

### 安装依赖

```bash
npm install
```

### 启动开发服务器

```bash
npm run dev
```

前端将运行在 http://localhost:5173

### 构建生产版本

```bash
npm run build
```

### 预览生产构建

```bash
npm run preview
```

## API配置

在 `.env.development` 文件中配置API地址：

```env
VITE_API_BASE_URL=http://localhost:8000/api
```

## 可用脚本

- `npm run dev` - 启动开发服务器
- `npm run build` - 构建生产版本
- `npm run preview` - 预览生产构建
- `npm run lint` - 运行ESLint检查
- `npm run type-check` - TypeScript类型检查
