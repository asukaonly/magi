/**
 * 人格配置页面
 *
 * 用于配置AI的人格模型，支持手动输入和AI生成
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Form,
  Input,
  Select,
  Switch,
  Button,
  Space,
  message,
  Tabs,
  Slider,
  Row,
  Col,
  Divider,
  Alert,
  Spin,
  Modal,
  Tooltip,
  Typography,
  Tag,
  List,
} from 'antd';
import {
  SaveOutlined,
  ThunderboltOutlined,
  ReloadOutlined,
  PlusOutlined,
  DeleteOutlined,
  QuestionCircleOutlined,
  CheckOutlined,
  ExclamationCircleOutlined,
  DiffOutlined,
} from '@ant-design/icons';
import { personalityApi, type PersonalityConfig, type PersonalityCompareResponse, type PersonalityDiff } from '../api';

const { TextArea } = Input;
const { Option } = Select;
const { Text, Title } = Typography;

// 枚举选项
const LANGUAGE_STYLES = [
  { value: 'casual', label: 'Casual - 随意' },
  { value: 'formal', label: 'Formal - 正式' },
  { value: 'concise', label: 'Concise - 简洁' },
  { value: 'verbose', label: 'Verbose - 详细' },
  { value: 'technical', label: 'Technical - 技术' },
  { value: 'poetic', label: 'Poetic - 诗意' },
];

const COMMUNICATION_DISTANCES = [
  { value: 'equal', label: '平等' },
  { value: 'intimate', label: '亲密' },
  { value: 'respectful', label: '尊重' },
  { value: 'subservient', label: '服从' },
  { value: 'detached', label: '疏离' },
];

const VALUE_ALIGNMENTS = [
  { value: 'neutral_good', label: '中立善良' },
  { value: 'lawful_good', label: '守序善良' },
  { value: 'chaotic_good', label: '混乱善良' },
  { value: 'lawful_neutral', label: '守序中立' },
  { value: 'true_neutral', label: '绝对中立' },
  { value: 'chaotic_neutral', label: '混乱中立' },
];

const THINKING_STYLES = [
  { value: 'logical', label: 'Logical - 逻辑' },
  { value: 'creative', label: 'Creative - 创造' },
  { value: 'intuitive', label: 'Intuitive - 直觉' },
  { value: 'analytical', label: 'Analytical - 分析' },
];

const RISK_PREFERENCES = [
  { value: 'conservative', label: '保守' },
  { value: 'balanced', label: '平衡' },
  { value: 'adventurous', label: '冒险' },
];

const REASONING_DEPTHS = [
  { value: 'shallow', label: '浅层' },
  { value: 'medium', label: '中等' },
  { value: 'deep', label: '深层' },
];

interface PersonalityInfo {
  name: string;        // 文件名
  displayName: string; // AI名字
  role?: string;       // 角色
}

const PersonalityPage: React.FC = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [currentPersonality, setCurrentPersonality] = useState<string>('');
  const [personalities, setPersonalities] = useState<PersonalityInfo[]>([]);
  const [aiDescription, setAiDescription] = useState('');
  const [initialized, setInitialized] = useState(false);
  const [createModalVisible, setCreateModalVisible] = useState(false);

  // 切换人格相关状态
  const [pendingPersonality, setPendingPersonality] = useState<string | null>(null);
  const [pendingConfig, setPendingConfig] = useState<PersonalityConfig | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareData, setCompareData] = useState<PersonalityCompareResponse | null>(null);
  const [confirmModalVisible, setConfirmModalVisible] = useState(false);

  // 加载当前人格
  const loadCurrentPersonality = useCallback(async () => {
    try {
      const response = await personalityApi.getCurrent();
      if (response.success && response.data) {
        const current = (response.data as any).current as string;
        setCurrentPersonality(current);
        return current;
      }
      return 'default';
    } catch (error) {
      console.error('Failed to load current personality:', error);
      return 'default';
    }
  }, []);

  // 加载人格列表
  const loadPersonalities = useCallback(async () => {
    try {
      const response = await personalityApi.list();
      if (response.success && response.data) {
        const data = response.data as any;
        if (data.personalities) {
          const names = data.personalities as string[];
          const infos: PersonalityInfo[] = [];

          for (const name of names) {
            try {
              const resp = await personalityApi.get(name);
              if (resp.data && typeof resp.data === 'object' && 'core' in resp.data) {
                const core = (resp.data as any).core;
                infos.push({
                  name,
                  displayName: core?.name || name,
                  role: core?.role,
                });
              }
            } catch (error) {
              infos.push({ name, displayName: name });
            }
          }
          setPersonalities(infos);
        }
      }
    } catch (error) {
      console.error('Failed to load personalities list:', error);
    }
  }, []);

  // 加载人格配置
  const loadPersonality = useCallback(async (name: string, showMessage: boolean = false) => {
    setLoading(true);
    try {
      const response = await personalityApi.get(name);
      if (response.success && response.data) {
        form.setFieldsValue(response.data);
        if (showMessage) {
          const data = response.data as any;
          const aiName = data?.core?.name || name;
          message.success(`已加载: ${aiName}`);
        }
      }
    } catch (error) {
      message.error('加载人格配置失败');
    } finally {
      setLoading(false);
    }
  }, [form]);

  // 切换人格 - 显示确认弹窗
  const handlePersonalityChange = async (name: string) => {
    if (name === currentPersonality) return;

    setCompareLoading(true);
    try {
      // 获取比较结果
      const compareResp = await personalityApi.compare(currentPersonality, name);
      if (compareResp.success) {
        setCompareData(compareResp);
        setPendingPersonality(name);
        const data = compareResp as any;
        setPendingConfig(data.to_config || null);
        setConfirmModalVisible(true);
      }
    } catch (error) {
      message.error('获取人格差异失败');
      console.error(error);
    } finally {
      setCompareLoading(false);
    }
  };

  // 确认切换人格
  const handleConfirmSwitch = async () => {
    if (!pendingPersonality || !pendingConfig) return;

    try {
      // 先设置当前人格
      await personalityApi.setCurrent(pendingPersonality);

      // 然后加载配置
      form.setFieldsValue(pendingConfig);

      setCurrentPersonality(pendingPersonality);
      message.success(`已切换到: ${pendingConfig.core?.name || pendingPersonality}`);

      // 清理状态
      setPendingPersonality(null);
      setPendingConfig(null);
      setCompareData(null);
      setConfirmModalVisible(false);
    } catch (error) {
      message.error('切换人格失败');
    }
  };

  // 取消切换
  const handleCancelSwitch = () => {
    setPendingPersonality(null);
    setPendingConfig(null);
    setCompareData(null);
    setConfirmModalVisible(false);
  };

  // 保存人格配置
  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      // 如果有未确认的切换，先确认切换
      if (pendingPersonality && pendingConfig) {
        await personalityApi.setCurrent(pendingPersonality);
        setCurrentPersonality(pendingPersonality);
        setPendingPersonality(null);
        setPendingConfig(null);
      }

      let response;
      // 如果是默认人格或名字与AI名字不同，使用AI名字作为文件名
      if (currentPersonality === 'default' || currentPersonality !== values.core?.name) {
        response = await personalityApi.updateWithAIName(values);
        if (response.success) {
          const responseData = response.data as any;
          const actualName = responseData?.actual_name;
          if (actualName) {
            await personalityApi.setCurrent(actualName);
            setCurrentPersonality(actualName);
          }
        }
      } else {
        response = await personalityApi.update(currentPersonality, values);
      }

      if (response.success) {
        message.success('人格配置已保存');
        await loadPersonalities();
      } else {
        message.error(response.message || '保存失败');
      }
    } catch (error: any) {
      message.error(`保存失败: ${error.message || '未知错误'}`);
    } finally {
      setSaving(false);
    }
  };

  // AI生成人格配置
  const handleAIGenerate = async () => {
    if (!aiDescription.trim()) {
      message.warning('请输入AI人格描述');
      return;
    }

    setGenerating(true);
    try {
      const response = await personalityApi.generate({
        description: aiDescription,
      });

      if (response.success && response.data) {
        form.setFieldsValue(response.data);
        message.success('AI生成人格配置成功');
        setAiDescription('');
      } else {
        message.error(response.message || 'AI生成失败');
      }
    } catch (error: any) {
      message.error(`AI生成失败: ${error.message || '未知错误'}`);
    } finally {
      setGenerating(false);
    }
  };

  // 创建新人格
  const handleCreatePersonality = async () => {
    const currentValues = form.getFieldsValue();
    const aiName = currentValues.core?.name || 'AI';

    if (!aiName.trim()) {
      message.warning('请先填写AI名字');
      return;
    }

    // 检查是否已存在相同AI名字的人格
    const existingName = personalities.find(p => p.displayName === aiName)?.name;
    if (existingName) {
      message.warning(`已存在名为"${aiName}"的人格`);
      return;
    }

    try {
      // 使用AI名字保存，use_ai_name=true让后端使用AI名字作为文件名
      const response = await personalityApi.updateWithAIName(currentValues);

      if (response.success) {
        const responseData = response.data as any;
        const actualName = responseData?.actual_name || aiName;
        message.success(`新人格"${aiName}"已创建`);
        setCreateModalVisible(false);
        await loadPersonalities();
        // 切换到新创建的人格
        await personalityApi.setCurrent(actualName);
        setCurrentPersonality(actualName);
        // 重新加载配置以确认
        await loadPersonality(actualName, false);
      } else {
        message.error(response.message || '创建失败');
      }
    } catch (error) {
      message.error('创建失败');
    }
  };

  // 删除人格
  const handleDeletePersonality = async (name: string) => {
    if (name === currentPersonality) {
      message.warning('不能删除当前使用的人格');
      return;
    }

    Modal.confirm({
      title: '确认删除',
      content: `确定要删除人格"${name}"吗？此操作不可恢复。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await personalityApi.delete(name);
          message.success('人格已删除');
          loadPersonalities();
        } catch (error) {
          message.error('删除失败');
        }
      },
    });
  };

  // 重置为默认
  const handleReset = async () => {
    await loadPersonality(currentPersonality, true);
  };

  // 初始化加载
  useEffect(() => {
    if (!initialized) {
      const init = async () => {
        const current = await loadCurrentPersonality();
        await loadPersonalities();
        await loadPersonality(current, false);
        setInitialized(true);
      };
      init();
    }
  }, [initialized, loadCurrentPersonality, loadPersonality, loadPersonalities]);

  // 渲染差异列表
  const renderDiffs = () => {
    if (!compareData || (compareData as any).diffs.length === 0) {
      return <Text type="secondary">两个人格配置完全相同</Text>;
    }

    const diffs = (compareData as any).diffs as PersonalityDiff[];
    const groupedDiffs = {
      basic: diffs.filter((d: PersonalityDiff) =>
        ['name', 'role', 'backstory', 'tone', 'language_style', 'use_emoji'].includes(d.field)
      ),
      personality: diffs.filter((d: PersonalityDiff) =>
        ['communication_distance', 'value_alignment', 'traits', 'virtues', 'flaws', 'catchphrases', 'taboos', 'boundaries'].includes(d.field)
      ),
      cognition: diffs.filter((d: PersonalityDiff) =>
        ['primary_style', 'secondary_style', 'risk_preference', 'reasoning_depth', 'creativity_level', 'learning_rate', 'expertise'].includes(d.field)
      ),
    };

    return (
      <div style={{ maxHeight: 400, overflowY: 'auto' }}>
        {Object.entries(groupedDiffs).map(([group, groupDiffs]) => {
          if (groupDiffs.length === 0) return null;
          const groupTitles = { basic: '基础信息', personality: '个性特征', cognition: '认知能力' };
          return (
            <div key={group} style={{ marginBottom: 16 }}>
              <Title level={5} style={{ fontSize: 14, marginBottom: 8 }}>
                {groupTitles[group as keyof typeof groupTitles]}
              </Title>
              <List
                size="small"
                dataSource={groupDiffs}
                renderItem={(diff) => (
                  <List.Item>
                    <div style={{ width: '100%' }}>
                      <div style={{ marginBottom: 4 }}>
                        <Text strong>{diff.field_label}</Text>
                      </div>
                      <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
                        <div style={{ flex: 1 }}>
                          <Text type="secondary">当前：</Text>
                          <br />
                          <Text code style={{ color: '#cf1322' }}>
                            {formatValue(diff.old_value)}
                          </Text>
                        </div>
                        <div style={{ flex: 1 }}>
                          <Text type="secondary">切换后：</Text>
                          <br />
                          <Text code style={{ color: '#389e0d' }}>
                            {formatValue(diff.new_value)}
                          </Text>
                        </div>
                      </div>
                    </div>
                  </List.Item>
                )}
              />
            </div>
          );
        })}
      </div>
    );
  };

  // 格式化值显示
  const formatValue = (val: any): string => {
    if (val === null || val === undefined) return '（无）';
    if (Array.isArray(val)) {
      if (val.length === 0) return '（空）';
      return val.slice(0, 3).join('、') + (val.length > 3 ? '...' : '');
    }
    if (typeof val === 'object') return JSON.stringify(val, null, 2);
    return String(val);
  };

  // 渲染标签输入（带标题）
  const renderTagsInput = (
    field: string,
    label: string,
    placeholder: string,
    tooltip?: string
  ) => (
    <Form.Item name={field} label={label}>
      <Space.Compact style={{ width: '100%' }}>
        <Select
          mode="tags"
          placeholder={placeholder}
          tokenSeparators={[',', ' ']}
          style={{ flex: 1 }}
        />
        {tooltip && (
          <Tooltip title={tooltip}>
            <Button icon={<QuestionCircleOutlined />} />
          </Tooltip>
        )}
      </Space.Compact>
    </Form.Item>
  );

  const currentDisplay = personalities.find(p => p.name === currentPersonality);
  const pendingDisplay = personalities.find(p => p.name === pendingPersonality);

  return (
    <div style={{ maxWidth: '1000px', margin: '0 auto' }}>
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>AI 人格配置</h1>
        <p style={{ margin: '4px 0 0', color: '#888', fontSize: 14 }}>
          配置AI助手的人格模型，支持手动输入或使用AI生成
        </p>
      </div>

      {/* 人格选择和AI生成 */}
      <Card style={{ marginBottom: '20px', borderRadius: '8px' }} bordered={false}>
        <Row gutter={16} align="middle">
          <Col span={12}>
            <Space wrap>
              <span>当前人格：</span>
              <Select
                value={currentPersonality}
                onChange={handlePersonalityChange}
                style={{ width: 280 }}
                placeholder="选择人格"
                loading={compareLoading}
              >
                {personalities.map((p) => (
                  <Option key={p.name} value={p.name}>
                    {p.displayName} {p.role && `(${p.role})`}
                  </Option>
                ))}
              </Select>
              <Button
                icon={<PlusOutlined />}
                onClick={() => setCreateModalVisible(true)}
              >
                新建
              </Button>
              {(currentPersonality !== 'default' || personalities.length > 1) && (
                <Button
                  icon={<DeleteOutlined />}
                  danger
                  onClick={() => handleDeletePersonality(currentPersonality)}
                >
                  删除
                </Button>
              )}
            </Space>
          </Col>
          <Col span={12}>
            <Space.Compact style={{ width: '100%' }}>
              <Input
                placeholder="用一句话描述AI人格，例如：一个友善的编程助手，喜欢用幽默的方式解释复杂概念"
                value={aiDescription}
                onChange={(e) => setAiDescription(e.target.value)}
              />
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                onClick={handleAIGenerate}
                loading={generating}
              >
                AI生成
              </Button>
            </Space.Compact>
          </Col>
        </Row>
      </Card>

      <Spin spinning={loading}>
        {/* 切换警告 */}
        {pendingPersonality && (
          <Alert
            message={
              <Space>
                <ExclamationCircleOutlined />
                <span>
                  预览模式：正在显示「{pendingDisplay?.displayName}」的配置，点击下方「确认切换」后才会生效
                </span>
              </Space>
            }
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
          />
        )}

        <Form
          form={form}
          layout="vertical"
          initialValues={{
            core: {
              name: 'AI',
              role: '助手',
              backstory: '',
              language_style: 'casual',
              use_emoji: false,
              catchphrases: [],
              tone: 'friendly',
              communication_distance: 'equal',
              value_alignment: 'neutral_good',
              traits: [],
              virtues: [],
              flaws: [],
              taboos: [],
              boundaries: [],
            },
            cognition: {
              primary_style: 'logical',
              secondary_style: 'intuitive',
              risk_preference: 'balanced',
              reasoning_depth: 'medium',
              creativity_level: 0.5,
              learning_rate: 0.5,
              expertise: {},
            },
          }}
        >
          <Tabs
            defaultActiveKey="basic"
            items={[
              {
                key: 'basic',
                label: '基础信息',
                children: (
                  <Card bordered={false} style={{ borderRadius: '8px' }}>
                    <Row gutter={16}>
                      <Col span={12}>
                        <Form.Item
                          name={['core', 'name']}
                          label="AI名字"
                          rules={[{ required: true, message: '请输入AI名字' }]}
                        >
                          <Input placeholder="例如：小智、AI助手" />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item
                          name={['core', 'role']}
                          label="角色定位"
                          rules={[{ required: true, message: '请输入角色定位' }]}
                        >
                          <Input placeholder="例如：编程助手、顾问" />
                        </Form.Item>
                      </Col>
                    </Row>

                    <Form.Item name={['core', 'backstory']} label="背景故事">
                      <TextArea
                        rows={4}
                        placeholder="描述AI的背景、来历、目标等..."
                      />
                    </Form.Item>

                    <Row gutter={16}>
                      <Col span={8}>
                        <Form.Item name={['core', 'tone']} label="语调">
                          <Select placeholder="选择语调">
                            <Option value="friendly">友好</Option>
                            <Option value="professional">专业</Option>
                            <Option value="humorous">幽默</Option>
                            <Option value="serious">严肃</Option>
                            <Option value="warm">温暖</Option>
                          </Select>
                        </Form.Item>
                      </Col>
                      <Col span={8}>
                        <Form.Item name={['core', 'language_style']} label="语言风格">
                          <Select placeholder="选择风格">
                            {LANGUAGE_STYLES.map((s) => (
                              <Option key={s.value} value={s.value}>
                                {s.label}
                              </Option>
                            ))}
                          </Select>
                        </Form.Item>
                      </Col>
                      <Col span={8}>
                        <Form.Item
                          name={['core', 'use_emoji']}
                          label="使用表情符号"
                          valuePropName="checked"
                        >
                          <Switch />
                        </Form.Item>
                      </Col>
                    </Row>
                  </Card>
                ),
              },
              {
                key: 'personality',
                label: '个性特征',
                children: (
                  <Card bordered={false} style={{ borderRadius: '8px' }}>
                    <Row gutter={16}>
                      <Col span={8}>
                        <Form.Item name={['core', 'communication_distance']} label="沟通距离">
                          <Select placeholder="选择距离">
                            {COMMUNICATION_DISTANCES.map((d) => (
                              <Option key={d.value} value={d.value}>
                                {d.label}
                              </Option>
                            ))}
                          </Select>
                        </Form.Item>
                      </Col>
                      <Col span={8}>
                        <Form.Item name={['core', 'value_alignment']} label="价值观阵营">
                          <Select placeholder="选择阵营">
                            {VALUE_ALIGNMENTS.map((a) => (
                              <Option key={a.value} value={a.value}>
                                {a.label}
                              </Option>
                            ))}
                          </Select>
                        </Form.Item>
                      </Col>
                    </Row>

                    <Divider orientation="left" style={{ fontSize: 13, color: '#999' }}>个性特征</Divider>

                    {renderTagsInput(
                      ['core', 'traits'],
                      '个性标签',
                      '添加性格特征，如：友善、好奇、耐心',
                      '描述AI的主要性格特点'
                    )}
                    {renderTagsInput(
                      ['core', 'virtues'],
                      '优点美德',
                      '添加优点，如：同理心、诚实、勤奋',
                      'AI的优点和美德'
                    )}
                    {renderTagsInput(
                      ['core', 'flaws'],
                      '缺点弱点',
                      '添加缺点，如：想太多、分心',
                      'AI的缺点和不完美之处'
                    )}

                    <Divider orientation="left" style={{ fontSize: 13, color: '#999' }}>语言习惯</Divider>

                    {renderTagsInput(
                      ['core', 'catchphrases'],
                      '口头禅',
                      '添加口头禅，如：让我想想、有意思',
                      'AI常说的标志性话语'
                    )}

                    <Divider orientation="left" style={{ fontSize: 13, color: '#999' }}>行为约束</Divider>

                    {renderTagsInput(
                      ['core', 'taboos'],
                      '禁忌话题',
                      '添加禁忌，如：暴力内容、歧视',
                      'AI绝对不讨论的话题'
                    )}
                    {renderTagsInput(
                      ['core', 'boundaries'],
                      '行为边界',
                      '添加边界，如：尊重隐私、遵循道德',
                      'AI的行为准则和底线'
                    )}
                  </Card>
                ),
              },
              {
                key: 'cognition',
                label: '认知能力',
                children: (
                  <Card bordered={false} style={{ borderRadius: '8px' }}>
                    <Row gutter={16}>
                      <Col span={12}>
                        <Form.Item name={['cognition', 'primary_style']} label="主要思维风格">
                          <Select placeholder="选择主要风格">
                            {THINKING_STYLES.map((s) => (
                              <Option key={s.value} value={s.value}>
                                {s.label}
                              </Option>
                            ))}
                          </Select>
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name={['cognition', 'secondary_style']} label="次要思维风格">
                          <Select placeholder="选择次要风格">
                            {THINKING_STYLES.map((s) => (
                              <Option key={s.value} value={s.value}>
                                {s.label}
                              </Option>
                            ))}
                          </Select>
                        </Form.Item>
                      </Col>
                    </Row>

                    <Row gutter={16}>
                      <Col span={8}>
                        <Form.Item name={['cognition', 'risk_preference']} label="风险偏好">
                          <Select placeholder="选择风险偏好">
                            {RISK_PREFERENCES.map((r) => (
                              <Option key={r.value} value={r.value}>
                                {r.label}
                              </Option>
                            ))}
                          </Select>
                        </Form.Item>
                      </Col>
                      <Col span={8}>
                        <Form.Item name={['cognition', 'reasoning_depth']} label="推理深度">
                          <Select placeholder="选择深度">
                            {REASONING_DEPTHS.map((d) => (
                              <Option key={d.value} value={d.value}>
                                {d.label}
                              </Option>
                            ))}
                          </Select>
                        </Form.Item>
                      </Col>
                      <Col span={8}>
                        <Form.Item name={['cognition', 'creativity_level']} label="创造力水平">
                          <Slider
                            min={0}
                            max={1}
                            step={0.1}
                            marks={{ 0: '0%', 0.5: '50%', 1: '100%' }}
                          />
                        </Form.Item>
                      </Col>
                    </Row>

                    <Form.Item name={['cognition', 'learning_rate']} label="学习速率">
                      <Slider
                        min={0}
                        max={1}
                        step={0.1}
                        marks={{ 0: '慢', 0.5: '中', 1: '快' }}
                      />
                    </Form.Item>

                    <Divider orientation="left" style={{ fontSize: 13, color: '#999' }}>领域专精</Divider>
                    <Alert
                      message="领域专精配置"
                      description="格式：领域名:等级，例如 coding:0.9（等级范围0-1）"
                      type="info"
                      showIcon
                      style={{ marginBottom: 16 }}
                    />
                    <Form.Item name={['cognition', 'expertise']} label="专精领域">
                      <Select
                        mode="tags"
                        placeholder="添加领域专精，格式：领域名:等级，例如 coding:0.9"
                        tokenSeparators={[',', ' ']}
                        options={[
                          { label: 'coding:0.9', value: 'coding:0.9' },
                          { label: 'writing:0.8', value: 'writing:0.8' },
                          { label: 'analysis:0.85', value: 'analysis:0.85' },
                          { label: 'reasoning:0.9', value: 'reasoning:0.9' },
                          { label: 'creative:0.7', value: 'creative:0.7' },
                        ]}
                        style={{ textAlign: 'left' }}
                      />
                    </Form.Item>
                  </Card>
                ),
              },
            ]}
          />
        </Form>
      </Spin>

      {/* 保存按钮 */}
      <div style={{ marginTop: '16px', textAlign: 'center' }}>
        {pendingPersonality && (
          <Alert
            message="切换人格说明"
            description="切换人格不会影响已有的记忆数据，但会改变AI的回复风格、行为模式和操作经验。切换后AI将使用新的人格配置与您交互。"
            type="info"
            showIcon
            style={{ marginBottom: 16, textAlign: 'left' }}
          />
        )}
        <Space>
          <Button icon={<ReloadOutlined />} onClick={handleReset}>
            重置
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSave}
            loading={saving}
            size="large"
          >
            保存配置
          </Button>
        </Space>
      </div>

      {/* 确认切换弹窗 */}
      <Modal
        title={
          <Space>
            <DiffOutlined />
            <span>确认切换人格</span>
          </Space>
        }
        open={confirmModalVisible}
        onOk={handleConfirmSwitch}
        onCancel={handleCancelSwitch}
        okText="确认切换"
        cancelText="取消"
        width={600}
        okButtonProps={{ icon: <CheckOutlined /> }}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <div>
            <Text strong>从：</Text>
            <Tag color="default" style={{ marginLeft: 8 }}>
              {compareData?.from_config?.core?.name || currentPersonality}
            </Tag>
          </div>
          <div>
            <Text strong>到：</Text>
            <Tag color="blue" style={{ marginLeft: 8 }}>
              {compareData?.to_config?.core?.name || pendingPersonality}
            </Tag>
          </div>
          <Divider style={{ margin: '8px 0' }} />
          <div>
            <Text type="secondary">
              找到 {compareData?.diffs.length || 0} 处不同配置
            </Text>
          </div>
          {renderDiffs()}
        </Space>
      </Modal>

      {/* 创建新人格对话框 */}
      <Modal
        title="创建新人格"
        open={createModalVisible}
        onOk={handleCreatePersonality}
        onCancel={() => {
          setCreateModalVisible(false);
        }}
        okText="创建"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text>将使用当前表单中的「AI名字」作为新人格的文件名。</Text>
          <Alert
            message="确认创建"
            description={`新人格将使用当前表单配置创建，AI名字为「${form.getFieldValue(['core', 'name']) || '未设置'}」`}
            type="info"
            showIcon
          />
        </Space>
      </Modal>
    </div>
  );
};

export default PersonalityPage;
