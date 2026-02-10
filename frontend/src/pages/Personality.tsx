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
  Empty,
} from 'antd';
import {
  SaveOutlined,
  ThunderboltOutlined,
  ReloadOutlined,
  CheckOutlined,
} from '@ant-design/icons';
import { personalityApi, type PersonalityConfig } from '../api';

const { TextArea } = Input;
const { Option } = Select;

// 枚举选项
const LANGUAGE_STYLES = [
  'casual',
  'formal',
  'concise',
  'verbose',
  'technical',
  'poetic',
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
  'logical',
  'creative',
  'intuitive',
  'analytical',
];

const RISK_PREFERENCES = [
  { value: 'conservative', label: '保守' },
  { value: 'balanced', label: '平衡' },
  { value: 'adventurous', label: '冒险' },
];

const REASONING_DEPTHS = ['shallow', 'medium', 'deep'];

const PersonalityPage: React.FC = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [currentPersonality, setCurrentPersonality] = useState<string>('default');
  const [aiDescription, setAiDescription] = useState('');
  const [initialized, setInitialized] = useState(false);

  // 加载人格配置
  const loadPersonality = useCallback(async (name: string, showMessage: boolean = false) => {
    setLoading(true);
    try {
      const response = await personalityApi.get(name);
      if (response.success && response.data) {
        form.setFieldsValue(response.data);
        if (showMessage) {
          message.success(`加载人格配置成功: ${name}`);
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
      console.log('[保存人格] 表单数据:', values);
      setSaving(true);

      const response = await personalityApi.update(currentPersonality, values);
      console.log('[保存人格] API响应:', response);

      if (response.success) {
        message.success('人格配置已保存');
      } else {
        message.error(response.message || '保存失败');
      }
    } catch (error: any) {
      console.error('[保存人格] 异常:', error);
      message.error(`保存失败: ${error.message || error?.message || '未知错误'}`);
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
      console.log('[AI生成] 发送请求:', aiDescription);
      const response = await personalityApi.generate({
        description: aiDescription,
      });

      console.log('[AI生成] 收到响应:', response);

      if (response.success && response.data) {
        console.log('[AI生成] 更新表单数据:', response.data);
        form.setFieldsValue(response.data);
        message.success('AI生成人格配置成功');
        setAiDescription('');
      } else {
        console.error('[AI生成] 响应失败:', response);
        message.error(response.message || 'AI生成失败');
      }
    } catch (error: any) {
      console.error('[AI生成] 请求异常:', error);
      message.error(`AI生成失败: ${error.message || '未知错误'}`);
    } finally {
      setGenerating(false);
    }
  };

  // 重置为默认
  const handleReset = async () => {
    await loadPersonality(currentPersonality, true);
  };

  // 初始化加载
  useEffect(() => {
    if (!initialized) {
      loadPersonality(currentPersonality, false);
      setInitialized(true);
    }
  }, [currentPersonality, initialized, loadPersonality]);

  // 辅助函数：渲染标签输入
  const renderTagsInput = (field: string, placeholder: string) => (
    <Form.Item name={field}>
      <Select
        mode="tags"
        placeholder={placeholder}
        tokenSeparators={[',', ' ']}
      />
    </Form.Item>
  );

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
          <Col span={8}>
            <Space>
              <span>当前人格：</span>
              <Select
                value={currentPersonality}
                onChange={setCurrentPersonality}
                style={{ width: 150 }}
              >
                <Option value="default">默认人格</Option>
                <Option value="technical">技术专家</Option>
              </Select>
              <Button icon={<ReloadOutlined />} onClick={handleReset}>
                刷新
              </Button>
            </Space>
          </Col>
          <Col span={16}>
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
                          rules={[{ required: true }]}
                        >
                          <Input placeholder="例如：小智、AI助手" />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item
                          name={['core', 'role']}
                          label="角色定位"
                          rules={[{ required: true }]}
                        >
                          <Input placeholder="例如：编程助手、顾问" />
                        </Form.Item>
                      </Col>
                    </Row>

                    <Form.Item name={['core', 'backstory']} label="背景故事">
                      <TextArea
                        rows={3}
                        placeholder="描述AI的背景、来历、目标等..."
                      />
                    </Form.Item>

                    <Row gutter={16}>
                      <Col span={12}>
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
                      <Col span={12}>
                        <Form.Item name={['core', 'use_emoji']} label="使用表情" valuePropName="checked">
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
                        <Form.Item name={['core', 'language_style']} label="语言风格">
                          <Select placeholder="选择风格">
                            {LANGUAGE_STYLES.map((s) => (
                              <Option key={s} value={s}>
                                {s}
                              </Option>
                            ))}
                          </Select>
                        </Form.Item>
                      </Col>
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
                        <Form.Item name={['core', 'value_alignment']} label="价值观">
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

                    {renderTagsInput(['core', 'traits'], '个性标签，如：友善、好奇、耐心')}
                    {renderTagsInput(['core', 'virtues'], '优点，如：同理心、诚实、勤奋')}
                    {renderTagsInput(['core', 'flaws'], '缺点，如：想太多、分心')}
                    {renderTagsInput(['core', 'catchphrases'], '口头禅，如：让我想想、有意思')}
                    {renderTagsInput(['core', 'taboos'], '禁忌，如：暴力内容、歧视')}
                    {renderTagsInput(['core', 'boundaries'], '行为边界，如：尊重隐私、遵循道德')}
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
                              <Option key={s} value={s}>
                                {s}
                              </Option>
                            ))}
                          </Select>
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name={['cognition', 'secondary_style']} label="次要思维风格">
                          <Select placeholder="选择次要风格">
                            {THINKING_STYLES.map((s) => (
                              <Option key={s} value={s}>
                                {s}
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
                              <Option key={d} value={d}>
                                {d}
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
                      description="格式：领域名-等级，例如：coding-0.9"
                      type="info"
                      showIcon
                      style={{ marginBottom: 16 }}
                    />
                    <Form.Item name={['cognition', 'expertise']}>
                      <Select
                        mode="tags"
                        placeholder="添加领域专精，格式：领域名:等级，例如 coding:0.9"
                        tokenSeparators={[',', ' ']}
                        options={[
                          { label: 'coding:0.9', value: 'coding:0.9' },
                          { label: 'writing:0.8', value: 'writing:0.8' },
                          { label: 'analysis:0.85', value: 'analysis:0.85' },
                        ]}
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
    </div>
  );
};

export default PersonalityPage;
