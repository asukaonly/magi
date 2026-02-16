"""
plugin系统 - plugin管理器
"""
import asyncio
import importlib
import inspect
from typing import List, Dict, Optional, type, Any
from pathlib import path
from .base import Plugin, Plugintype


class PluginManager:
    """
    plugin管理器

    职责：
    - loadplugin
    - Enable/Disableplugin
    - Execute生命period钩子
    - 管理plugindependency
    """

    def __init__(self):
        """initializeplugin管理器"""
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
        plugin_class: type[Plugin],
        config: Optional[Dict] = None,
    ) -> Plugin:
        """
        loadplugin

        Args:
            plugin_class: pluginClass
            config: pluginConfiguration

        Returns:
            pluginInstance
        """
        # createpluginInstance
        plugin = plugin_class()

        # 应用Configuration
        if config:
            if "enabled" in config:
                plugin.enabled = config["enabled"]
            if "priority" in config:
                plugin.priority = config["priority"]

        # checkdependency
        await self._check_dependencies(plugin)

        # registerplugin
        self._plugins[plugin.name] = plugin

        # register生命period钩子
        self._register_hooks(plugin)

        # 收集extension
        await self._collect_extensions(plugin)

        return plugin

    async def load_plugin_from_module(
        self,
        module_path: str,
        class_name: str,
        config: Optional[Dict] = None,
    ) -> Plugin:
        """
        从moduleloadplugin

        Args:
            module_path: modulepath（如 "my_plugin"）
            class_name: Class名（如 "MyPlugin"）
            config: pluginConfiguration

        Returns:
            pluginInstance
        """
        # dynamicimportmodule
        module = importlib.import_module(module_path)

        # getpluginClass
        plugin_class = getattr(module, class_name)

        # ValidateisPlugin子Class
        if not issubclass(plugin_class, Plugin):
            raise typeerror(f"{class_name} is not a subclass of Plugin")

        # loadplugin
        return await self.load_plugin(plugin_class, config)

    async def unload_plugin(self, plugin_name: str) -> bool:
        """
        uninstallplugin

        Args:
            plugin_name: pluginName

        Returns:
            is notsuccessuninstall
        """
        if plugin_name not in self._plugins:
            return False

        plugin = self._plugins[plugin_name]

        # checkdependency
        dependent_plugins = self._get_dependents(plugin_name)
        if dependent_plugins:
            raise Runtimeerror(
                f"Cannot unload plugin {plugin_name}: "
                f"required by {', '.join(dependent_plugins)}"
            )

        # deregister钩子
        self._unregister_hooks(plugin)

        # Removeplugin
        del self._plugins[plugin_name]

        return True

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """
        getplugin

        Args:
            name: pluginName

        Returns:
            pluginInstance或None
        """
        return self._plugins.get(name)

    def list_plugins(self) -> List[Plugin]:
        """
        column出allplugin

        Returns:
            pluginlist（按prioritysort）
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
        Execute生命period钩子

        Args:
            hook_name: 钩子Name
            *args: positionParameter
            **kwargs: 关key字Parameter

        Returns:
            Execution result
        """
        if hook_name not in self._hooks:
            raise Valueerror(f"Unknotttwn hook: {hook_name}")

        # chainpattern：顺序Execute
        if hook_name.startswith("before_"):
            return await self._execute_chain_hooks(hook_name, *args, **kwargs)

        # Parallelpattern：concurrentExecute
        elif hook_name.startswith("after_"):
            return await self._execute_parallel_hooks(hook_name, *args, **kwargs)

    async def _execute_chain_hooks(
        self,
        hook_name: str,
        *args,
        **kwargs
    ) -> Any:
        """Executechainpattern钩子（顺序）"""
        hooks = self._hooks[hook_name]

        # 按prioritysort
        hooks = sorted(hooks, key=lambda h: h["plugin"].priority, reverse=True)

        result = None
        for hook_info in hooks:
            plugin = hook_info["plugin"]
            method = hook_info["method"]

            if not plugin.enabled:
                continue

            try:
                result = await method(*args, **kwargs)

                # 如果ReturnNone，终止后续钩子
                if result is None and hook_name != "after_sense":
                    break

                # updateParameter（前一个钩子的Output作为下一个的Input）
                if len(args) > 0:
                    args = (result,) + args[1:]

            except Exception as e:
                # error隔离：继续Executeother钩子
                pass

        return result

    async def _execute_parallel_hooks(
        self,
        hook_name: str,
        *args,
        **kwargs
    ) -> List[Any]:
        """ExecuteParallelpattern钩子（concurrent）"""
        hooks = self._hooks[hook_name]

        # concurrentExecuteall钩子
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
                    # error隔离
                    return None

            tasks.append(execute_hook())

        # 等待all钩子complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if r is not None]

    def _register_hooks(self, plugin: Plugin):
        """registerplugin的生命period钩子"""
        hook_methods = {
            "before_sense": plugin.before_sense,
            "after_sense": plugin.after_sense,
            "before_plan": plugin.before_plan,
            "after_plan": plugin.after_plan,
            "before_act": plugin.before_act,
            "after_act": plugin.after_act,
        }

        for hook_name, method in hook_methods.items():
            # checkis not覆盖了defaultImplementation
            if not self._is_default_implementation(method):
                self._hooks[hook_name].append({
                    "plugin": plugin,
                    "method": method,
                })

    def _unregister_hooks(self, plugin: Plugin):
        """deregisterplugin的生命period钩子"""
        for hook_name in self._hooks:
            self._hooks[hook_name] = [
                h for h in self._hooks[hook_name]
                if h["plugin"] != plugin
            ]

    def _is_default_implementation(self, method) -> bool:
        """checkis notisdefaultImplementation"""
        # getPluginBase class的Method
        base_method = getattr(Plugin, method.__name__)
        return method.__func__ == base_method

    async def _check_dependencies(self, plugin: Plugin):
        """checkplugindependency"""
        # TODO: Implementationdependencycheck
        pass

    def _get_dependents(self, plugin_name: str) -> List[str]:
        """getdependency此plugin的otherplugin"""
        # TODO: Implementationdependencyquery
        return []

    async def _collect_extensions(self, plugin: Plugin):
        """收集plugin提供的extension"""
        # TODO: 收集tools、storage、llm、sensors
        pass
