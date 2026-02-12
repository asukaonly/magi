/**
 * Chat页面 - 与Agent对话（使用正确的Agent架构）
 * 流程：用户消息 → 感知器队列 → Agent循环 → WebSocket推送回复
 */
import React, { useState, useRef, useEffect } from 'react';
import { Card, Input, Button, List, Avatar, Space, Tag, message, Typography, Divider } from 'antd';
import { SendOutlined, UserOutlined, RobotOutlined, ClearOutlined } from '@ant-design/icons';
import { messagesApi, ConversationHistory } from '../api';
import { personalityApi } from '../api/modules/personality';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  agent_id?: string;
  status?: 'sending' | 'sent' | 'failed';
}

export const ChatPage: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [aiName, setAiName] = useState<string>('AI Agent');
  const [_ws, setWs] = useState<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [_sid, setSid] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // WebSocket连接
  useEffect(() => {
    const userId = 'web_user';
    const room = `user_${userId}`;

    // 连接到WebSocket服务器
    const wsUrl = 'ws://localhost:8000/ws';
    const websocket = new WebSocket(wsUrl);

    websocket.onopen = () => {
      console.log('WebSocket connected');
      setConnected(true);

      // 订阅用户专属房间
      websocket.send(JSON.stringify({
        type: 'subscribe',
        channel: room,
      }));
    };

    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log('WebSocket message received:', data);

        // 处理订阅确认
        if (data.type === 'subscribed') {
          console.log('Subscribed to room:', data.channel);
          setSid(data.sid);
        }
        // 处理Agent回复
        else if (data.event === 'agent_response') {
          const response = data.data;
          console.log('Received agent response:', response);

          const assistantMessage: ChatMessage = {
            id: `ws-${Date.now()}`,
            role: 'assistant',
            content: response.response,
            timestamp: response.timestamp * 1000, // 转换为毫秒
          };

          // 直接添加消息，无需 loading 状态
          setMessages((prev) => [...prev, assistantMessage]);
        }
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };

    websocket.onclose = () => {
      console.log('WebSocket disconnected');
      setConnected(false);
    };

    websocket.onerror = (error) => {
      console.error('WebSocket error:', error);
      setConnected(false);
    };

    setWs(websocket);

    // 清理函数
    return () => {
      websocket.close();
    };
  }, []);

  // 添加欢迎消息和加载历史
  useEffect(() => {
    const loadHistory = async () => {
      try {
        const history: ConversationHistory = await messagesApi.getHistory('web_user');
        if (history.messages && history.messages.length > 0) {
          const chatMessages: ChatMessage[] = history.messages.map((msg, index) => ({
            id: `history-${index}`,
            role: msg.role,
            content: msg.content,
            timestamp: msg.timestamp * 1000, // 转换为毫秒
            status: 'sent',
          }));
          setMessages(chatMessages);
        } else {
          // 没有历史记录，获取人格问候语和名字
          try {
            const greetingResponse = await personalityApi.getGreeting() as any;
            const greeting = greetingResponse?.data?.greeting || '👋 欢迎使用 Magi AI Agent Framework！\n\n你可以在这里与 Agent 对话。发送消息后，Agent 会通过感知器接收消息，处理后通过 WebSocket 推送回复。';
            const name = greetingResponse?.data?.name || 'AI Agent';
            setAiName(name);

            const welcomeMessage: ChatMessage = {
              id: 'welcome',
              role: 'assistant',
              content: greeting,
              timestamp: Date.now(),
            };
            setMessages([welcomeMessage]);
          } catch (error) {
            console.error('获取问候语失败:', error);
            const welcomeMessage: ChatMessage = {
              id: 'welcome',
              role: 'system',
              content: '👋 欢迎使用 Magi AI Agent Framework！\n\n你可以在这里与 Agent 对话。发送消息后，Agent 会通过感知器接收消息，处理后通过 WebSocket 推送回复。',
              timestamp: Date.now(),
            };
            setMessages([welcomeMessage]);
          }
        }
      } catch (error) {
        console.error('加载历史失败:', error);
        console.error('History error details:', {
          message: (error as any)?.message,
          code: (error as any)?.code,
          status: (error as any)?.status,
          details: (error as any)?.details,
          fullError: error,
        });
        // 设置默认欢迎消息
        const defaultWelcome: ChatMessage = {
          id: 'welcome',
          role: 'system',
          content: '👋 欢迎使用 Magi AI Agent Framework！',
          timestamp: Date.now(),
        };
        setMessages([defaultWelcome]);
      }
    };

    loadHistory();
  }, []);

  // 发送消息
  const handleSendMessage = async () => {
    if (!inputValue.trim()) {
      message.warning('请输入消息内容');
      return;
    }

    if (!connected) {
      message.error('WebSocket未连接，请等待连接建立');
      return;
    }

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: inputValue,
      timestamp: Date.now(),
      status: 'sent',
    };

    setMessages((prev) => [...prev, userMessage]);
    const messageContent = inputValue;
    setInputValue('');

    try {
      // 发送到后端（放入感知器队列），异步处理，无需等待
      await messagesApi.sendMessage({
        message: messageContent,
        user_id: 'web_user',
      });
      console.log('✅ Message sent successfully');
    } catch (error: any) {
      console.error('发送消息失败:', error);
      message.error(error?.message || '发送消息失败');

      // 更新用户消息状态为失败
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === userMessage.id ? { ...msg, status: 'failed' } : msg
        )
      );
    }
  };

  // 清空对话
  const handleClearMessages = async () => {
    try {
      await messagesApi.clearHistory('web_user');
      setMessages([]);
      message.info('对话已清空');
    } catch (error) {
      console.error('清空对话失败:', error);
      message.error('清空对话失败');
    }
  };

  // 按回车发送（Shift+Enter换行）
  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const getAvatar = (role: string) => {
    switch (role) {
      case 'user':
        return <Avatar icon={<UserOutlined />} style={{ backgroundColor: '#0d9488' }} />;
      case 'assistant':
        return <Avatar icon={<RobotOutlined />} style={{ backgroundColor: '#6366f1' }} />;
      case 'system':
        return <Avatar icon={<RobotOutlined />} style={{ backgroundColor: '#f59e0b' }} />;
      default:
        return <Avatar />;
    }
  };

  const getStatusTag = (status?: string) => {
    switch (status) {
      case 'sending':
        return <Tag color="processing">发送中...</Tag>;
      case 'sent':
        return <Tag color="success">已发送</Tag>;
      case 'failed':
        return <Tag color="error">发送失败</Tag>;
      default:
        return null;
    }
  };

  return (
    <div style={{ padding: '24px', height: 'calc(100vh - 112px)', display: 'flex', flexDirection: 'column' }}>
      <Card
        title={`${aiName} 对话`}
        extra={
          <Space>
            <Tag color={connected ? 'success' : 'error'}>
              {connected ? 'WebSocket 已连接' : 'WebSocket 未连接'}
            </Tag>
            <Button
              size="small"
              icon={<ClearOutlined />}
              onClick={handleClearMessages}
            >
              清空对话
            </Button>
          </Space>
        }
        style={{ flex: 1, display: 'flex', flexDirection: 'column' }}
        bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 0 }}
      >
        {/* 消息列表 */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '24px',
            backgroundColor: '#f9fafb',
          }}
        >
          <List
            dataSource={messages}
            renderItem={(msg) => (
              <div
                key={msg.id}
                style={{
                  marginBottom: '24px',
                  display: 'flex',
                  justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  alignItems: 'flex-start',
                }}
              >
                <div
                  style={{
                    maxWidth: '70%',
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: '12px',
                    flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
                  }}
                >
                  {getAvatar(msg.role)}
                  <div>
                    <div style={{ marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Text strong style={{ fontSize: '12px', color: '#999' }}>
                        {msg.role === 'user' ? '你' : msg.role === 'assistant' ? aiName : '系统'}
                      </Text>
                      {msg.role !== 'system' && getStatusTag(msg.status)}
                      <Text type="secondary" style={{ fontSize: '12px' }}>
                        {new Date(msg.timestamp).toLocaleTimeString('zh-CN')}
                      </Text>
                    </div>
                    <div
                      style={{
                        padding: '12px 16px',
                        borderRadius: '12px',
                        backgroundColor:
                          msg.role === 'user'
                            ? '#0d9488'
                            : msg.role === 'system'
                            ? '#f0fdfa'
                            : '#ffffff',
                        color: msg.role === 'user' ? 'white' : msg.role === 'system' ? '#0f766e' : '#111827',
                        boxShadow: '0 1px 2px rgba(0,0,0,0.08)',
                        border: msg.role === 'user' ? 'none' : '1px solid #e5e7eb',
                        wordBreak: 'break-word',
                      }}
                    >
                      {msg.role === 'assistant' ? (
                        <div
                          style={{
                            color: 'inherit',
                            lineHeight: '1.6',
                          }}
                        >
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              p: ({ children }) => <p style={{ margin: '0.5em 0' }}>{children}</p>,
                              code: ({ node, inline, className, children, ...props }) => {
                                const match = /language-(\w+)/.exec(className || '');
                                return !inline ? (
                                  <code
                                    className={className}
                                    style={{
                                      display: 'block',
                                      padding: '8px 12px',
                                      backgroundColor: '#f6f8fa',
                                      borderRadius: '6px',
                                      fontSize: '14px',
                                      overflow: 'auto',
                                      fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                                    }}
                                    {...props}
                                  >
                                    {children}
                                  </code>
                                ) : (
                                  <code
                                    style={{
                                      padding: '2px 6px',
                                      backgroundColor: '#f6f8fa',
                                      borderRadius: '4px',
                                                                      fontSize: '0.9em',
                                      fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                                    }}
                                    {...props}
                                  >
                                    {children}
                                  </code>
                                );
                              },
                              pre: ({ children }) => <>{children}</>,
                              ul: ({ children }) => <ul style={{ margin: '0.5em 0', paddingLeft: '1.5em' }}>{children}</ul>,
                              ol: ({ children }) => <ol style={{ margin: '0.5em 0', paddingLeft: '1.5em' }}>{children}</ol>,
                              li: ({ children }) => <li style={{ marginBottom: '0.25em' }}>{children}</li>,
                              h1: ({ children }) => <h1 style={{ fontSize: '1.5em', margin: '0.5em 0', fontWeight: 'bold' }}>{children}</h1>,
                              h2: ({ children }) => <h2 style={{ fontSize: '1.3em', margin: '0.5em 0', fontWeight: 'bold' }}>{children}</h2>,
                              h3: ({ children }) => <h3 style={{ fontSize: '1.1em', margin: '0.5em 0', fontWeight: 'bold' }}>{children}</h3>,
                              strong: ({ children }) => <strong style={{ fontWeight: 'bold' }}>{children}</strong>,
                              em: ({ children }) => <em>{children}</em>,
                              blockquote: ({ children }) => (
                                <blockquote
                                  style={{
                                    borderLeft: '4px solid #dfe2e5',
                                    paddingLeft: '1em',
                                    margin: '0.5em 0',
                                    color: '#6b7280',
                                  }}
                                >
                                  {children}
                                </blockquote>
                              ),
                              a: ({ href, children }) => (
                                <a href={href} style={{ color: '#0d9488' }} target="_blank" rel="noopener noreferrer">
                                  {children}
                                </a>
                              ),
                              table: ({ children }) => (
                                <div style={{ overflow: 'auto', margin: '0.5em 0' }}>
                                  <table
                                    style={{
                                      borderCollapse: 'collapse',
                                      width: '100%',
                                      fontSize: '14px',
                                    }}
                                  >
                                    {children}
                                  </table>
                                </div>
                              ),
                              thead: ({ children }) => <thead style={{ backgroundColor: '#f6f8fa' }}>{children}</thead>,
                              th: ({ children }) => (
                                <th
                                  style={{
                                    border: '1px solid #dfe2e5',
                                                                    padding: '8px 12px',
                                                                    textAlign: 'left',
                                                                  }}
                                >
                                  {children}
                                </th>
                              ),
                              td: ({ children }) => (
                                <td
                                  style={{
                                    border: '1px solid #dfe2e5',
                                    padding: '8px 12px',
                                  }}
                                >
                                  {children}
                                </td>
                              ),
                            }}
                          >
                            {msg.content}
                          </ReactMarkdown>
                        </div>
                      ) : (
                        <Paragraph
                          style={{
                            margin: 0,
                            whiteSpace: 'pre-wrap',
                            color: msg.role === 'user' ? 'white' : 'inherit',
                          }}
                        >
                          {msg.content}
                        </Paragraph>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          />
          <div ref={messagesEndRef} />
        </div>

        <Divider style={{ margin: 0 }} />

        {/* 输入区域 */}
        <div style={{ padding: '16px', backgroundColor: '#fff' }}>
          <Space.Compact style={{ width: '100%' }}>
            <TextArea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="输入你的消息...（按 Enter 发送，Shift + Enter 换行）"
              autoSize={{ minRows: 2, maxRows: 6 }}
              onKeyPress={handleKeyPress}
              disabled={!connected}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSendMessage}
              size="large"
              disabled={!connected}
            >
              发送
            </Button>
          </Space.Compact>
          <div style={{ marginTop: '8px', fontSize: '12px', color: '#999' }}>
            💡 提示：按 Enter 发送消息，Shift + Enter 换行
          </div>
        </div>
      </Card>
    </div>
  );
};

export default ChatPage;
