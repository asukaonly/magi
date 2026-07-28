import React, { useMemo } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ArrowRight, CheckCircle2, MessageSquare, Settings, Sparkles, UserRound } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useChatShellStore } from '@/stores';
import { cn } from '@/lib/utils';

const mockStats = {
  totalMessages: 1234,
  todayMessages: 56,
  activeCapabilities: 23,
  memoryUsage: 67,
};

const Dashboard: React.FC = () => {
  const { t } = useTranslation('app');
  const navigate = useNavigate();
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const clearSettingsNavigationIntent = useChatShellStore((state) => state.clearSettingsNavigationIntent);
  const stats = useMemo(() => mockStats, []);
  const recentActivities = useMemo(
    () => [
      { text: t('dashboard.activity.userMessage'), time: t('dashboard.activity.time2min') },
      { text: t('dashboard.activity.taskDone'), time: t('dashboard.activity.time5min') },
      { text: t('dashboard.activity.personalityUpdated'), time: t('dashboard.activity.time1hour') },
      { text: t('dashboard.activity.newCapability'), time: t('dashboard.activity.time2hour') },
      { text: t('dashboard.activity.systemStarted'), time: t('dashboard.activity.today') },
    ],
    [t]
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">{t('dashboard.welcomeTitle')}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t('dashboard.welcomeSubtitle')}
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { title: t('dashboard.stats.totalMessages'), value: stats.totalMessages, color: 'text-teal-600' },
          { title: t('dashboard.stats.todayMessages'), value: stats.todayMessages, color: 'text-emerald-600' },
          { title: t('dashboard.stats.activeCapabilities'), value: stats.activeCapabilities, color: 'text-indigo-600' },
          { title: t('dashboard.stats.memoryUsage'), value: `${stats.memoryUsage}%`, color: 'text-amber-600' },
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
            <CardTitle>{t('dashboard.quickActions.title')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Button className="w-full justify-between" onClick={() => navigate('/chat')}>
              <span className="inline-flex items-center gap-2">
                <MessageSquare className="h-4 w-4" />
                {t('dashboard.quickActions.startChat')}
              </span>
              <ArrowRight className="h-4 w-4" />
            </Button>
            <Button variant="outline" className="w-full justify-between" onClick={() => navigate('/personality')}>
              <span className="inline-flex items-center gap-2">
                <UserRound className="h-4 w-4" />
                {t('dashboard.quickActions.managePersonality')}
              </span>
              <ArrowRight className="h-4 w-4 text-muted-foreground" />
            </Button>
            <Button variant="outline" className="w-full justify-between" onClick={() => { clearSettingsNavigationIntent(); setActivePanel('settings'); }}>
              <span className="inline-flex items-center gap-2">
                <Settings className="h-4 w-4" />
                {t('dashboard.quickActions.openSettings')}
              </span>
              <ArrowRight className="h-4 w-4 text-muted-foreground" />
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t('dashboard.systemInfo.title')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">{t('dashboard.systemInfo.frameworkVersion')}</p>
                <p className="mt-1 text-sm font-semibold">Magi v0.1.0</p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">{t('dashboard.systemInfo.memoryArchitecture')}</p>
                <p className="mt-1 text-sm font-semibold">{t('dashboard.systemInfo.memoryArchitectureValue')}</p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">{t('dashboard.systemInfo.eventSystem')}</p>
                <p className="mt-1 text-sm font-semibold">MessageBus</p>
              </div>
            </div>

            <div className="h-px bg-border" />

            <div>
              <p className="mb-3 text-sm font-medium">{t('dashboard.systemInfo.recentActivity')}</p>
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
                        {index === 0 && <Badge variant="secondary">{t('dashboard.systemInfo.latest')}</Badge>}
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
