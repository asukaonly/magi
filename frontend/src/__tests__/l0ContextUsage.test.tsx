import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { L0Tab } from '@/components/memory/L0Tab';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      const messages: Record<string, string> = {
        'memory.pages.workbench.contextUsageTitle': '最近一次回答的上下文',
        'memory.pages.workbench.contextUsageValue': '{{used}} / {{window}} tokens',
        'memory.pages.workbench.contextUsageThreshold': '达到 {{threshold}} tokens 时开始考虑压缩',
        'memory.pages.workbench.contextUsageUpdated': '记录于 {{time}}',
        'memory.pages.workbench.shellEmpty': '工作台为空',
        'memory.l0.workbench': '工作台',
        'memory.l0.sessions': '会话',
        'memory.l0.activeSessions': '活跃会话',
        'memory.l0.totalGoals': '目标',
        'memory.l0.totalEntities': '实体',
        'memory.l0.totalTactics': '策略',
        'memory.l0.goalStack': '目标栈',
        'memory.l0.activeEntities': '关注实体',
        'memory.l0.tactics': '策略',
        'memory.l0.noGoals': '暂无目标',
        'memory.l0.noEntities': '暂无实体',
        'memory.l0.noTactics': '暂无策略',
      };
      return (messages[key] ?? key).replace(
        /\{\{(\w+)\}\}/g,
        (_, name: string) => String(options?.[name] ?? ''),
      );
    },
  }),
}));

describe('L0 context usage inspection', () => {
  it('shows the durable latest-reply snapshot beside the workbench', () => {
    render(
      <L0Tab
        stats={{
          active_sessions: 1,
          total_goals: 0,
          total_entities: 0,
          total_tactics: 0,
        }}
        sessions={[
          {
            session_id: 'session-1',
            display_title: '统计问题',
            status: 'active',
            started_at: 1,
            last_active_at: 2,
            goal_count: 0,
            entity_count: 0,
            tactic_count: 0,
          },
        ]}
        workbench={{
          session: { session_id: 'session-1' },
          goal_stack: [],
          active_entities: [],
          temporary_tactics: [],
          context_usage: {
            turn_id: 'turn-1',
            used_tokens: 12_345,
            window_size: 256_000,
            input_capacity: 248_000,
            threshold: 192_000,
            measurement: 'actual',
            updated_at_ms: 2_000,
          },
        }}
        selectedSessionId="session-1"
        onSelectSession={vi.fn()}
      />,
    );

    expect(screen.getByText('最近一次回答的上下文')).toBeInTheDocument();
    expect(screen.getByText('12,345 / 256,000 tokens')).toBeInTheDocument();
    expect(screen.getByText('达到 192,000 tokens 时开始考虑压缩')).toBeInTheDocument();
  });
});
