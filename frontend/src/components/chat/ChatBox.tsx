/**
 * Chat component
 */
import React, { useState, useEffect, useRef } from 'react';
import { Bot, Loader2, Send, UserRound } from 'lucide-react';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { messagesApi } from '../../api';

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
  const connected = false;
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto scroll to bottom
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Send message
  const handleSendMessage = async () => {
    if (!inputValue.trim()) {
      toast.warning('请输入消息内容');
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
      // Send to backend
      const response = await messagesApi.sendMessage({
        message: inputValue,
        user_id: 'web_user',
      });

      if (response.success) {
        toast.success('消息发送成功');

        // Simulate AI response (should receive from WebSocket in production)
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
      toast.error('发送消息失败');
      setLoading(false);
    }
  };

  // Clear messages
  const handleClearMessages = () => {
    setMessages([]);
    toast.info('已清空聊天记录');
  };

  return (
    <Card className="flex h-[600px] flex-col">
      <CardHeader className="flex-row items-center justify-between border-b py-4">
        <CardTitle className="text-base">智能对话</CardTitle>
        <div className="flex items-center gap-2">
          <Badge variant={connected ? 'success' : 'secondary'}>{connected ? '已连接' : '未连接'}</Badge>
          <Button size="sm" variant="outline" onClick={handleClearMessages}>清空</Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col p-0">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto bg-muted/30 p-4">
        {messages.map((msg) => (
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
                <div className={`flex h-8 w-8 items-center justify-center rounded-full text-white ${msg.role === 'user' ? 'bg-primary' : 'bg-primary/70'}`}>
                  {msg.role === 'user' ? <UserRound className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
                </div>
                <div
                  style={{
                    padding: '8px 12px',
                    borderRadius: '8px',
                    backgroundColor: msg.role === 'user' ? 'hsl(var(--primary))' : 'white',
                    color: msg.role === 'user' ? 'white' : 'black',
                    boxShadow: '0 1px 2px rgba(0,0,0,0.1)',
                  }}
                >
                  <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                  </p>
                  <span style={{ fontSize: '12px', color: '#6b7280' }}>
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </span>
                </div>
              </div>
            </div>
        ))}
        {loading && (
          <div style={{ textAlign: 'center', padding: '8px' }}>
            <Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> AI正在思考...
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="border-t bg-background p-4">
        <div className="flex w-full gap-2">
          <Textarea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="输入你的消息..."
            rows={2}
            onKeyDown={(e) => {
              if (e.shiftKey) return;
              // Ignore Enter key during IME composition
              if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void handleSendMessage();
              }
            }}
            disabled={loading}
          />
          <Button
            onClick={handleSendMessage}
            disabled={loading}
          >
            <Send className="mr-1 h-4 w-4" />
            发送
          </Button>
        </div>
        <div style={{ marginTop: '8px', fontSize: '12px', color: '#999' }}>
          按 Enter 发送，Shift + Enter 换行
        </div>
      </div>
      </CardContent>
    </Card>
  );
};

export default ChatBox;
