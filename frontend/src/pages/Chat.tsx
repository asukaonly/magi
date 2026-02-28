/**
 * Chat页面 - 与Agent对话
 * 所有通信通过 WebSocket 进行
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Bot, Eraser, Plus, Send, UserRound } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { AutoResizeTextarea } from '@/components/ui/auto-resize-textarea';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AnimatePresence, motion } from 'framer-motion';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  status?: 'sending' | 'sent' | 'failed';
}

// WebSocket 消息类型
interface WSMessage {
  type: string;
  data?: any;
  event?: string;
  channel?: string;
  sid?: string;
  message?: string;
}

export const ChatPage: React.FC = () => {
  const { t, i18n } = useTranslation('app');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [aiName, setAiName] = useState<string>('AI');
  const [aiAvatar, setAiAvatar] = useState<string>('');
  const [connected, setConnected] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [initialized, setInitialized] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectCountRef = useRef(0);

  // WebSocket 配置
  const WS_CONFIG = {
    baseUrl: 'ws://localhost:8000/ws',
    maxReconnectAttempts: 10,
    baseDelay: 1000,
    maxDelay: 30000,
  };

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 计算重连延迟（指数退避）
  const getReconnectDelay = useCallback(() => {
    const delay = Math.min(
      WS_CONFIG.baseDelay * Math.pow(2, reconnectCountRef.current),
      WS_CONFIG.maxDelay
    );
    return delay + Math.random() * 1000;
  }, []);

  // 发送 WebSocket 消息
  const sendWS = useCallback((type: string, data?: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, ...data }));
    }
  }, []);

  // 处理 WebSocket 消息
  const handleWSMessage = useCallback((data: WSMessage) => {
    console.log('WS message:', data);

    switch (data.type) {
      case 'subscribed':
        console.log('Subscribed to room:', data.channel);
        // 订阅成功后，按顺序请求：当前会话 → 历史记录 → 人格信息
        sendWS('get_current_session');
        break;

      case 'current_session':
        // 收到当前会话 ID
        if (data.data) {
          setSessionId(data.data.session_id);
          if (data.data.session_id) {
            localStorage.setItem('chat_session_web_user', data.data.session_id);
          }
          // 获取历史记录
          sendWS('get_history', { session_id: data.data.session_id });
        }
        break;

      case 'history':
        // 收到历史记录
        if (data.data) {
          setSessionId(data.data.session_id);
          if (data.data.messages && data.data.messages.length > 0) {
            const chatMessages: ChatMessage[] = data.data.messages.map((msg: any, index: number) => ({
              id: `history-${index}`,
              role: msg.role,
              content: msg.content,
              timestamp: msg.timestamp * 1000,
              status: 'sent' as const,
            }));
            setMessages(chatMessages);
          }
          // 获取人格信息
          sendWS('get_personality');
        }
        break;

      case 'personality_info':
        // 收到人格信息
        if (data.data) {
          setAiName(data.data.name || 'AI');
          setAiAvatar(data.data.avatar || '');

          // 如果没有历史消息，显示问候语
          setMessages(prev => {
            if (prev.length === 0 && data.data.greeting) {
              return [{
                id: 'welcome',
                role: 'assistant',
                content: data.data.greeting,
                timestamp: Date.now(),
              }];
            }
            return prev;
          });
          setInitialized(true);
        }
        break;

      case 'message_sent':
        // 消息发送确认
        console.log('Message sent:', data.data);
        break;

      case 'error':
        console.error('WS error:', data.message);
        toast.error(data.message || 'WebSocket error');
        break;
    }

    // 处理 Agent 回复（通过 event 字段）
    if (data.event === 'agent_response' && data.data) {
      const assistantMessage: ChatMessage = {
        id: `ws-${Date.now()}`,
        role: 'assistant',
        content: data.data.response,
        timestamp: data.data.timestamp * 1000,
        status: 'sent',
      };
      setMessages(prev => [...prev, assistantMessage]);
    }
  }, [sendWS]);

  // 创建 WebSocket 连接
  const connectWebSocket = useCallback(() => {
    const userId = 'web_user';
    const room = `user_${userId}`;

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const websocket = new WebSocket(WS_CONFIG.baseUrl);

    websocket.onopen = () => {
      console.log('WebSocket connected');
      setConnected(true);
      reconnectCountRef.current = 0;
      setInitialized(false);

      // 订阅用户专属房间
      websocket.send(JSON.stringify({
        type: 'subscribe',
        channel: room,
      }));
    };

    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWSMessage(data);
      } catch (error) {
        console.error('Failed to parse WS message:', error);
      }
    };

    websocket.onclose = (event) => {
      console.log('WebSocket disconnected:', event.code, event.reason);
      setConnected(false);
      setInitialized(false);

      if (event.code !== 1000 && reconnectCountRef.current < WS_CONFIG.maxReconnectAttempts) {
        const delay = getReconnectDelay();
        console.log(`Reconnecting in ${Math.round(delay / 1000)}s`);

        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectCountRef.current++;
          connectWebSocket();
        }, delay);
      } else if (reconnectCountRef.current >= WS_CONFIG.maxReconnectAttempts) {
        toast.error(t('chat.reconnectFailed'));
      }
    };

    websocket.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    wsRef.current = websocket;
  }, [getReconnectDelay, handleWSMessage, t]);

  // 初始化 WebSocket
  useEffect(() => {
    connectWebSocket();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounting');
      }
    };
  }, [connectWebSocket]);

  // 发送消息（通过 WebSocket）
  const handleSendMessage = () => {
    if (!inputValue.trim()) {
      toast.warning(t('chat.emptyInput'));
      return;
    }

    if (!connected || wsRef.current?.readyState !== WebSocket.OPEN) {
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

    setMessages(prev => [...prev, userMessage]);
    const messageContent = inputValue;
    setInputValue('');

    // 通过 WebSocket 发送消息
    sendWS('send_message', {
      user_id: 'web_user',
      session_id: sessionId,
      message: messageContent,
    });
  };

  // 清空对话（仍需 HTTP，因为需要操作数据库）
  const handleClearMessages = async () => {
    try {
      const { messagesApi } = await import('../api');
      await messagesApi.clearHistory('web_user', sessionId || undefined);
      setMessages([]);
      toast.info(t('chat.cleared'));
    } catch (error) {
      console.error('清空对话失败:', error);
      toast.error(t('chat.clearFailed'));
    }
  };

  // 新建会话（仍需 HTTP，因为需要操作数据库）
  const handleNewSession = async () => {
    try {
      const { messagesApi } = await import('../api');
      const result = await messagesApi.createNewSession('web_user');
      if (!result.success || !result.session_id) {
        toast.error(t('chat.createSessionFailed'));
        return;
      }
      setSessionId(result.session_id);
      localStorage.setItem('chat_session_web_user', result.session_id);
      setMessages([]);

      // 重新获取人格信息以显示问候语
      sendWS('get_personality');

      toast.success(t('chat.sessionSwitched'));
    } catch (error) {
      console.error('创建新会话失败:', error);
      toast.error(t('chat.createSessionFailed'));
    }
  };

  // 按回车发送
  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // 头像渲染
  const getAvatar = (role: string) => {
    switch (role) {
      case 'user':
        return (
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-teal-600 text-white">
            <UserRound className="h-5 w-5" />
          </div>
        );
      case 'assistant':
        const initial = aiName?.charAt(0)?.toUpperCase() || 'A';
        // 处理 avatar URL
        let avatarSrc = aiAvatar;
        if (avatarSrc && avatarSrc.startsWith('/')) {
          // 相对路径，拼接后端基础 URL
          const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';
          const baseUrl = apiBaseUrl.replace(/\/api\/?$/, ''); // 移除 /api 后缀
          avatarSrc = `${baseUrl}${avatarSrc}`;
        }

        // 判断 avatar 是 URL 还是 emoji/文字
        const isImageUrl = avatarSrc && avatarSrc.startsWith('http');
        if (isImageUrl) {
          return (
            <div className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-indigo-500">
              <img src={avatarSrc} alt={aiName} className="h-full w-full object-cover" />
            </div>
          );
        }
        return (
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-500 text-lg text-white">
            {aiAvatar || initial}
          </div>
        );
      case 'system':
        return (
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-amber-500 text-white">
            <Bot className="h-5 w-5" />
          </div>
        );
      default:
        return null;
    }
  };

  // 状态标签
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
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden">
      {/* 顶部区域 */}
      <div className="shrink-0 px-6 pb-3 pt-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {getAvatar('assistant')}
            <span className="text-sm font-medium">{aiName}</span>
          </div>
          <div className="flex items-center gap-2">
            <Badge className="shadow-sm" variant={connected ? 'default' : 'destructive'}>
              {connected ? t('chat.connected') : t('chat.disconnected')}
            </Badge>
            <Button size="sm" variant="ghost" onClick={handleClearMessages} className="rounded-full">
              <Eraser className="h-4 w-4" />
            </Button>
            <Button size="sm" variant="ghost" onClick={handleNewSession} className="rounded-full">
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      {/* 消息区 */}
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-4 pt-2">
        {messages.map((msg) => (
          <motion.div
            key={msg.id}
            initial={{ opacity: 0, y: 10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className={`mb-6 flex items-start ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div className={`flex max-w-[72%] items-start gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
              {getAvatar(msg.role)}
              <div className={`flex max-w-full flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                <div className="mb-2 flex w-fit items-center gap-2">
                  <span className="text-xs font-semibold text-muted-foreground">
                    {msg.role === 'user' ? t('chat.you') : msg.role === 'assistant' ? aiName : t('chat.system')}
                  </span>
                  {msg.role !== 'system' && getStatusTag(msg.status)}
                  <span className="text-xs text-muted-foreground">
                    {new Date(msg.timestamp).toLocaleTimeString(i18n.language === 'en' ? 'en-US' : 'zh-CN')}
                  </span>
                </div>
                <div
                  className="max-w-full"
                  style={{
                    display: 'inline-block',
                    width: 'fit-content',
                    padding: '12px 16px',
                    borderRadius: '12px',
                    backgroundColor: msg.role === 'user' ? '#0d9488' : msg.role === 'system' ? '#f0fdfa' : '#ffffff',
                    color: msg.role === 'user' ? 'white' : msg.role === 'system' ? '#0f766e' : '#111827',
                    boxShadow: '0 1px 2px rgba(0,0,0,0.08)',
                    border: msg.role === 'user' ? 'none' : '1px solid #e5e7eb',
                    wordBreak: 'break-word',
                  }}
                >
                  {msg.role === 'assistant' ? (
                    <div style={{ color: 'inherit', lineHeight: '1.6' }}>
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
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

      {/* 底部输入区域 */}
      <div className="shrink-0 bg-background/95 px-6 pb-4 pt-3 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="flex w-full items-end gap-3">
          <AutoResizeTextarea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder={t('chat.inputPlaceholder')}
            onKeyDown={handleKeyPress}
            disabled={!connected}
            minHeight={96}
            className="max-h-64 resize-none rounded-xl border-0 bg-muted/40 px-4 py-3 text-sm shadow-none focus-visible:ring-1"
          />
          <Button
            onClick={handleSendMessage}
            disabled={!connected}
            className="h-11 rounded-xl px-5"
          >
            <Send className="mr-1 h-4 w-4" />
            {t('chat.send')}
          </Button>
        </div>
        <div className="mt-2 text-center text-xs text-muted-foreground">
          {t('chat.tip')}
        </div>
      </div>
    </div>
  );
};

export default ChatPage;
