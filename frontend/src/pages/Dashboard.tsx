import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, CheckCircle2, MessageSquare, Settings, Sparkles, UserRound } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

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
  const stats = useMemo(() => mockStats, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">欢迎使用 Magi AI Framework</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          智能代理框架，支持多层记忆和动态人格配置
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { title: '总消息数', value: stats.totalMessages, color: 'text-teal-600' },
          { title: '今日消息', value: stats.todayMessages, color: 'text-emerald-600' },
          { title: '活跃能力', value: stats.activeCapabilities, color: 'text-indigo-600' },
          { title: '内存使用', value: `${stats.memoryUsage}%`, color: 'text-amber-600' },
        ].map((item) => (
          <Card key={item.title}>
            <CardContent className="p-5">
              <p className="text-xs font-medium text-muted-foreground">{item.title}</p>
              <p className={cn('mt-2 text-3xl font-semibold', item.color)}>{item.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>快捷操作</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Button className="w-full justify-between" onClick={() => navigate('/chat')}>
              <span className="inline-flex items-center gap-2">
                <MessageSquare className="h-4 w-4" />
                开始对话
              </span>
              <ArrowRight className="h-4 w-4" />
            </Button>
            <Button variant="outline" className="w-full justify-between" onClick={() => navigate('/personality')}>
              <span className="inline-flex items-center gap-2">
                <UserRound className="h-4 w-4" />
                管理人格
              </span>
              <ArrowRight className="h-4 w-4 text-muted-foreground" />
            </Button>
            <Button variant="outline" className="w-full justify-between" onClick={() => navigate('/settings')}>
              <span className="inline-flex items-center gap-2">
                <Settings className="h-4 w-4" />
                系统设置
              </span>
              <ArrowRight className="h-4 w-4 text-muted-foreground" />
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>系统信息</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">框架版本</p>
                <p className="mt-1 text-sm font-semibold">Magi v0.1.0</p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">记忆架构</p>
                <p className="mt-1 text-sm font-semibold">L1-L5 五层</p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">事件系统</p>
                <p className="mt-1 text-sm font-semibold">MessageBus</p>
              </div>
            </div>

            <div className="h-px bg-border" />

            <div>
              <p className="mb-3 text-sm font-medium">最近活动</p>
              <div className="space-y-3">
                {recentActivities.map((activity, index) => (
                  <div key={`${activity.text}-${index}`} className="flex items-start gap-2">
                    {index === 0 ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 text-teal-600" />
                    ) : (
                      <Sparkles className="mt-0.5 h-4 w-4 text-muted-foreground" />
                    )}
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm">{activity.text}</span>
                        {index === 0 && <Badge variant="secondary">最新</Badge>}
                      </div>
                      <p className="text-xs text-muted-foreground">{activity.time}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default Dashboard;
