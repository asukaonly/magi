/**
 * Settings页面
 */
import React, { useEffect, useState } from 'react';
import {
  Card,
  Form,
  Input,
  Select,
  InputNumber,
  Switch,
  Button,
  Space,
  message,
  Tabs,
  Spin,
  Alert,
} from 'antd';
import {
  SaveOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import { configApi, SystemConfig } from '../api/modules/config';

const { Option } = Select;
const { TextArea } = Input;

export const SettingsPage: React.FC = () => {
  const [form] = Form.useForm();
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState('agent');

  useEffect(() => {
    fetchConfig();
  }, []);

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const response = await configApi.get();
      setConfig(response.data);
      form.setFieldsValue(response.data);
    } catch (error: any) {
      message.error('加载配置失败: ' + (error.message || '未知错误'));
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (tabKey: string) => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      // 根据当前标签页构建更新的配置
      const updateMap: Record<string, (values: any) => Partial<SystemConfig>> = {
        agent: (v) => ({ agent: v }),
        llm: (v) => ({ llm: v }),
        loop: (v) => ({ loop: v }),
        message_bus: (v) => ({ message_bus: v }),
        memory: (v) => ({ memory: v }),
        websocket: (v) => ({ websocket: v }),
        log: (v) => ({ log: v }),
      };

      const updateFn = updateMap[tabKey];
      if (updateFn) {
        const partialConfig = updateFn(values);
        await configApi.update(partialConfig);
        message.success('配置保存成功');
        await fetchConfig(); // 重新加载配置
      }
    } catch (error: any) {
      if (error.errorFields) {
        message.warning('请检查表单输入');
      } else {
        message.error('保存配置失败: ' + (error.message || '未知错误'));
      }
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    const confirmed = window.confirm('确定要重置所有配置为默认值吗？');
    if (!confirmed) return;

    try {
      setLoading(true);
      await configApi.reset();
      message.success('配置已重置为默认值');
      await fetchConfig();
    } catch (error: any) {
      message.error('重置配置失败: ' + (error.message || '未知错误'));
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '50px 0' }}>
        <Spin size="large" tip="加载配置中..." />
      </div>
    );
  }

  return (
    <div style={{ padding: '24px' }}>
      <Card
        title="系统配置"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchConfig}>
              刷新
            </Button>
            <Button danger onClick={handleReset}>
              重置为默认
            </Button>
          </Space>
        }
      >
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          tabPosition="left"
          items={[
            {
              key: 'agent',
              label: 'Agent配置',
              children: (
                <Card title="Agent基础配置" type="inner">
                  <Form
                    form={form}
                    layout="vertical"
                    initialValues={config?.agent}
                  >
                    <Form.Item
                      label="Agent名称"
                      name={['agent', 'name']}
                      rules={[{ required: true, message: '请输入Agent名称' }]}
                    >
                      <Input placeholder="my-agent" />
                    </Form.Item>

                    <Form.Item
                      label="描述"
                      name={['agent', 'description']}
                    >
                      <TextArea rows={3} placeholder="Agent的功能描述" />
                    </Form.Item>

                    <Form.Item>
                      <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        onClick={() => handleSave('agent')}
                        loading={saving}
                      >
                        保存Agent配置
                      </Button>
                    </Form.Item>
                  </Form>
                </Card>
              ),
            },
            {
              key: 'llm',
              label: 'LLM配置',
              children: (
                <Card title="大语言模型配置" type="inner">
                  <Alert
                    message="提示"
                    description="API密钥将以加密方式存储，请确保输入正确。"
                    type="info"
                    showIcon
                    style={{ marginBottom: 16 }}
                  />
                  <Form
                    form={form}
                    layout="vertical"
                    initialValues={config?.llm}
                  >
                    <Form.Item
                      label="提供商"
                      name={['llm', 'provider']}
                      rules={[{ required: true }]}
                    >
                      <Select>
                        <Option value="openai">OpenAI</Option>
                        <Option value="anthropic">Anthropic</Option>
                        <Option value="local">本地模型</Option>
                      </Select>
                    </Form.Item>

                    <Form.Item
                      label="模型名称"
                      name={['llm', 'model']}
                      rules={[{ required: true, message: '请输入模型名称' }]}
                    >
                      <Input placeholder="gpt-4" />
                    </Form.Item>

                    <Form.Item
                      label="API密钥"
                      name={['llm', 'api_key']}
                    >
                      <Input.Password placeholder="sk-..." />
                    </Form.Item>

                    <Form.Item
                      label="Base URL（可选）"
                      name={['llm', 'base_url']}
                    >
                      <Input placeholder="https://api.openai.com/v1" />
                    </Form.Item>

                    <Form.Item>
                      <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        onClick={() => handleSave('llm')}
                        loading={saving}
                      >
                        保存LLM配置
                      </Button>
                    </Form.Item>
                  </Form>
                </Card>
              ),
            },
            {
              key: 'loop',
              label: '循环配置',
              children: (
                <Card title="Agent循环策略配置" type="inner">
                  <Form
                    form={form}
                    layout="vertical"
                    initialValues={config?.loop}
                  >
                    <Form.Item
                      label="循环策略"
                      name={['loop', 'strategy']}
                      rules={[{ required: true }]}
                      tooltip="STEP: 单步执行 | WAVE: 波次执行 | CONTINUOUS: 持续执行"
                    >
                      <Select>
                        <Option value="step">单步 (STEP)</Option>
                        <Option value="wave">波次 (WAVE)</Option>
                        <Option value="continuous">持续 (CONTINUOUS)</Option>
                      </Select>
                    </Form.Item>

                    <Form.Item
                      label="循环间隔（秒）"
                      name={['loop', 'interval']}
                      rules={[{ required: true }]}
                    >
                      <InputNumber min={0.1} max={60} step={0.1} style={{ width: '100%' }} />
                    </Form.Item>

                    <Form.Item>
                      <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        onClick={() => handleSave('loop')}
                        loading={saving}
                      >
                        保存循环配置
                      </Button>
                    </Form.Item>
                  </Form>
                </Card>
              ),
            },
            {
              key: 'message_bus',
              label: '消息总线',
              children: (
                <Card title="消息总线配置" type="inner">
                  <Form
                    form={form}
                    layout="vertical"
                    initialValues={config?.message_bus}
                  >
                    <Form.Item
                      label="后端类型"
                      name={['message_bus', 'backend']}
                      rules={[{ required: true }]}
                    >
                      <Select>
                        <Option value="memory">内存</Option>
                        <Option value="sqlite">SQLite</Option>
                        <Option value="redis">Redis</Option>
                      </Select>
                    </Form.Item>

                    <Form.Item
                      label="队列最大长度"
                      name={['message_bus', 'max_size']}
                    >
                      <InputNumber min={100} max={10000} style={{ width: '100%' }} />
                    </Form.Item>

                    <Form.Item>
                      <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        onClick={() => handleSave('message_bus')}
                        loading={saving}
                      >
                        保存消息总线配置
                      </Button>
                    </Form.Item>
                  </Form>
                </Card>
              ),
            },
            {
              key: 'memory',
              label: '记忆存储',
              children: (
                <Card title="记忆存储配置" type="inner">
                  <Form
                    form={form}
                    layout="vertical"
                    initialValues={config?.memory}
                  >
                    <Form.Item
                      label="后端类型"
                      name={['memory', 'backend']}
                      rules={[{ required: true }]}
                    >
                      <Select>
                        <Option value="memory">内存</Option>
                        <Option value="sqlite">SQLite</Option>
                        <Option value="chromadb">ChromaDB</Option>
                      </Select>
                    </Form.Item>

                    <Form.Item
                      label="存储路径"
                      name={['memory', 'path']}
                    >
                      <Input placeholder="./data/memory" />
                    </Form.Item>

                    <Form.Item>
                      <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        onClick={() => handleSave('memory')}
                        loading={saving}
                      >
                        保存记忆存储配置
                      </Button>
                    </Form.Item>
                  </Form>
                </Card>
              ),
            },
            {
              key: 'websocket',
              label: 'WebSocket',
              children: (
                <Card title="WebSocket服务配置" type="inner">
                  <Form
                    form={form}
                    layout="vertical"
                    initialValues={config?.websocket}
                  >
                    <Form.Item
                      label="启用WebSocket"
                      name={['websocket', 'enabled']}
                      valuePropName="checked"
                    >
                      <Switch />
                    </Form.Item>

                    <Form.Item
                      label="端口"
                      name={['websocket', 'port']}
                    >
                      <InputNumber min={1024} max={65535} style={{ width: '100%' }} />
                    </Form.Item>

                    <Form.Item>
                      <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        onClick={() => handleSave('websocket')}
                        loading={saving}
                      >
                        保存WebSocket配置
                      </Button>
                    </Form.Item>
                  </Form>
                </Card>
              ),
            },
            {
              key: 'log',
              label: '日志配置',
              children: (
                <Card title="日志系统配置" type="inner">
                  <Form
                    form={form}
                    layout="vertical"
                    initialValues={config?.log}
                  >
                    <Form.Item
                      label="日志级别"
                      name={['log', 'level']}
                      rules={[{ required: true }]}
                    >
                      <Select>
                        <Option value="DEBUG">DEBUG</Option>
                        <Option value="INFO">INFO</Option>
                        <Option value="WARNING">WARNING</Option>
                        <Option value="ERROR">ERROR</Option>
                      </Select>
                    </Form.Item>

                    <Form.Item
                      label="日志路径"
                      name={['log', 'path']}
                    >
                      <Input placeholder="./logs/magi.log" />
                    </Form.Item>

                    <Form.Item>
                      <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        onClick={() => handleSave('log')}
                        loading={saving}
                      >
                        保存日志配置
                      </Button>
                    </Form.Item>
                  </Form>
                </Card>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
};
