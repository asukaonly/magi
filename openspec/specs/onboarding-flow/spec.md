# Onboarding Flow

引导流程规范，定义首次使用时的配置向导体验。

## ADDED Requirements

### Requirement: 首次使用检测

系统 SHALL 在应用启动时检测用户是否已完成首次引导。

#### Scenario: 首次用户检测
- **WHEN** 用户访问应用且 `preferences.onboarding_completed` 为 `false` 或不存在
- **THEN** 系统 SHALL 自动跳转到 `/onboarding` 路由

#### Scenario: 已完成引导用户
- **WHEN** 用户访问应用且 `preferences.onboarding_completed` 为 `true`
- **THEN** 系统 SHALL 正常进入应用主页面

### Requirement: 模式选择

系统 SHALL 在引导开始时让用户选择配置模式。

#### Scenario: 选择快速模式
- **WHEN** 用户选择"快速模式"
- **THEN** 系统 SHALL 设置 `user_mode` 为 `quick`
- **AND** 系统 SHALL 仅展示步骤 1-3（语言、LLM、人格）

#### Scenario: 选择专家模式
- **WHEN** 用户选择"专家模式"
- **THEN** 系统 SHALL 设置 `user_mode` 为 `expert`
- **AND** 系统 SHALL 展示全部 5 个步骤（语言、LLM、人格、记忆、工具）

### Requirement: 步骤导航

系统 SHALL 提供清晰的步骤指示和导航控制。

#### Scenario: 步骤指示器显示
- **WHEN** 用户处于引导流程中
- **THEN** 系统 SHALL 显示当前步骤位置和总步骤数
- **AND** 系统 SHALL 高亮当前步骤，显示已完成步骤

#### Scenario: 前进到下一步
- **WHEN** 用户完成当前步骤的必填项并点击"下一步"
- **THEN** 系统 SHALL 保存当前步骤的配置
- **AND** 系统 SHALL 前进到下一个步骤

#### Scenario: 返回上一步
- **WHEN** 用户点击"上一步"
- **THEN** 系统 SHALL 返回前一个步骤
- **AND** 系统 SHALL 保留已填写的数据

#### Scenario: 最后一步完成引导
- **WHEN** 用户在最后一个步骤点击"完成"
- **THEN** 系统 SHALL 设置 `onboarding_completed` 为 `true`
- **AND** 系统 SHALL 跳转到应用主页面

### Requirement: 中途退出处理

系统 SHALL 处理用户中途退出引导的情况。

#### Scenario: 中途关闭页面
- **WHEN** 用户在引导过程中关闭页面或刷新
- **THEN** 系统 SHALL 保存已完成的步骤数据
- **AND** 下次访问时系统 SHALL 从上次中断的步骤继续

### Requirement: 引导页面布局

引导流程 SHALL 使用独立布局，不包含主应用的侧边栏和导航。

#### Scenario: 独立布局渲染
- **WHEN** 用户访问 `/onboarding` 路由
- **THEN** 系统 SHALL 渲染独立的引导页面布局
- **AND** 系统 SHALL 不显示 MainLayout 的侧边栏和顶部导航
