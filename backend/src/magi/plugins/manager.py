"""
插件系统 - 插件管理器
"""
import asyncio
import importlib
import inspect
from typing import List, Dict, Optional, Type
from pathlib import Path
from .base import Plugin, PluginType


class PluginManager:
    """
    插件管理器

    职责：
    - 加载插件
    - 启用/禁用插件
    - 执行生命周期钩子
    - 管理插件依赖
    """

    def __init__(self):
        """初始化插件管理器"""
        self._plugins: Dict[str, Plugin] = {}
        self._hooks = {
            "before_sense": [],
            "after_sense": [],
            "before_plan": [],
            "after_plan": [],
            "before_act": [],
            "after_act": [],
        }

    async def load_plugin(
        self,
        plugin_class: Type[Plugin],
        config: Optional[Dict] = None,
    ) -> Plugin:
        """
        加载插件

        Args:
            plugin_class: 插件类
            config: 插件配置

        Returns:
            插件实例
        """
        # 创建插件实例
        plugin = plugin_class()

        # 应用配置
        if config:
            if "enabled" in config:
                plugin.enabled = config["enabled"]
            if "priority" in config:
                plugin.priority = config["priority"]

        # 检查依赖
        await self._check_dependencies(plugin)

        # 注册插件
        self._plugins[plugin.name] = plugin

        # 注册生命周期钩子
        self._register_hooks(plugin)

        # 收集扩展
        await self._collect_extensions(plugin)

        return plugin

    async def load_plugin_from_module(
        self,
        module_path: str,
        class_name: str,
        config: Optional[Dict] = None,
    ) -> Plugin:
        """
        从模块加载插件

        Args:
            module_path: 模块路径（如 "my_plugin"）
            class_name: 类名（如 "MyPlugin"）
            config: 插件配置

        Returns:
            插件实例
        """
        # 动态导入模块
        module = importlib.import_module(module_path)

        # 获取插件类
        plugin_class = getattr(module, class_name)

        # 验证是Plugin子类
        if not issubclass(plugin_class, Plugin):
            raise TypeError(f"{class_name} is not a subclass of Plugin")

        # 加载插件
        return await self.load_plugin(plugin_class, config)

    async def unload_plugin(self, plugin_name: str) -> bool:
        """
        卸载插件

        Args:
            plugin_name: 插件名称

        Returns:
            是否成功卸载
        """
        if plugin_name not in self._plugins:
            return False

        plugin = self._plugins[plugin_name]

        # 检查依赖
        dependent_plugins = self._get_dependents(plugin_name)
        if dependent_plugins:
            raise RuntimeError(
                f"Cannot unload plugin {plugin_name}: "
                f"required by {', '.join(dependent_plugins)}"
            )

        # 注销钩子
        self._unregister_hooks(plugin)

        # 移除插件
        del self._plugins[plugin_name]

        return True

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """
        获取插件

        Args:
            name: 插件名称

        Returns:
            插件实例或None
        """
        return self._plugins.get(name)

    def list_plugins(self) -> List[Plugin]:
        """
        列出所有插件

        Returns:
            插件列表（按优先级排序）
        """
        return sorted(
            self._plugins.values(),
            key=lambda p: p.priority,
            reverse=True,
        )

    async def execute_hooks(
        self,
        hook_name: str,
        *args,
        **kwargs
    ) -> Any:
        """
        执行生命周期钩子

        Args:
            hook_name: 钩子名称
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            执行结果
        """
        if hook_name not in self._hooks:
            raise ValueError(f"Unknown hook: {hook_name}")

        # Chain模式：顺序执行
        if hook_name.startswith("before_"):
            return await self._execute_chain_hooks(hook_name, *args, **kwargs)

        # Parallel模式：并发执行
        elif hook_name.startswith("after_"):
            return await self._execute_parallel_hooks(hook_name, *args, **kwargs)

    async def _execute_chain_hooks(
        self,
        hook_name: str,
        *args,
        **kwargs
    ) -> Any:
        """执行Chain模式钩子（顺序）"""
        hooks = self._hooks[hook_name]

        # 按优先级排序
        hooks = sorted(hooks, key=lambda h: h["plugin"].priority, reverse=True)

        result = None
        for hook_info in hooks:
            plugin = hook_info["plugin"]
            method = hook_info["method"]

            if not plugin.enabled:
                continue

            try:
                result = await method(*args, **kwargs)

                # 如果返回None，终止后续钩子
                if result is None and hook_name != "after_sense":
                    break

                # 更新参数（前一个钩子的输出作为下一个的输入）
                if len(args) > 0:
                    args = (result,) + args[1:]

            except Exception as e:
                # 错误隔离：继续执行其他钩子
                pass

        return result

    async def _execute_parallel_hooks(
        self,
        hook_name: str,
        *args,
        **kwargs
    ) -> List[Any]:
        """执行Parallel模式钩子（并发）"""
        hooks = self._hooks[hook_name]

        # 并发执行所有钩子
        tasks = []
        for hook_info in hooks:
            plugin = hook_info["plugin"]
            method = hook_info["method"]

            if not plugin.enabled:
                continue

            async def execute_hook():
                try:
                    return await method(*args, **kwargs)
                except Exception:
                    # 错误隔离
                    return None

            tasks.append(execute_hook())

        # 等待所有钩子完成
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if r is not None]

    def _register_hooks(self, plugin: Plugin):
        """注册插件的生命周期钩子"""
        hook_methods = {
            "before_sense": plugin.before_sense,
            "after_sense": plugin.after_sense,
            "before_plan": plugin.before_plan,
            "after_plan": plugin.after_plan,
            "before_act": plugin.before_act,
            "after_act": plugin.after_act,
        }

        for hook_name, method in hook_methods.items():
            # 检查是否覆盖了默认实现
            if not self._is_default_implementation(method):
                self._hooks[hook_name].append({
                    "plugin": plugin,
                    "method": method,
                })

    def _unregister_hooks(self, plugin: Plugin):
        """注销插件的生命周期钩子"""
        for hook_name in self._hooks:
            self._hooks[hook_name] = [
                h for h in self._hooks[hook_name]
                if h["plugin"] != plugin
            ]

    def _is_default_implementation(self, method) -> bool:
        """检查是否是默认实现"""
        # 获取Plugin基类的方法
        base_method = getattr(Plugin, method.__name__)
        return method.__func__ == base_method

    async def _check_dependencies(self, plugin: Plugin):
        """检查插件依赖"""
        # TODO: 实现依赖检查
        pass

    def _get_dependents(self, plugin_name: str) -> List[str]:
        """获取依赖此插件的其他插件"""
        # TODO: 实现依赖查询
        return []

    async def _collect_extensions(self, plugin: Plugin):
        """收集插件提供的扩展"""
        # TODO: 收集tools、storage、llm、sensors
        pass
