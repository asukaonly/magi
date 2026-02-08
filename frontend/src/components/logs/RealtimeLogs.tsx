/**
 * 实时日志组件
 */
import React, { useState, useEffect, useRef } from 'react';
import { Card, List, Tag, Space, Button } from 'antd';
import { PlayCircleOutlined, PauseCircleOutlined, DeleteOutlined } from '@ant-design/icons';
import useWebSocket from '../hooks/useWebSocket';

interface LogEntry {
  level: string;
  message: string;
  source?: string;
  timestamp: number;
}

const RealtimeLogs: React.FC = () => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isPaused, setIsPaused] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);

  const { connected, subscribe, subscribeChannel } = useWebSocket({
    onConnected: () => {
      console.log('WebSocket connected for logs');
      // 订阅日志频道
      subscribeChannel('logs');
    },
  });

  useEffect(() => {
    // 订阅日志事件
    const unsubscribe = subscribe('log', (data: LogEntry) => {
      if (!isPaused) {
        setLogs((prev) => [...prev, data].slice(-100)); // 保留最近100条
      }
    });

    return unsubscribe;
  }, [subscribe, isPaused]);

  // 自动滚动到底部
  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  const getLevelColor = (level: string) => {
    const colors = {
      info: 'blue',
      warning: 'orange',
      error: 'red',
      debug: 'default',
    };
    return colors[level as keyof typeof colors] || 'default';
  };

  const formatTimestamp = (timestamp: number) => {
    return new Date(timestamp * 1000).toLocaleTimeString();
  };

  const handleClear = () => {
    setLogs([]);
  };

  const handlePause = () => {
    setIsPaused(!isPaused);
  };

  return (
    <Card
      title="实时日志"
      extra={
        <Space>
          <Button
            icon={isPaused ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
            onClick={handlePause}
            size="small"
          >
            {isPaused ? '继续' : '暂停'}
          </Button>
          <Button
            icon={<DeleteOutlined />}
            onClick={handleClear}
            size="small"
          >
            清空
          </Button>
          <Tag color={connected ? 'success' : 'error'}>
            {connected ? '已连接' : '未连接'}
          </Tag>
        </Space>
      }
    >
      <div
        style={{
          height: 400,
          overflowY: 'auto',
          backgroundColor: '#f5f5f5',
          padding: 16,
          borderRadius: 4,
        }}
      >
        {logs.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#999', marginTop: 100 }}>
            等待日志...
          </div>
        ) : (
          <List
            dataSource={logs}
            renderItem={(log) => (
              <List.Item style={{ padding: '4px 0', border: 'none' }}>
                <Space>
                  <span style={{ color: '#999', fontSize: 12 }}>
                    {formatTimestamp(log.timestamp)}
                  </span>
                  <Tag color={getLevelColor(log.level)}>{log.level.toUpperCase()}</Tag>
                  {log.source && <span style={{ color: '#666' }}>[{log.source}]</span>}
                  <span>{log.message}</span>
                </Space>
              </List.Item>
            )}
          />
        )}
        <div ref={logsEndRef} />
      </div>
    </Card>
  );
};

export default RealtimeLogs;
