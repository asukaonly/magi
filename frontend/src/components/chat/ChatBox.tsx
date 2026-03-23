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
import { cn } from '@/lib/utils';

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
  const isComposingRef = useRef(false);
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
        session_id: 'demo-session',
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
          <Badge variant={connected ? 'default' : 'secondary'}>{connected ? '已连接' : '未连接'}</Badge>
          <Button size="sm" variant="outline" onClick={handleClearMessages}>清空</Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col p-0">
        {/* Message list */}
        <div className="flex-1 overflow-y-auto bg-muted/30 p-4">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                'mb-4 flex',
                msg.role === 'user' ? 'justify-end' : 'justify-start'
              )}
            >
              <div
                className={cn(
                  'flex max-w-[70%] items-start gap-2',
                  msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'
                )}
              >
                <div
                  className={cn(
                    'flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-primary-foreground',
                    msg.role === 'user' ? 'bg-primary' : 'bg-primary/80'
                  )}
                >
                  {msg.role === 'user' ? (
                    <UserRound className="h-4 w-4" />
                  ) : (
                    <Bot className="h-4 w-4" />
                  )}
                </div>
                <div
                  className={cn(
                    'rounded-xl px-3 py-2 shadow-sm',
                    msg.role === 'user'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-card text-card-foreground border border-border/50'
                  )}
                >
                  <p className="m-0 whitespace-pre-wrap text-sm leading-relaxed">
                    {msg.content}
                  </p>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </span>
                </div>
              </div>
            </div>
          ))}
          {loading && (
            <div className="py-2 text-center text-sm text-muted-foreground">
              <Loader2 className="mr-1 inline h-4 w-4 animate-spin" />
              AI正在思考...
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
              onCompositionStart={() => { isComposingRef.current = true; }}
              onCompositionEnd={() => { isComposingRef.current = false; }}
              onKeyDown={(e) => {
                if (e.shiftKey) return;
                if (e.key === 'Enter' && !isComposingRef.current) {
                  e.preventDefault();
                  void handleSendMessage();
                }
              }}
              disabled={loading}
            />
            <Button onClick={handleSendMessage} disabled={loading}>
              <Send className="mr-1 h-4 w-4" />
              发送
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            按 Enter 发送，Shift + Enter 换行
          </p>
        </div>
      </CardContent>
    </Card>
  );
};

export default ChatBox;
