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
  Tag,
  Row,
  Col,
  Divider,
  Alert,
  Spin,
  Modal,
  Tooltip,
  Typography,
} from 'antd';
import {
  SaveOutlined,
  ThunderboltOutlined,
  ReloadOutlined,
  PlusOutlined,
  DeleteOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';
import { personalityApi, type PersonalityConfig, type CorePersonality } from '../api';

const { TextArea } = Input;
const { Option } = Select;
const { Text } = Typography;

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
  const [currentPersonality, setCurrentPersonality] = useState<string>('default');
  const [personalities, setPersonalities] = useState<PersonalityInfo[]>([]);
  const [aiDescription, setAiDescription] = useState('');
  const [initialized, setInitialized] = useState(false);
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [newPersonalityName, setNewPersonalityName] = useState('');

  // 加载人格列表
  const loadPersonalities = useCallback(async () => {
    try {
      const response = await personalityApi.list();
      if (response.success) {
        // 从多个来源获取人格信息
        const names = ['default', 'technical', 'steve', 'asuka']; // TODO: 从API获取完整列表
        const infos: PersonalityInfo[] = [];

        for (const name of names) {
          try {
            const resp = await personalityApi.get(name);
            if (resp.data?.core) {
              infos.push({
                name,
                displayName: resp.data.core.name || name,
                role: resp.data.core.role,
              });
            }
          } catch {
            // 如果加载失败，使用文件名
            infos.push({ name, displayName: name });
          }
        }
        setPersonalities(infos);
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
          const aiName = response.data.core?.name || name;
          message.success(`已加载: ${aiName}`);
        }
      }
    } catch (error) {
      message.error('加载人格配置失败');
    } finally {
      setLoading(false);
    }
  }, [form]);

  // 保存人格配置
  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      const response = await personalityApi.update(currentPersonality, values);

      if (response.success) {
        message.success('人格配置已保存');
        // 重新加载列表以更新显示名称
        loadPersonalities();
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
    if (!newPersonalityName.trim()) {
      message.warning('请输入人格名称');
      return;
    }

    // 检查是否已存在
    if (personalities.some(p => p.name === newPersonalityName)) {
      message.error('该人格名称已存在');
      return;
    }

    // 获取当前表单数据作为新人格的初始值
    const currentValues = form.getFieldsValue();

    try {
      await personalityApi.update(newPersonalityName, currentValues);
      message.success('新人格已创建');
      setCreateModalVisible(false);
      setNewPersonalityName('');
      loadPersonalities();
      setCurrentPersonality(newPersonalityName);
    } catch (error) {
      message.error('创建失败');
    }
  };

  // 删除人格
  const handleDeletePersonality = async (name: string) => {
    if (name === 'default') {
      message.warning('不能删除默认人格');
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
          if (currentPersonality === name) {
            setCurrentPersonality('default');
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

  // 切换人格
  const handlePersonalityChange = (name: string) => {
    setCurrentPersonality(name);
  };

  // 初始化加载
  useEffect(() => {
    if (!initialized) {
      loadPersonalities();
      loadPersonality(currentPersonality, false);
      setInitialized(true);
    }
  }, [currentPersonality, initialized, loadPersonality, loadPersonalities]);

  // 当切换人格时重新加载
  useEffect(() => {
    if (initialized) {
      loadPersonality(currentPersonality, false);
    }
  }, [currentPersonality, initialized, loadPersonality]);

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

  // 获取当前选中的显示名称
  const currentDisplay = personalities.find(p => p.name === currentPersonality);

  return (
    <div style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
      <div style={{ marginBottom: '24px' }}>
        <h1>AI 人格配置</h1>
        <p style={{ color: '#666' }}>
          配置AI助手的人格模型，支持手动输入或使用AI生成
        </p>
      </div>

      {/* 人格选择和AI生成 */}
      <Card style={{ marginBottom: '24px' }}>
        <Row gutter={16} align="middle">
          <Col span={12}>
            <Space wrap>
              <span>当前人格：</span>
              <Select
                value={currentPersonality}
                onChange={handlePersonalityChange}
                style={{ width: 280 }}
                placeholder="选择人格"
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
              {currentPersonality !== 'default' && (
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
                  <Card>
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
                  <Card>
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

                    <Divider orientation="left">个性特征</Divider>

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

                    <Divider orientation="left">语言习惯</Divider>

                    {renderTagsInput(
                      ['core', 'catchphrases'],
                      '口头禅',
                      '添加口头禅，如：让我想想、有意思',
                      'AI常说的标志性话语'
                    )}

                    <Divider orientation="left">行为约束</Divider>

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
                  <Card>
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

                    <Divider orientation="left">领域专精</Divider>
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
      <div style={{ marginTop: '24px', textAlign: 'center' }}>
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
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text>请输入新人格的名称（将用作文件名）：</Text>
          <Input
            placeholder="例如：technical、friendly"
            value={newPersonalityName}
            onChange={(e) => setNewPersonalityName(e.target.value)}
          />
          <Text type="secondary" style={{ fontSize: '12px' }}>
            新人格将基于当前配置创建，创建后可以独立修改
          </Text>
        </Space>
      </Modal>
    </div>
  );
};

export default PersonalityPage;
