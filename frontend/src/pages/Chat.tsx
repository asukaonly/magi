/**
 * Chat页面 - 与Agent对话（使用正确的Agent架构）
 * 流程：用户消息 → 感知器队列 → Agent循环 → WebSocket推送回复
 */
import React, { useState, useRef, useEffect } from 'react';
import { Bot, Eraser, Plus, Send, UserRound } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { messagesApi, ConversationHistory } from '../api';
import { personalityApi } from '../api/modules/personality';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AnimatePresence, motion } from 'framer-motion';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  agent_id?: string;
  status?: 'sending' | 'sent' | 'failed';
}

export const ChatPage: React.FC = () => {
  const { t, i18n } = useTranslation('app');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [aiName, setAiName] = useState<string>('AI Agent');
  const [_ws, setWs] = useState<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [_sid, setSid] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
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
        const current = await messagesApi.getCurrentSession('web_user');
        const resolvedSession = current.session_id;
        setSessionId(resolvedSession);
        if (resolvedSession) {
          localStorage.setItem('chat_session_web_user', resolvedSession);
        }

        const history: ConversationHistory = await messagesApi.getHistory('web_user', resolvedSession || undefined);
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
            const greeting = greetingResponse?.data?.greeting || t('chat.greetingFallback');
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
              content: t('chat.greetingFallback'),
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
          content: t('chat.greetingSimpleFallback'),
          timestamp: Date.now(),
        };
        setMessages([defaultWelcome]);
      }
    };

    loadHistory();
  }, [t]);

  // 发送消息
  const handleSendMessage = async () => {
    if (!inputValue.trim()) {
      toast.warning(t('chat.emptyInput'));
      return;
    }

    if (!connected) {
      toast.error(t('chat.wsNotConnected'));
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
        session_id: sessionId || undefined,
      });
      console.log('✅ Message sent successfully');
    } catch (error: any) {
      console.error('发送消息失败:', error);
      toast.error(error?.message || t('chat.sendFailed'));

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
      await messagesApi.clearHistory('web_user', sessionId || undefined);
      setMessages([]);
      toast.info(t('chat.cleared'));
    } catch (error) {
      console.error('清空对话失败:', error);
      toast.error(t('chat.clearFailed'));
    }
  };

  const handleNewSession = async () => {
    try {
      const result = await messagesApi.createNewSession('web_user');
      if (!result.success || !result.session_id) {
        toast.error(t('chat.createSessionFailed'));
        return;
      }
      setSessionId(result.session_id);
      localStorage.setItem('chat_session_web_user', result.session_id);
      setMessages([]);
      toast.success(t('chat.sessionSwitched'));
    } catch (error) {
      console.error('创建新会话失败:', error);
      toast.error(t('chat.createSessionFailed'));
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
        return (
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-teal-600 text-white">
            <UserRound className="h-4 w-4" />
          </div>
        );
      case 'assistant':
        return (
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-indigo-500 text-white">
            <Bot className="h-4 w-4" />
          </div>
        );
      case 'system':
        return (
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-500 text-white">
            <Bot className="h-4 w-4" />
          </div>
        );
      default:
        return null;
    }
  };

  const getStatusTag = (status?: string) => {
    switch (status) {
      case 'sending':
        return <Badge variant="secondary">{t('chat.sending')}</Badge>;
      case 'sent':
        return <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">{t('chat.sent')}</Badge>;
      case 'failed':
        return <Badge variant="destructive">{t('chat.failed')}</Badge>;
      default:
        return null;
    }
  };

  return (
    <div className="flex h-[calc(100vh-112px)] flex-col p-6">
      <Card className="flex h-full flex-col">
        <CardHeader className="flex-row items-center justify-between space-y-0 border-b">
          <CardTitle>{t('chat.title', { name: aiName })}</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant={connected ? 'default' : 'destructive'}>
              {connected ? t('chat.connected') : t('chat.disconnected')}
            </Badge>
            <Button size="sm" variant="outline" onClick={handleClearMessages}>
              <Eraser className="mr-1 h-4 w-4" />
              {t('chat.clear')}
            </Button>
            <Button size="sm" variant="outline" onClick={handleNewSession}>
              <Plus className="mr-1 h-4 w-4" />
              {t('chat.newSession')}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="flex flex-1 flex-col p-0">
        {/* 消息列表 */}
        <div className="flex-1 overflow-y-auto bg-muted/30 p-6">
          {messages.map((msg) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 10, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -6, scale: 0.98 }}
                transition={{ duration: 0.2, ease: 'easeOut' }}
                className={`mb-6 flex items-start ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div className={`flex max-w-[70%] items-start gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                  {getAvatar(msg.role)}
                  <div>
                    <div className="mb-2 flex items-center gap-2">
                      <span className="text-xs font-semibold text-muted-foreground">
                        {msg.role === 'user' ? t('chat.you') : msg.role === 'assistant' ? aiName : t('chat.system')}
                      </span>
                      {msg.role !== 'system' && getStatusTag(msg.status)}
                      <span className="text-xs text-muted-foreground">
                        {new Date(msg.timestamp).toLocaleTimeString(i18n.language === 'en' ? 'en-US' : 'zh-CN')}
                      </span>
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
                        <div style={{ color: 'inherit', lineHeight: '1.6' }}>
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              p: ({ children }) => <p style={{ margin: '0.5em 0' }}>{children}</p>,
                              code: ({ className, children, ...props }) => (
                                <code
                                  className={className}
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
                              ),
                              pre: ({ children }) => (
                                <pre
                                  style={{
                                    margin: '0.5em 0',
                                    padding: '8px 12px',
                                    backgroundColor: '#f6f8fa',
                                    borderRadius: '6px',
                                    overflow: 'auto',
                                  }}
                                >
                                  {children}
                                </pre>
                              ),
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
                        <p style={{ margin: 0, whiteSpace: 'pre-wrap', color: msg.role === 'user' ? 'white' : 'inherit' }}>
                          {msg.content}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              </motion.div>
          ))}
          <AnimatePresence>
            {!connected && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="mb-3 mt-1 text-center text-xs text-amber-700"
              >
                {t('chat.connectingHint')}
              </motion.div>
            )}
          </AnimatePresence>
          <div ref={messagesEndRef} />
        </div>
        <div className="h-px bg-border" />

        {/* 输入区域 */}
        <div className="bg-background p-4">
          <div className="flex w-full gap-2">
            <Textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder={t('chat.inputPlaceholder')}
              rows={2}
              onKeyDown={handleKeyPress}
              disabled={!connected}
            />
            <Button
              onClick={handleSendMessage}
              disabled={!connected}
              className="h-auto"
            >
              <Send className="mr-1 h-4 w-4" />
              {t('chat.send')}
            </Button>
          </div>
          <div className="mt-2 text-xs text-muted-foreground">
            {t('chat.tip')}
          </div>
        </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default ChatPage;
