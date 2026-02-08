/**
 * Dashboard页面
 */
import React, { useEffect } from 'react';
import { Card, Row, Col, Statistic, Table, Tag, Space, Button } from 'antd';
import {
  RobotOutlined,
  UnorderedListOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAgentsStore } from '../stores';
import { useTasksStore } from '../stores';
import { useMetricsStore } from '../stores';
import useWebSocket from '../hooks/useWebSocket';
import RealtimeLogs from '../components/logs/RealtimeLogs';

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { agents, fetchAgents } = useAgentsStore();
  const { tasks, stats, fetchTasks, fetchStats } = useTasksStore();
  const { systemMetrics, fetchSystemMetrics } = useMetricsStore();

  // WebSocket连接
  const { connected, subscribe, subscribeChannel } = useWebSocket({
    onConnected: () => {
      console.log('WebSocket connected');
      // 订阅更新
      subscribeChannel('agents');
      subscribeChannel('tasks');
      subscribeChannel('metrics');
    },
  });

  useEffect(() => {
    fetchAgents();
    fetchTasks();
    fetchStats();
    fetchSystemMetrics();

    // 订阅WebSocket更新
    const unsubscribeAgent = subscribe('agent_update', (data) => {
      console.log('Agent update received:', data);
      fetchAgents();
    });

    const unsubscribeTask = subscribe('task_update', (data) => {
      console.log('Task update received:', data);
      fetchTasks();
      fetchStats();
    });

    const unsubscribeMetrics = subscribe('metrics_update', (data) => {
      console.log('Metrics update received:', data);
      fetchSystemMetrics();
    });

    // 定时刷新（备用方案，每30秒）
    const interval = setInterval(() => {
      fetchSystemMetrics();
    }, 30000);

    return () => {
      unsubscribeAgent();
      unsubscribeTask();
      unsubscribeMetrics();
      clearInterval(interval);
    };
  }, [subscribe, fetchAgents, fetchTasks, fetchStats, fetchSystemMetrics]);

  // 计算Agent统计
  const runningAgents = agents.filter((a) => a.state === 'running').length;
  const stoppedAgents = agents.filter((a) => a.state === 'stopped').length;

  // 任务表格列
  const taskColumns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 200,
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      render: (priority: string) => {
        const color = {
          high: 'red',
          normal: 'blue',
          low: 'default',
        }[priority] || 'default';
        return <Tag color={color}>{priority.toUpperCase()}</Tag>;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const color = {
          pending: 'default',
          running: 'processing',
          completed: 'success',
          failed: 'error',
        }[status] || 'default';
        return <Tag color={color}>{status.toUpperCase()}</Tag>;
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (date: string) => new Date(date).toLocaleString(),
    },
  ];

  // Agent表格列
  const agentColumns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 150,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: '类型',
      dataIndex: 'agent_type',
      key: 'agent_type',
      render: (type: string) => type.toUpperCase(),
    },
    {
      title: '状态',
      dataIndex: 'state',
      key: 'state',
      render: (state: string) => {
        const color = {
          running: 'success',
          stopped: 'default',
          starting: 'processing',
          stopping: 'processing',
          error: 'error',
        }[state] || 'default';
        return <Tag color={color}>{state.toUpperCase()}</Tag>;
      },
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>仪表盘</h1>
        <p style={{ margin: '8px 0 0', color: '#666' }}>
          系统概览和实时监控
        </p>
      </div>

      {/* 系统指标 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="总Agent数"
              value={agents.length}
              prefix={<RobotOutlined />}
              valueStyle={{ color: '#3f8600' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="运行中"
              value={runningAgents}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="总任务数"
              value={stats?.total || 0}
              prefix={<UnorderedListOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="已完成"
              value={stats?.completed || 0}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 系统资源使用率 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={12}>
          <Card title="系统资源" extra={<ClockCircleOutlined />}>
            <Space direction="vertical" style={{ width: '100%' }} size="large">
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <span>CPU使用率</span>
                  <span style={{ fontWeight: 600 }}>
                    {systemMetrics?.cpu_percent?.toFixed(1)}%
                  </span>
                </div>
                <div
                  style={{
                    width: '100%',
                    height: 8,
                    background: '#f0f0f0',
                    borderRadius: 4,
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      width: `${systemMetrics?.cpu_percent || 0}%`,
                      height: '100%',
                      background: systemMetrics?.cpu_percent && systemMetrics.cpu_percent > 80
                        ? '#ff4d4f'
                        : '#52c41a',
                      transition: 'width 0.3s ease',
                    }}
                  />
                </div>
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <span>内存使用率</span>
                  <span style={{ fontWeight: 600 }}>
                    {systemMetrics?.memory_percent?.toFixed(1)}%
                  </span>
                </div>
                <div
                  style={{
                    width: '100%',
                    height: 8,
                    background: '#f0f0f0',
                    borderRadius: 4,
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      width: `${systemMetrics?.memory_percent || 0}%`,
                      height: '100%',
                      background: systemMetrics?.memory_percent && systemMetrics.memory_percent > 80
                        ? '#ff4d4f'
                        : '#52c41a',
                      transition: 'width 0.3s ease',
                    }}
                  />
                </div>
                <div style={{ marginTop: 4, fontSize: 12, color: '#666' }}>
                  {systemMetrics?.memory_used?.toFixed(2)} GB / {systemMetrics?.memory_total?.toFixed(2)} GB
                </div>
              </div>
            </Space>
          </Card>
        </Col>

        <Col span={12}>
          <Card title="任务统计" extra={<UnorderedListOutlined />}>
            <Row gutter={16}>
              <Col span={12}>
                <Statistic
                  title="待处理"
                  value={stats?.pending || 0}
                  valueStyle={{ color: '#faad14' }}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="运行中"
                  value={stats?.running || 0}
                  valueStyle={{ color: '#1890ff' }}
                />
              </Col>
              <Col span={12} style={{ marginTop: 16 }}>
                <Statistic
                  title="已完成"
                  value={stats?.completed || 0}
                  valueStyle={{ color: '#52c41a' }}
                />
              </Col>
              <Col span={12} style={{ marginTop: 16 }}>
                <Statistic
                  title="失败"
                  value={stats?.failed || 0}
                  valueStyle={{ color: '#ff4d4f' }}
                />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      {/* Agent列表 */}
      <Card
        title="Agent列表"
        extra={
          <Button type="primary" onClick={() => navigate('/agents')}>
            查看全部
          </Button>
        }
        style={{ marginBottom: 24 }}
      >
        <Table
          columns={agentColumns}
          dataSource={agents.slice(0, 5)}
          rowKey="id"
          pagination={false}
          size="small"
        />
      </Card>

      {/* 最近任务 */}
      <Card
        title="最近任务"
        extra={
          <Button type="primary" onClick={() => navigate('/tasks')}>
            查看全部
          </Button>
        }
        style={{ marginBottom: 24 }}
      >
        <Table
          columns={taskColumns}
          dataSource={tasks.slice(0, 5)}
          rowKey="id"
          pagination={false}
          size="small"
        />
      </Card>

      {/* 实时日志 */}
      <RealtimeLogs />
    </div>
  );
};

export default Dashboard;
