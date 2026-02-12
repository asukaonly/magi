/**
 * Events页面 - L1-L5 记忆查看
 */
import React, { useEffect, useState } from 'react';
import {
  Card,
  Tabs,
  Table,
  Tag,
  Space,
  Button,
  Input,
  Descriptions,
  Timeline,
  Statistic,
  Row,
  Col,
  message,
  Spin,
} from 'antd';
import {
  ReloadOutlined,
  SearchOutlined,
  DatabaseOutlined,
  NodeIndexOutlined,
  BranchesOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type { TabsProps } from 'antd';
import { apiClient } from '../api/client';

interface Event {
  id: string;
  type: string;
  data: any;
  timestamp: number;
  source: string;
  level: number;
  correlation_id: string;
  metadata: any;
}

interface Relation {
  source_event_id: string;
  target_event_id: string;
  relation_type: string;
  confidence: number;
}

interface Embedding {
  event_id: string;
  text: string;
  metadata: any;
}

interface Summary {
  period_type: string;
  period_key: string;
  start_time: number;
  end_time: number;
  event_count: number;
  summary: string;
}

interface Capability {
  capability_id: string;
  name: string;
  description: string;
  success_rate: number;
  usage_count: number;
}

const EventsPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('l1');

  // L1 数据
  const [l1Events, setL1Events] = useState<Event[]>([]);
  const [l1Stats, setL1Stats] = useState({ total: 0 });

  // L2 数据
  const [l2Relations, setL2Relations] = useState<Relation[]>([]);
  const [l2Events, setL2Events] = useState<any[]>([]);
  const [l2Stats, setL2Stats] = useState({ total_events: 0, total_relations: 0 });

  // L3 数据
  const [l3Embeddings, setL3Embeddings] = useState<Embedding[]>([]);
  const [l3Stats, setL3Stats] = useState({ total_embeddings: 0, dimension: 0 });

  // L4 数据
  const [l4Summaries, setL4Summaries] = useState<Summary[]>([]);
  const [l4Stats, setL4Stats] = useState({ total_summaries: 0 });

  // L5 数据
  const [l5Capabilities, setL5Capabilities] = useState<Capability[]>([]);
  const [l5Stats, setL5Stats] = useState({ total_capabilities: 0 });

  // 搜索关键词
  const [searchKeyword, setSearchKeyword] = useState('');

  const fetchAllData = async () => {
    setLoading(true);
    try {
      await Promise.all([
        fetchL1Data(),
        fetchL2Data(),
        fetchL3Data(),
        fetchL4Data(),
        fetchL5Data(),
      ]);
    } catch (error: any) {
      message.error('加载数据失败: ' + error.message);
    } finally {
      setLoading(false);
    }
  };

  // L1: 获取原始事件
  const fetchL1Data = async () => {
    try {
      const response = await apiClient.get('/memory/l1/events', { params: { limit: 50 } });
      setL1Events(response.data.events || []);
      setL1Stats(response.data.stats || { total: 0 });
    } catch (error) {
      console.error('Failed to fetch L1 data:', error);
      setL1Events([]);
      setL1Stats({ total: 0 });
    }
  };

  // L2: 获取事件关系
  const fetchL2Data = async () => {
    try {
      const response = await apiClient.get('/memory/l2/statistics');
      setL2Stats(response.data || { total_events: 0, total_relations: 0 });
    } catch (error) {
      console.error('Failed to fetch L2 data:', error);
    }
  };

  // L3: 获取嵌入向量
  const fetchL3Data = async () => {
    try {
      const response = await apiClient.get('/memory/statistics');
      const stats = response.data.l3_embeddings || {};
      setL3Stats(stats);
    } catch (error) {
      console.error('Failed to fetch L3 data:', error);
    }
  };

  // L4: 获取摘要
  const fetchL4Data = async () => {
    try {
      const response = await apiClient.get('/memory/statistics');
      const stats = response.data.l4_summaries || {};
      setL4Stats(stats);
    } catch (error) {
      console.error('Failed to fetch L4 data:', error);
    }
  };

  // L5: 获取能力
  const fetchL5Data = async () => {
    try {
      const response = await apiClient.get('/memory/capabilities');
      setL5Capabilities(response.data || []);
      const statsResponse = await apiClient.get('/memory/statistics');
      setL5Stats(statsResponse.data.l5_capabilities || { total_capabilities: 0 });
    } catch (error) {
      console.error('Failed to fetch L5 data:', error);
    }
  };

  useEffect(() => {
    fetchAllData();
  }, []);

  // 事件等级标签颜色
  const getLevelColor = (level: number) => {
    const colors = ['#d1d5db', '#10b981', '#f59e0b', '#ef4444', '#dc2626', '#6366f1'];
    return colors[level] || '#d1d5db';
  };

  const getLevelName = (level: number) => {
    const names = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'EMERGENCY'];
    return names[level] || 'UNKNOWN';
  };

  // L1 表格列
  const l1Columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 80,
      render: (id: string) => id.slice(0, 8) + '...',
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 180,
      render: (type: string) => <Tag color="cyan">{type}</Tag>,
    },
    {
      title: '数据',
      dataIndex: 'data',
      key: 'data',
      ellipsis: true,
      render: (data: any) => {
        const str = typeof data === 'string' ? data : JSON.stringify(data);
        return <span style={{ fontSize: 12 }}>{str.slice(0, 50)}...</span>;
      },
    },
    {
      title: '等级',
      dataIndex: 'level',
      key: 'level',
      width: 80,
      render: (level: number) => (
        <Tag color={getLevelColor(level)}>{getLevelName(level)}</Tag>
      ),
    },
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 160,
      render: (ts: number) => new Date(ts * 1000).toLocaleString(),
    },
    {
      title: '关联ID',
      dataIndex: 'correlation_id',
      key: 'correlation_id',
      width: 80,
      render: (id: string) => id?.slice(0, 8) + '...' || '-',
    },
  ];

  // L5 表格列
  const l5Columns = [
    {
      title: 'ID',
      dataIndex: 'capability_id',
      key: 'capability_id',
      width: 100,
      render: (id: string) => id.slice(0, 12) + '...',
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: '成功率',
      dataIndex: 'success_rate',
      key: 'success_rate',
      width: 100,
      render: (rate: number) => (
        <Tag color={rate > 0.7 ? 'success' : rate > 0.5 ? 'warning' : 'error'}>
          {(rate * 100).toFixed(0)}%
        </Tag>
      ),
    },
    {
      title: '使用次数',
      dataIndex: 'usage_count',
      key: 'usage_count',
      width: 100,
    },
  ];

  // 搜索处理
  const handleSearch = async () => {
    if (!searchKeyword.trim()) {
      message.warning('请输入搜索关键词');
      return;
    }

    setLoading(true);
    try {
      const response = await apiClient.get('/memory/search', {
        params: { query: searchKeyword, limit: 20 },
      });
      const results = response.data || [];

      if (results.length > 0) {
        setActiveTab('l3');
        setL3Embeddings(results);
        message.success(`找到 ${results.length} 条相关事件`);
      } else {
        message.warning('未找到相关事件');
      }
    } catch (error: any) {
      message.error('搜索失败: ' + error.message);
    } finally {
      setLoading(false);
    }
  };

  // Tab 内容
  const tabItems: TabsProps['items'] = [
    {
      key: 'l1',
      label: (
        <span>
          <DatabaseOutlined />
          L1 原始事件 ({l1Stats.total})
        </span>
      ),
      children: (
        <div>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card size="small">
                <Statistic title="总事件数" value={l1Stats.total} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="INFO事件"
                  value={l1Events.filter((e) => e.level === 1).length}
                  valueStyle={{ color: '#10b981' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="WARNING事件"
                  value={l1Events.filter((e) => e.level === 2).length}
                  valueStyle={{ color: '#f59e0b' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="ERROR事件"
                  value={l1Events.filter((e) => e.level >= 3).length}
                  valueStyle={{ color: '#ef4444' }}
                />
              </Card>
            </Col>
          </Row>

          <Table
            columns={l1Columns}
            dataSource={l1Events}
            rowKey="id"
            size="small"
            pagination={{ pageSize: 10 }}
            expandable={{
              expandedRowRender: (record) => (
                <Descriptions size="small" column={2} bordered>
                  <Descriptions.Item label="ID">{record.id}</Descriptions.Item>
                  <Descriptions.Item label="关联ID">{record.correlation_id}</Descriptions.Item>
                  <Descriptions.Item label="来源">{record.source}</Descriptions.Item>
                  <Descriptions.Item label="时间戳">{record.timestamp}</Descriptions.Item>
                  <Descriptions.Item label="元数据" span={2}>
                    <pre style={{ margin: 0, fontSize: 12 }}>
                      {JSON.stringify(record.metadata, null, 2)}
                    </pre>
                  </Descriptions.Item>
                  <Descriptions.Item label="数据" span={2}>
                    <pre style={{ margin: 0, fontSize: 12, maxHeight: 200, overflow: 'auto' }}>
                      {JSON.stringify(record.data, null, 2)}
                    </pre>
                  </Descriptions.Item>
                </Descriptions>
              ),
            }}
          />
        </div>
      ),
    },
    {
      key: 'l2',
      label: (
        <span>
          <BranchesOutlined />
          L2 事件关系 ({l2Stats.total_relations})
        </span>
      ),
      children: (
        <div>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={8}>
              <Card size="small">
                <Statistic title="总事件数" value={l2Stats.total_events} />
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small">
                <Statistic title="总关系数" value={l2Stats.total_relations} />
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small">
                <Statistic
                  title="平均关系数/事件"
                  value={l2Stats.total_events > 0 ? (l2Stats.total_relations / l2Stats.total_events).toFixed(2) : 0}
                  decimalSeparator="."
                />
              </Card>
            </Col>
          </Row>

          <Card title="关系类型说明" size="small">
            <Space direction="vertical" style={{ width: '100%' }}>
              <div><Tag color="default">PRECEDE</Tag> - 同一链路上的前后事件</div>
              <div><Tag color="cyan">TRIGGER</Tag> - 感知触发处理</div>
              <div><Tag color="orange">CAUSE</Tag> - 因果关系</div>
              <div><Tag color="purple">FOLLOW</Tag> - 后续事件</div>
              <div><Tag color="blue">SAME_USER</Tag> - 同一用户事件</div>
            </Space>
          </Card>
        </div>
      ),
    },
    {
      key: 'l3',
      label: (
        <span>
          <NodeIndexOutlined />
          L3 语义搜索 ({l3Stats.total_embeddings})
        </span>
      ),
      children: (
        <div>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={12}>
              <Card size="small">
                <Statistic title="嵌入向量数" value={l3Stats.total_embeddings} />
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small">
                <Statistic title="向量维度" value={l3Stats.dimension} suffix="维" />
              </Card>
            </Col>
          </Row>

          <Card title="语义搜索" size="small" style={{ marginBottom: 16 }}>
            <Space.Compact style={{ width: '100%' }}>
              <Input
                placeholder="输入搜索关键词，如：用户消息、错误、任务完成..."
                value={searchKeyword}
                onChange={(e) => setSearchKeyword(e.target.value)}
                onPressEnter={handleSearch}
              />
              <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>
                搜索
              </Button>
            </Space.Compact>
          </Card>

          {l3Embeddings.length > 0 && (
            <Table
              columns={[
                { title: '事件ID', dataIndex: 'event_id', key: 'event_id', render: (id: string) => id.slice(0, 12) + '...' },
                { title: '文本内容', dataIndex: 'text', key: 'text', ellipsis: true },
                { title: '类型', dataIndex: 'metadata', key: 'type', render: (m: any) => m?.event_type || '-' },
              ]}
              dataSource={l3Embeddings}
              rowKey="event_id"
              size="small"
              pagination={false}
            />
          )}
        </div>
      ),
    },
    {
      key: 'l4',
      label: (
        <span>
          <FileTextOutlined />
          L4 时间摘要 ({l4Stats.total_summaries})
        </span>
      ),
      children: (
        <div>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={24}>
              <Card size="small">
                <Statistic title="摘要总数" value={l4Stats.total_summaries} />
              </Card>
            </Col>
          </Row>

          <Card title="摘要说明" size="small">
            <p>L4 摘要按照时间粒度自动生成：</p>
            <Space>
              <Tag>小时</Tag>
              <Tag>天</Tag>
              <Tag>周</Tag>
              <Tag>月</Tag>
            </Space>
            <p style={{ marginTop: 16, color: '#666' }}>
              摘要会在后台定期生成，也可以手动触发。
            </p>
          </Card>
        </div>
      ),
    },
    {
      key: 'l5',
      label: (
        <span>
          <ThunderboltOutlined />
          L5 能力记忆 ({l5Stats.total_capabilities})
        </span>
      ),
      children: (
        <div>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={8}>
              <Card size="small">
                <Statistic title="能力总数" value={l5Stats.total_capabilities} />
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small">
                <Statistic
                  title="高成功率能力"
                  value={l5Capabilities.filter((c) => c.success_rate > 0.8).length}
                  valueStyle={{ color: '#10b981' }}
                />
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small">
                <Statistic
                  title="低成功率能力"
                  value={l5Capabilities.filter((c) => c.success_rate < 0.5).length}
                  valueStyle={{ color: '#ef4444' }}
                />
              </Card>
            </Col>
          </Row>

          <Table
            columns={l5Columns}
            dataSource={l5Capabilities}
            rowKey="capability_id"
            size="small"
            pagination={{ pageSize: 10 }}
          />
        </div>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>记忆查看</h1>
          <p style={{ margin: '8px 0 0', color: '#666' }}>
            L1-L5 五层记忆架构数据查看
          </p>
        </div>
        <Button icon={<ReloadOutlined />} onClick={fetchAllData} loading={loading}>
          刷新
        </Button>
      </div>

      <Spin spinning={loading}>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      </Spin>
    </div>
  );
};

export default EventsPage;
