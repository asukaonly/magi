/**
 * 聊天组件
 */
import React, { useState, useEffect, useRef } from 'react';
import { Card, Input, Button, List, Tag, Space, message, Typography } from 'antd';
import { SendOutlined, UserOutlined, RobotOutlined, LoadingOutlined } from '@ant-design/icons';
import { messagesApi } from '../../api';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

const ChatBox: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [connected, setConnected] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // 发送消息
  const handleSendMessage = async () => {
    if (!inputValue.trim()) {
      message.warning('请输入消息内容');
      return;
    }

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: inputValue,
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setLoading(true);

    try {
      // 发送到后端
      const response = await messagesApi.sendMessage({
        message: inputValue,
        user_id: 'web_user',
      });

      if (response.success) {
        message.success('消息发送成功');

        // 模拟AI回复（实际应该从WebSocket接收）
        setTimeout(() => {
          const assistantMessage: ChatMessage = {
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            content: `收到你的消息："${inputValue}"\n\n我正在处理中...（这是模拟回复，实际需要连接到Agent系统）`,
            timestamp: Date.now(),
          };
          setMessages((prev) => [...prev, assistantMessage]);
          setLoading(false);
        }, 1000);
      }
    } catch (error) {
      message.error('发送消息失败');
      setLoading(false);
    }
  };

  // 清空消息
  const handleClearMessages = () => {
    setMessages([]);
    message.info('已清空聊天记录');
  };

  return (
    <Card
      title="智能对话"
      extra={
        <Space>
          <Tag color={connected ? 'success' : 'default'}>
            {connected ? '已连接' : '未连接'}
          </Tag>
          <Button size="small" onClick={handleClearMessages}>
            清空
          </Button>
        </Space>
      }
      style={{ height: '600px', display: 'flex', flexDirection: 'column' }}
      bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 0 }}
    >
      {/* 消息列表 */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '16px',
          backgroundColor: '#fafafa',
        }}
      >
        <List
          dataSource={messages}
          renderItem={(msg) => (
            <div
              key={msg.id}
              style={{
                marginBottom: '16px',
                display: 'flex',
                justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
              }}
            >
              <div
                style={{
                  maxWidth: '70%',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                  flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
                }}
              >
                <div
                  style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    backgroundColor: msg.role === 'user' ? '#1890ff' : '#52c41a',
                    color: 'white',
                  }}
                >
                  {msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                </div>
                <div
                  style={{
                    padding: '8px 12px',
                    borderRadius: '8px',
                    backgroundColor: msg.role === 'user' ? '#1890ff' : 'white',
                    color: msg.role === 'user' ? 'white' : 'black',
                    boxShadow: '0 1px 2px rgba(0,0,0,0.1)',
                  }}
                >
                  <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                  </Paragraph>
                  <Text type="secondary" style={{ fontSize: '12px' }}>
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </Text>
                </div>
              </div>
            </div>
          )}
        />
        {loading && (
          <div style={{ textAlign: 'center', padding: '8px' }}>
            <LoadingOutlined /> AI正在思考...
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div style={{ padding: '16px', borderTop: '1px solid #f0f0f0' }}>
        <Space.Compact style={{ width: '100%' }}>
          <TextArea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="输入你的消息..."
            autoSize={{ minRows: 1, maxRows: 4 }}
            onPressEnter={(e) => {
              if (e.shiftKey) return;
              e.preventDefault();
              handleSendMessage();
            }}
            disabled={loading}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={handleSendMessage}
            loading={loading}
          >
            发送
          </Button>
        </Space.Compact>
        <div style={{ marginTop: '8px', fontSize: '12px', color: '#999' }}>
          按 Enter 发送，Shift + Enter 换行
        </div>
      </div>
    </Card>
  );
};

export default ChatBox;
