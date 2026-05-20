import React from 'react';
import { useTranslation } from 'react-i18next';
import { History } from 'lucide-react';
import { TasksPageFrame } from './TasksPageFrame';

export const ScheduleActivityPage: React.FC = () => {
  const { t } = useTranslation('app');
  return (
    <TasksPageFrame
      title={t('tasks.activity.pageTitle')}
      subtitle={t('tasks.activity.pageSubtitle')}
      icon={<History className="h-5 w-5 text-muted-foreground" />}
    >
      <div className="text-sm text-muted-foreground">…</div>
    </TasksPageFrame>
  );
};
