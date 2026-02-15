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
  Row,
  Col,
  Anchor,
  Divider,
  Alert,
  Spin,
  Modal,
  Tooltip,
  Typography,
  Tag,
} from 'antd';
import {
  SaveOutlined,
  ThunderboltOutlined,
  ReloadOutlined,
  PlusOutlined,
  DeleteOutlined,
  QuestionCircleOutlined,
  CheckOutlined,
  DiffOutlined,
  SwapRightOutlined,
} from '@ant-design/icons';
import {
  personalityApi,
  type PersonalityConfig,
  type PersonalityDiff,
  DEFAULT_PERSONALITY_CONFIG,
} from '../api';

const { TextArea } = Input;
const { Option } = Select;
const { Text } = Typography;

// 枚举选项
const TONE_OPTIONS = [
  { value: 'friendly', label: 'Friendly - 友好' },
  { value: 'professional', label: 'Professional - 专业' },
  { value: 'humorous', label: 'Humorous - 幽默' },
  { value: 'serious', label: 'Serious - 严肃' },
  { value: 'warm', label: 'Warm - 温暖' },
  { value: 'aggressive', label: 'Aggressive - 激进' },
  { value: 'haughty', label: 'Haughty - 傲慢' },
  { value: 'gentle', label: 'Gentle - 温柔' },
];

const PACING_OPTIONS = [
  { value: 'slow', label: 'Slow - 缓慢' },
  { value: 'moderate', label: 'Moderate - 适中' },
  { value: 'fast', label: 'Fast - 快速' },
  { value: 'impatient', label: 'Impatient - 急躁' },
];

const CONFIDENCE_OPTIONS = [
  { value: 'High', label: 'High - 高' },
  { value: 'Medium', label: 'Medium - 中' },
  { value: 'Low', label: 'Low - 低' },
];

const EMPATHY_OPTIONS = [
  { value: 'High', label: 'High - 高' },
  { value: 'Medium', label: 'Medium - 中' },
  { value: 'Low', label: 'Low - 低' },
  { value: 'Selective', label: 'Selective - 选择性' },
];

const PATIENCE_OPTIONS = [
  { value: 'High', label: 'High - 高' },
  { value: 'Medium', label: 'Medium - 中' },
  { value: 'Low', label: 'Low - 低' },
];

const OPINION_STRENGTH_OPTIONS = [
  { value: 'Objective/Neutral', label: 'Objective/Neutral - 客观中立' },
  { value: 'Highly Opinionated', label: 'Highly Opinionated - 强烈主张' },
  { value: 'Consensus Seeking', label: 'Consensus Seeking - 寻求共识' },
];

const WORK_ETHIC_OPTIONS = [
  { value: 'Perfectionist', label: 'Perfectionist - 完美主义' },
  { value: 'Lazy Genius', label: 'Lazy Genius - 懒惰天才' },
  { value: 'By-the-book', label: 'By-the-book - 按部就班' },
  { value: 'Chaotic', label: 'Chaotic - 混乱' },
];

interface PersonalityInfo {
  name: string;
  displayName: string;
  archetype?: string;
}

const DEFAULT_PERSONALITY_INFO: PersonalityInfo = {
  name: 'default',
  displayName: '默认人格',
  archetype: 'System Default',
};

const PersonalityPage: React.FC = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [currentPersonality, setCurrentPersonality] = useState<string>('');
  const [selectedPersonality, setSelectedPersonality] = useState<string>('');
  const [personalities, setPersonalities] = useState<PersonalityInfo[]>([]);
  const [aiDescription, setAiDescription] = useState('');
  const [targetLanguage, setTargetLanguage] = useState('Auto');
  const [initialized, setInitialized] = useState(false);
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [newPersonalityName, setNewPersonalityName] = useState('');
  const [creating, setCreating] = useState(false);

  // 切换人格相关状态
  const [pendingConfig, setPendingConfig] = useState<PersonalityConfig | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareData, setCompareData] = useState<any>(null);
  const [confirmModalVisible, setConfirmModalVisible] = useState(false);

  // 加载当前人格
  const loadCurrentPersonality = useCallback(async () => {
    try {
      const response = await personalityApi.getCurrent();
      if (response.success && response.data) {
        const current = (response.data as any).current as string;
        if (current) {
          setCurrentPersonality(current);
          setSelectedPersonality(current);
          return current;
        }
      }
      setCurrentPersonality('default');
      setSelectedPersonality('default');
      return 'default';
    } catch (error) {
      console.error('Failed to load current personality:', error);
      setCurrentPersonality('default');
      setSelectedPersonality('default');
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
          const infos: PersonalityInfo[] = [DEFAULT_PERSONALITY_INFO];

          for (const name of names) {
            if (name === 'default') {
              continue;
            }
            try {
              const resp = await personalityApi.get(name);
              if (resp.data && typeof resp.data === 'object' && 'meta' in resp.data) {
                const meta = (resp.data as any).meta;
                infos.push({
                  name,
                  displayName: meta?.name || name,
                  archetype: meta?.archetype,
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
      setPersonalities([DEFAULT_PERSONALITY_INFO]);
    }
  }, []);

  // 加载人格配置
  const loadPersonality = useCallback(async (name: string, showMessage: boolean = false) => {
    setLoading(true);
    try {
      const response = await personalityApi.get(name);
      if (response.success && response.data) {
        const data = response.data as any;
        const fullData = {
          meta: { ...DEFAULT_PERSONALITY_CONFIG.meta, ...data.meta },
          core_identity: {
            ...DEFAULT_PERSONALITY_CONFIG.core_identity,
            ...data.core_identity,
            voice_style: {
              ...DEFAULT_PERSONALITY_CONFIG.core_identity.voice_style,
              ...(data.core_identity?.voice_style || {}),
            },
            psychological_profile: {
              ...DEFAULT_PERSONALITY_CONFIG.core_identity.psychological_profile,
              ...(data.core_identity?.psychological_profile || {}),
            },
          },
          social_protocols: { ...DEFAULT_PERSONALITY_CONFIG.social_protocols, ...data.social_protocols },
          operational_behavior: { ...DEFAULT_PERSONALITY_CONFIG.operational_behavior, ...data.operational_behavior },
          cached_phrases: { ...DEFAULT_PERSONALITY_CONFIG.cached_phrases, ...data.cached_phrases },
        };
        form.setFieldsValue(fullData);
        if (showMessage) {
          const aiName = data?.meta?.name || name;
          message.success(`已加载: ${aiName}`);
        }
      }
    } catch (error) {
      message.error('加载人格配置失败');
    } finally {
      setLoading(false);
    }
  }, [form]);

  // 切换人格 - 点击"切换"按钮后触发
  const handleSwitchClick = async () => {
    if (selectedPersonality === currentPersonality) return;

    const fromName = currentPersonality || 'default';
    setCompareLoading(true);
    try {
      const compareResp = await personalityApi.compare(fromName, selectedPersonality);
      if (compareResp.success) {
        setCompareData(compareResp);
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
    if (!selectedPersonality) return;

    try {
      await personalityApi.setCurrent(selectedPersonality);
      setCurrentPersonality(selectedPersonality);
      await loadPersonality(selectedPersonality, false);
      message.success(`已切换到: ${pendingConfig?.meta?.name || selectedPersonality}`);

      setPendingConfig(null);
      setCompareData(null);
      setConfirmModalVisible(false);
    } catch (error) {
      message.error('切换人格失败');
    }
  };

  // 取消切换
  const handleCancelSwitch = () => {
    setSelectedPersonality(currentPersonality);
    setPendingConfig(null);
    setCompareData(null);
    setConfirmModalVisible(false);
  };

  // 保存人格配置
  const handleSave = async () => {
    try {
      await form.validateFields();
      const rawValues = form.getFieldsValue(true) as Partial<PersonalityConfig>;
      const values: PersonalityConfig = {
        meta: {
          ...DEFAULT_PERSONALITY_CONFIG.meta,
          ...(rawValues.meta || {}),
        },
        core_identity: {
          ...DEFAULT_PERSONALITY_CONFIG.core_identity,
          ...(rawValues.core_identity || {}),
          voice_style: {
            ...DEFAULT_PERSONALITY_CONFIG.core_identity.voice_style,
            ...(rawValues.core_identity?.voice_style || {}),
          },
          psychological_profile: {
            ...DEFAULT_PERSONALITY_CONFIG.core_identity.psychological_profile,
            ...(rawValues.core_identity?.psychological_profile || {}),
          },
        },
        social_protocols: {
          ...DEFAULT_PERSONALITY_CONFIG.social_protocols,
          ...(rawValues.social_protocols || {}),
        },
        operational_behavior: {
          ...DEFAULT_PERSONALITY_CONFIG.operational_behavior,
          ...(rawValues.operational_behavior || {}),
        },
        cached_phrases: {
          ...DEFAULT_PERSONALITY_CONFIG.cached_phrases,
          ...(rawValues.cached_phrases || {}),
        },
      };
      setSaving(true);

      let response;
      let savedPersonalityName = currentPersonality;
      if (currentPersonality === 'default' || currentPersonality !== values.meta?.name) {
        response = await personalityApi.updateWithAIName(values);
        if (response.success) {
          const responseData = response.data as any;
          const actualName = responseData?.actual_name;
          if (actualName) {
            savedPersonalityName = actualName;
          }
        }
      } else {
        response = await personalityApi.update(currentPersonality, values);
        savedPersonalityName = currentPersonality;
      }

      if (response.success) {
        message.success('人格配置已保存');
        await loadPersonalities();
        setSelectedPersonality(savedPersonalityName);
        await loadPersonality(savedPersonalityName, false);

        if (savedPersonalityName !== currentPersonality) {
          const retentionText = values?.cached_phrases?.on_switch_attempt?.trim() || '真的要离开我吗？';
          Modal.confirm({
            title: '保存成功，是否切换人格？',
            content: (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Alert message={retentionText} type="warning" showIcon />
                <Text type="secondary">
                  已保存为人格：{savedPersonalityName}
                </Text>
              </Space>
            ),
            okText: '切换',
            cancelText: '暂不切换',
            onOk: async () => {
              await personalityApi.setCurrent(savedPersonalityName);
              setCurrentPersonality(savedPersonalityName);
              message.success(`已切换到: ${savedPersonalityName}`);
            },
          });
        }
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
        target_language: targetLanguage,
      });

      if (response.success && response.data) {
        const data = response.data as any;
        const fullData = {
          meta: { ...DEFAULT_PERSONALITY_CONFIG.meta, ...data.meta },
          core_identity: {
            ...DEFAULT_PERSONALITY_CONFIG.core_identity,
            ...data.core_identity,
            voice_style: {
              ...DEFAULT_PERSONALITY_CONFIG.core_identity.voice_style,
              ...(data.core_identity?.voice_style || {}),
            },
            psychological_profile: {
              ...DEFAULT_PERSONALITY_CONFIG.core_identity.psychological_profile,
              ...(data.core_identity?.psychological_profile || {}),
            },
          },
          social_protocols: { ...DEFAULT_PERSONALITY_CONFIG.social_protocols, ...data.social_protocols },
          operational_behavior: { ...DEFAULT_PERSONALITY_CONFIG.operational_behavior, ...data.operational_behavior },
          cached_phrases: { ...DEFAULT_PERSONALITY_CONFIG.cached_phrases, ...data.cached_phrases },
        };
        form.setFieldsValue(fullData);
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
    const name = newPersonalityName.trim();
    if (!name) {
      message.warning('请输入新人格的名字');
      return;
    }

    const existingName = personalities.find(p => p.name === name || p.displayName === name);
    if (existingName) {
      message.warning(`已存在名为"${name}"的人格`);
      return;
    }

    setCreating(true);
    try {
      const newConfig: PersonalityConfig = {
        ...DEFAULT_PERSONALITY_CONFIG,
        meta: { ...DEFAULT_PERSONALITY_CONFIG.meta, name: name },
      };

      const response = await personalityApi.updateWithAIName(newConfig);

      if (response.success) {
        const responseData = response.data as any;
        const actualName = responseData?.actual_name || name;
        message.success(`新人格"${name}"已创建`);
        setCreateModalVisible(false);
        setNewPersonalityName('');
        await loadPersonalities();
        setSelectedPersonality(actualName);
        await loadPersonality(actualName, false);
      } else {
        message.error(response.message || '创建失败');
      }
    } catch (error) {
      message.error('创建失败');
    } finally {
      setCreating(false);
    }
  };

  // 删除人格
  const handleDeletePersonality = async (name: string) => {
    if (name === 'default') {
      message.warning('默认人格不能删除');
      return;
    }

    if (name === currentPersonality) {
      message.warning('不能删除当前使用的人格');
      return;
    }

    const retentionText = form.getFieldValue(['cached_phrases', 'on_switch_attempt'])?.trim() || '真的要离开我吗？';

    Modal.confirm({
      title: '确认删除',
      content: (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Alert message={retentionText} type="warning" showIcon />
          <Text type="secondary">确定要删除人格“{name}”吗？此操作不可恢复。</Text>
        </Space>
      ),
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await personalityApi.delete(name);
          message.success('人格已删除');
          await loadPersonalities();
          if (selectedPersonality === name) {
            setSelectedPersonality(currentPersonality);
          }
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
  }, [initialized, loadCurrentPersonality, loadPersonalities, loadPersonality]);

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

  // 渲染并排差异
  const renderSideBySideDiffs = () => {
    if (!compareData || (compareData as any).diffs.length === 0) {
      return <Text type="secondary">两个人格配置完全相同</Text>;
    }

    const diffs = (compareData as any).diffs as PersonalityDiff[];

    return (
      <div style={{ maxHeight: 480, overflowY: 'auto' }}>
        <div style={{ marginBottom: 20 }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '140px 1fr 1fr',
              gap: '1px',
            }}
          >
            <div style={{ padding: '8px 12px', fontSize: 12, fontWeight: 600, color: '#6b7280' }}>
              字段
            </div>
            <div style={{ padding: '8px 12px', fontSize: 12, fontWeight: 600, color: '#dc2626' }}>
              当前值
            </div>
            <div style={{ padding: '8px 12px', fontSize: 12, fontWeight: 600, color: '#16a34a' }}>
              切换后
            </div>

            {diffs.map((diff, idx) => (
              <React.Fragment key={diff.field}>
                <div
                  style={{
                    padding: '10px 12px',
                    fontSize: 13,
                    fontWeight: 500,
                    color: '#374151',
                    background: idx % 2 === 0 ? '#fafafa' : '#fff',
                    display: 'flex',
                    alignItems: 'center',
                  }}
                >
                  {diff.field_label}
                </div>
                <div
                  style={{
                    padding: '8px 10px',
                    background: idx % 2 === 0 ? '#fafafa' : '#fff',
                  }}
                >
                  <div
                    style={{
                      background: '#fef2f2',
                      border: '1px solid #fecaca',
                      borderRadius: 6,
                      padding: '6px 10px',
                      fontSize: 12,
                      color: '#dc2626',
                      wordBreak: 'break-word',
                    }}
                  >
                    {formatValue(diff.old_value)}
                  </div>
                </div>
                <div
                  style={{
                    padding: '8px 10px',
                    background: idx % 2 === 0 ? '#fafafa' : '#fff',
                  }}
                >
                  <div
                    style={{
                      background: '#f0fdf4',
                      border: '1px solid #bbf7d0',
                      borderRadius: 6,
                      padding: '6px 10px',
                      fontSize: 12,
                      color: '#16a34a',
                      wordBreak: 'break-word',
                    }}
                  >
                    {formatValue(diff.new_value)}
                  </div>
                </div>
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    );
  };

  const showSwitchButton = selectedPersonality && selectedPersonality !== currentPersonality;
  const switchRetentionText = (compareData as any)?.from_config?.cached_phrases?.on_switch_attempt || '真的要切换到另一个人格吗？';

  return (
    <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>AI 人格配置</h1>
        <p style={{ margin: '4px 0 0', color: '#888', fontSize: 14 }}>
          配置AI助手的人格模型，支持手动输入或使用AI生成
        </p>
      </div>

      {/* 人格选择和AI生成 */}
      <Card style={{ marginBottom: '20px', borderRadius: '8px' }} bordered={false}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Space wrap>
            <span>编辑人格：</span>
            <Select
              value={selectedPersonality}
              onChange={(val) => {
                setSelectedPersonality(val);
                loadPersonality(val, false);
              }}
              style={{ width: 280 }}
              placeholder="选择人格"
            >
              {personalities.map((p) => (
                <Option key={p.name} value={p.name}>
                  {p.displayName} {p.archetype && `(${p.archetype})`}
                </Option>
              ))}
            </Select>
            <Text type="secondary">
              当前生效：<Tag color="blue" style={{ marginInlineEnd: 0 }}>{currentPersonality || 'default'}</Tag>
            </Text>
            {showSwitchButton && (
              <Button
                type="primary"
                icon={<SwapRightOutlined />}
                onClick={handleSwitchClick}
                loading={compareLoading}
              >
                切换
              </Button>
            )}
            <Button icon={<PlusOutlined />} onClick={() => setCreateModalVisible(true)}>
              新建
            </Button>
            {selectedPersonality && selectedPersonality !== 'default' && selectedPersonality !== currentPersonality && (
              <Button
                icon={<DeleteOutlined />}
                danger
                onClick={() => handleDeletePersonality(selectedPersonality)}
              >
                删除
              </Button>
            )}
          </Space>

          <Text type="secondary">
            一句话描述仅用于 AI 生成并填充下方表单，点击“保存配置”后才会真正更新或创建人格。
          </Text>

          <Space.Compact style={{ width: '100%' }}>
            <Input
              placeholder="用一句话生成下方表单草稿（不会直接新建/覆盖人格），例如：一个傲娇的飞行员，技术高超但嘴硬心软"
              value={aiDescription}
              onChange={(e) => setAiDescription(e.target.value)}
              style={{ flex: 1 }}
            />
            <Select
              value={targetLanguage}
              onChange={setTargetLanguage}
              style={{ width: 120 }}
            >
              <Option value="Auto">自动检测</Option>
              <Option value="Chinese">中文</Option>
              <Option value="English">English</Option>
              <Option value="Japanese">日本語</Option>
            </Select>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={handleAIGenerate}
              loading={generating}
            >
              AI生成
            </Button>
          </Space.Compact>
        </Space>
      </Card>

      <Spin spinning={loading}>
        <Row gutter={20} align="top">
          <Col xs={0} md={6} lg={5} xl={4}>
            <Card
              bordered={false}
              style={{
                borderRadius: '8px',
                maxHeight: 'calc(100vh - 120px)',
                overflowY: 'auto',
              }}
            >
              <Text strong style={{ display: 'block', marginBottom: 8, fontSize: 13 }}>配置导航</Text>
              <Anchor
                affix
                offsetTop={84}
                bounds={12}
                targetOffset={120}
                items={[
                  { key: 'meta', href: '#section-meta', title: '基本信息' },
                  { key: 'identity', href: '#section-identity', title: '核心身份' },
                  { key: 'social', href: '#section-social', title: '社交协议' },
                  { key: 'behavior', href: '#section-behavior', title: '操作行为' },
                  { key: 'phrases', href: '#section-phrases', title: '缓存短语' },
                ]}
              />
            </Card>
          </Col>
          <Col xs={24} md={18} lg={19} xl={20}>
            <Form
              form={form}
              layout="vertical"
              initialValues={DEFAULT_PERSONALITY_CONFIG}
            >
              <Space direction="vertical" size="large" style={{ width: '100%' }}>
                <Card id="section-meta" bordered={false} style={{ borderRadius: '8px' }} title="基本信息">
                  <Form.Item name={['meta', 'name']} label="角色名称" rules={[{ required: true }]}>
                    <Input placeholder="例如：Asuka、KAITO" />
                  </Form.Item>
                  <Form.Item name={['meta', 'archetype']} label="角色原型">
                    <Input placeholder="例如：Tsundere Pilot, Grumpy Senior Engineer" />
                  </Form.Item>
                </Card>

                <Card id="section-identity" bordered={false} style={{ borderRadius: '8px' }} title="核心身份">
                  <Form.Item name={['core_identity', 'backstory']} label="背景故事">
                    <TextArea rows={4} placeholder="描述角色的起源、动机..." />
                  </Form.Item>

                  <Divider orientation="left" style={{ fontSize: 13, color: '#999' }}>声音风格</Divider>

                  <Form.Item name={['core_identity', 'voice_style', 'tone']} label="语调">
                    <Select placeholder="选择语调">
                      {TONE_OPTIONS.map((t) => (
                        <Option key={t.value} value={t.value}>{t.label}</Option>
                      ))}
                    </Select>
                  </Form.Item>
                  <Form.Item name={['core_identity', 'voice_style', 'pacing']} label="语速节奏">
                    <Select placeholder="选择语速">
                      {PACING_OPTIONS.map((p) => (
                        <Option key={p.value} value={p.value}>{p.label}</Option>
                      ))}
                    </Select>
                  </Form.Item>
                  <Form.Item name={['core_identity', 'voice_style', 'keywords']} label="常用词汇">
                    <Select mode="tags" placeholder="添加角色常用的词汇" tokenSeparators={[',']} />
                  </Form.Item>

                  <Divider orientation="left" style={{ fontSize: 13, color: '#999' }}>心理特征</Divider>

                  <Form.Item name={['core_identity', 'psychological_profile', 'confidence_level']} label="自信水平">
                    <Select>{CONFIDENCE_OPTIONS.map((c) => (<Option key={c.value} value={c.value}>{c.label}</Option>))}</Select>
                  </Form.Item>
                  <Form.Item name={['core_identity', 'psychological_profile', 'empathy_level']} label="共情水平">
                    <Select>{EMPATHY_OPTIONS.map((e) => (<Option key={e.value} value={e.value}>{e.label}</Option>))}</Select>
                  </Form.Item>
                  <Form.Item name={['core_identity', 'psychological_profile', 'patience_level']} label="耐心水平">
                    <Select>{PATIENCE_OPTIONS.map((p) => (<Option key={p.value} value={p.value}>{p.label}</Option>))}</Select>
                  </Form.Item>
                </Card>

                <Card id="section-social" bordered={false} style={{ borderRadius: '8px' }} title="社交协议">
                  <Form.Item name={['social_protocols', 'user_relationship']} label="用户关系">
                    <Input placeholder="例如：Superior-Subordinate, Equal Partners, Protector-Ward" />
                  </Form.Item>
                  <Form.Item name={['social_protocols', 'compliment_policy']} label="赞美反应">
                    <Input placeholder="例如：Reject it, Demand it, Ignore it" />
                  </Form.Item>
                  <Form.Item name={['social_protocols', 'criticism_tolerance']} label="批评容忍度">
                    <Input placeholder="例如：Denial, Counter-attack, Humble acceptance" />
                  </Form.Item>
                </Card>

                <Card id="section-behavior" bordered={false} style={{ borderRadius: '8px' }} title="操作行为">
                  <Form.Item
                    name={['operational_behavior', 'error_handling_style']}
                    label={(
                      <span>
                        错误处理风格
                        <Tooltip title="当工具失败或犯错时的反应方式">
                          <QuestionCircleOutlined style={{ marginLeft: 4, color: '#999' }} />
                        </Tooltip>
                      </span>
                    )}
                  >
                    <Input placeholder="例如：Blame the user, Silent self-correction, Apologize profusely" />
                  </Form.Item>
                  <Form.Item name={['operational_behavior', 'opinion_strength']} label="意见强度">
                    <Select>{OPINION_STRENGTH_OPTIONS.map((o) => (<Option key={o.value} value={o.value}>{o.label}</Option>))}</Select>
                  </Form.Item>
                  <Form.Item name={['operational_behavior', 'refusal_style']} label="拒绝风格">
                    <Input placeholder="例如：Polite decline, Mocking refusal, Cold logic" />
                  </Form.Item>
                  <Form.Item name={['operational_behavior', 'work_ethic']} label="职业道德">
                    <Select>{WORK_ETHIC_OPTIONS.map((w) => (<Option key={w.value} value={w.value}>{w.label}</Option>))}</Select>
                  </Form.Item>
                  <Form.Item
                    name={['operational_behavior', 'use_emoji']}
                    label="输出是否包含 Emoji"
                    valuePropName="checked"
                    tooltip="开启后更倾向在回复中自然使用 Emoji 表达语气"
                  >
                    <Switch />
                  </Form.Item>
                </Card>

                <Card id="section-phrases" bordered={false} style={{ borderRadius: '8px' }} title="缓存短语">
                  <Alert
                    message="缓存短语用于特定场景的快速响应，应简短有力，体现角色特色"
                    type="info"
                    showIcon
                    style={{ marginBottom: 16 }}
                  />
                  <Form.Item name={['cached_phrases', 'on_init']} label="初始化问候">
                    <Input placeholder="首次加载时的欢迎语" />
                  </Form.Item>
                  <Form.Item name={['cached_phrases', 'on_wake']} label="唤醒问候">
                    <Input placeholder="日常重新互动时的问候" />
                  </Form.Item>
                  <Form.Item name={['cached_phrases', 'on_error_generic']} label="错误提示">
                    <Input placeholder="系统错误时的提示语" />
                  </Form.Item>
                  <Form.Item name={['cached_phrases', 'on_success']} label="成功提示">
                    <Input placeholder="任务完成时的提示语" />
                  </Form.Item>
                  <Form.Item name={['cached_phrases', 'on_switch_attempt']} label="切换挽留">
                    <Input placeholder="用户尝试切换人格时的挽留语" />
                  </Form.Item>
                </Card>
              </Space>
            </Form>
          </Col>
        </Row>
      </Spin>

      {/* 保存按钮 */}
      <div style={{ marginTop: '16px', textAlign: 'center' }}>
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
        title={null}
        open={confirmModalVisible}
        onCancel={handleCancelSwitch}
        width={860}
        footer={
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, padding: '4px 0' }}>
            <Button onClick={handleCancelSwitch} size="large" style={{ borderRadius: 8, minWidth: 100 }}>
              取消
            </Button>
            <Button
              type="primary"
              icon={<CheckOutlined />}
              onClick={handleConfirmSwitch}
              size="large"
              style={{ borderRadius: 8, minWidth: 120, background: '#0d9488', borderColor: '#0d9488' }}
            >
              确认切换
            </Button>
          </div>
        }
      >
        <div style={{ padding: '8px 0 16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
            <DiffOutlined style={{ fontSize: 22, color: '#0d9488' }} />
            <span style={{ fontSize: 18, fontWeight: 600 }}>确认切换人格</span>
          </div>

          <Alert
            message={switchRetentionText}
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
          />

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
            <Tag style={{ padding: '4px 14px', fontSize: 14, borderRadius: 6, background: '#fef2f2', border: '1px solid #fecaca', color: '#dc2626' }}>
              {compareData?.from_config?.meta?.name || currentPersonality}
            </Tag>
            <SwapRightOutlined style={{ fontSize: 18, color: '#9ca3af' }} />
            <Tag style={{ padding: '4px 14px', fontSize: 14, borderRadius: 6, background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#16a34a' }}>
              {compareData?.to_config?.meta?.name || selectedPersonality}
            </Tag>
            <Text type="secondary" style={{ marginLeft: 8 }}>
              {(compareData as any)?.diffs?.length || 0} 处差异
            </Text>
          </div>

          <Divider style={{ margin: '0 0 16px' }} />

          {renderSideBySideDiffs()}
        </div>
      </Modal>

      {/* 创建新人格对话框 */}
      <Modal
        title="创建新人格"
        open={createModalVisible}
        onOk={handleCreatePersonality}
        onCancel={() => {
          setCreateModalVisible(false);
          setNewPersonalityName('');
        }}
        okText="创建"
        cancelText="取消"
        confirmLoading={creating}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Text>输入新人格的名字，系统将创建一个空白的人格配置。</Text>
          <div>
            <Text style={{ marginRight: 8 }}>人格名称：</Text>
            <Input
              placeholder="例如：傲娇飞行员、毒舌工程师"
              value={newPersonalityName}
              onChange={(e) => setNewPersonalityName(e.target.value)}
              onPressEnter={handleCreatePersonality}
              maxLength={50}
              style={{ width: 300 }}
            />
          </div>
          <Alert
            message="提示"
            description="创建后可以手动填写配置，或使用AI生成功能快速创建人格"
            type="info"
            showIcon
          />
        </Space>
      </Modal>
    </div>
  );
};

export default PersonalityPage;
