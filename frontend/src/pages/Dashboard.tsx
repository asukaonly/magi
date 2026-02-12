/**
 * Dashboard页面 - 现代化设计
 * 极简风格：统计卡片、快捷操作、最近活动
 */
import React, { useState, useEffect } from 'react';
import {
  Card,
  Row,
  Col,
  Statistic,
  Button,
  Space,
  Timeline,
  Typography,
  Divider,
} from 'antd';
import {
  MessageOutlined,
  UserOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

const { Text } = Typography;

// 模拟统计数据
const mockStats = {
  totalMessages: 1234,
  todayMessages: 56,
  activeCapabilities: 23,
  memoryUsage: 67,
};

// 模拟最近活动
const recentActivities = [
  { text: '用户发送了消息', time: '2 分钟前', type: 'message' },
  { text: 'AI 完成了任务', time: '5 分钟前', type: 'success' },
  { text: '人格配置已更新', time: '1 小时前', type: 'update' },
  { text: '新能力已习得', time: '2 小时前', type: 'capability' },
  { text: '系统已启动', time: '今天', type: 'system' },
];

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState(mockStats);

  // 快捷操作按钮样式
  const actionButtonStyle = {
    height: 48,
    borderRadius: 8,
    fontSize: 15,
    fontWeight: 500,
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  };

  // 统计卡片组件
  const StatCard: React.FC<{
    title: string;
    value: number;
    suffix?: string;
    color?: string;
  }> = ({ title, value, suffix, color = '#0d9488' }) => (
    <div
      style={{
        background: '#ffffff',
        border: '1px solid #e5e7eb',
        borderRadius: 8,
        padding: '20px 24px',
        height: '100%',
        transition: 'all 0.2s ease',
      }}
      className="stat-card"
    >
      <Text style={{ fontSize: 13, color: '#6b7280', fontWeight: 500 }}>{title}</Text>
      <div style={{ marginTop: 8 }}>
        <Statistic
          value={value}
          suffix={suffix}
          valueStyle={{
            fontSize: 28,
            fontWeight: 600,
            color: '#111827',
          }}
          suffixStyle={{ fontSize: 16, color: color }}
        />
      </div>
    </div>
  );

  return (
    <div>
      {/* 欢迎信息 */}
      <div style={{ marginBottom: 24 }}>
        <Text style={{ fontSize: 24, fontWeight: 600, color: '#111827' }}>
          欢迎使用 Magi AI Framework
        </Text>
        <div style={{ marginTop: 4 }}>
          <Text style={{ fontSize: 14, color: '#6b7280' }}>
            智能代理框架，支持多层记忆和动态人格配置
          </Text>
        </div>
      </div>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title="总消息数" value={stats.totalMessages} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title="今日消息"
            value={stats.todayMessages}
            color="#10b981"
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title="活跃能力"
            value={stats.activeCapabilities}
            color="#6366f1"
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title="内存使用"
            value={stats.memoryUsage}
            suffix="%"
            color="#f59e0b"
          />
        </Col>
      </Row>

      <Row gutter={24}>
        {/* 快捷操作 */}
        <Col xs={24} lg={12}>
          <Card
            title="快捷操作"
            bordered={false}
            style={{
              background: '#ffffff',
              border: '1px solid #e5e7eb',
              borderRadius: 8,
              height: '100%',
            }}
            styles={{ body: { padding: '20px 24px' } }}
          >
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              <Button
                type="primary"
                icon={<MessageOutlined />}
                onClick={() => navigate('/chat')}
                block
                size="large"
                style={{
                  ...actionButtonStyle,
                  background: '#0d9488',
                  borderColor: '#0d9488',
                }}
              >
                开始对话
                <ArrowRightOutlined style={{ marginLeft: 'auto' }} />
              </Button>
              <Button
                icon={<UserOutlined />}
                onClick={() => navigate('/personality')}
                block
                size="large"
                style={{
                  ...actionButtonStyle,
                  borderColor: '#e5e7eb',
                  color: '#111827',
                }}
              >
                管理人格
                <ArrowRightOutlined style={{ marginLeft: 'auto', color: '#9ca3af' }} />
              </Button>
              <Button
                icon={<SettingOutlined />}
                onClick={() => navigate('/settings')}
                block
                size="large"
                style={{
                  ...actionButtonStyle,
                  borderColor: '#e5e7eb',
                  color: '#111827',
                }}
              >
                系统设置
                <ArrowRightOutlined style={{ marginLeft: 'auto', color: '#9ca3af' }} />
              </Button>
            </Space>
          </Card>
        </Col>

        {/* 系统信息 */}
        <Col xs={24} lg={12}>
          <Card
            title="系统信息"
            bordered={false}
            style={{
              background: '#ffffff',
              border: '1px solid #e5e7eb',
              borderRadius: 8,
              height: '100%',
            }}
            styles={{ body: { padding: '20px 24px' } }}
          >
            <Row gutter={[16, 20]}>
              <Col xs={24} sm={8}>
                <div>
                  <Text style={{ fontSize: 12, color: '#6b7280' }}>框架版本</Text>
                  <div style={{ fontSize: 16, fontWeight: 600, color: '#111827', marginTop: 4 }}>
                    Magi v0.1.0
                  </div>
                </div>
              </Col>
              <Col xs={24} sm={8}>
                <div>
                  <Text style={{ fontSize: 12, color: '#6b7280' }}>记忆架构</Text>
                  <div style={{ fontSize: 16, fontWeight: 600, color: '#111827', marginTop: 4 }}>
                    L1-L5 五层
                  </div>
                </div>
              </Col>
              <Col xs={24} sm={8}>
                <div>
                  <Text style={{ fontSize: 12, color: '#6b7280' }}>事件系统</Text>
                  <div style={{ fontSize: 16, fontWeight: 600, color: '#111827', marginTop: 4 }}>
                    MessageBus
                  </div>
                </div>
              </Col>
            </Row>

            <Divider style={{ margin: '16px 0' }} />

            {/* 最近活动时间线 */}
            <div>
              <Text style={{ fontSize: 14, fontWeight: 600, color: '#111827', display: 'block', marginBottom: 12 }}>
                最近活动
              </Text>
              <Timeline
                items={recentActivities.map((activity, index) => ({
                  color: index === 0 ? '#0d9488' : '#e5e7eb',
                  dot: index === 0 ? <CheckCircleOutlined style={{ fontSize: 16, color: '#0d9488' }} /> : undefined,
                  children: (
                    <div key={index}>
                      <div style={{ fontSize: 13, color: '#111827' }}>{activity.text}</div>
                      <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 2 }}>
                        {activity.time}
                      </div>
                    </div>
                  ),
                }))}
                style={{ marginTop: 8 }}
              />
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Dashboard;
