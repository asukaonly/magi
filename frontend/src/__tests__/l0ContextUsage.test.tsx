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
        'memory.l0.workbench': '当前关注',
        'memory.l0.sessions': '会话',
        'memory.l0.activeSessions': '活跃会话',
        'memory.l0.totalAttentionItems': '关注项',
        'memory.l0.attentionItems': '关注内容',
        'memory.l0.attentionCount': '{{count}} 条关注',
        'memory.l0.workbenchItemCount': '{{count}} 条可查看记录',
        'memory.l0.kinds.focus': '当前话题',
        'memory.l0.kinds.situation': '当前情况',
        'memory.l0.kinds.open_loop': '未完线索',
        'memory.l0.kinds.active_object': '相关人物或事物',
        'memory.l0.kinds.constraint': '当前约束',
        'memory.l0.kinds.consensus': '已经确认',
        'memory.l0.statuses.active': '正在关注',
        'memory.l0.statuses.background': '暂时放下',
        'memory.l0.statuses.resolved': '已经解决',
        'memory.l0.statuses.superseded': '已被替代',
        'memory.l0.evidenceModes.direct': '明确表达',
        'memory.l0.evidenceModes.inferred': '暂时推断',
        'memory.l0.salience': '重要程度',
        'memory.l0.confidence': '可信程度',
        'memory.l0.lastReinforced': '最近提到',
        'memory.l0.expiresAt': '最晚保留至',
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
          total_attention_items: 0,
        }}
        sessions={[
          {
            session_id: 'session-1',
            display_title: '统计问题',
            status: 'active',
            started_at: 1,
            last_active_at: 2,
            attention_count: 0,
          },
        ]}
        workbench={{
          session: { session_id: 'session-1' },
          attention_items: [],
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

  it('renders every attention kind with lifecycle and evidence labels', () => {
    const kinds = [
      ['focus', '正在比较两张专辑的风格变化', 'active', 'direct'],
      ['situation', '用户今天有些疲惫', 'active', 'inferred'],
      ['open_loop', '还没有决定更喜欢哪一张', 'background', 'direct'],
      ['active_object', '正在讨论 Frog in Boiling Water', 'active', 'direct'],
      ['constraint', '暂时不要给出购买建议', 'resolved', 'direct'],
      ['consensus', '已经确认这是新专辑', 'superseded', 'inferred'],
    ] as const;

    render(
      <L0Tab
        stats={{ active_sessions: 1, total_attention_items: kinds.length }}
        sessions={[{
          session_id: 'session-1',
          display_title: '专辑闲聊',
          status: 'active',
          started_at: 1,
          last_active_at: 2,
          attention_count: kinds.length,
        }]}
        workbench={{
          session: { session_id: 'session-1' },
          attention_items: kinds.map(([kind, summary, status, evidenceMode], index) => ({
            item_id: `attention-${index}`,
            kind,
            summary,
            status,
            salience: 0.8,
            confidence: 0.9,
            evidence_mode: evidenceMode,
            source_turn_ids: [`turn-${index}`],
            source_event_ids: [],
            entity_id: null,
            task_id: null,
            first_seen_at: 1,
            last_reinforced_at: 2,
            expires_at: null,
            supersedes_item_id: null,
            metadata: {},
          })),
        }}
        selectedSessionId="session-1"
        onSelectSession={vi.fn()}
      />,
    );

    expect(screen.getByText('当前话题')).toBeInTheDocument();
    expect(screen.getByText('当前情况')).toBeInTheDocument();
    expect(screen.getByText('未完线索')).toBeInTheDocument();
    expect(screen.getByText('相关人物或事物')).toBeInTheDocument();
    expect(screen.getByText('当前约束')).toBeInTheDocument();
    expect(screen.getByText('已经确认')).toBeInTheDocument();
    expect(screen.getByText('暂时放下')).toBeInTheDocument();
    expect(screen.getByText('已经解决')).toBeInTheDocument();
    expect(screen.getByText('已被替代')).toBeInTheDocument();
    expect(screen.getAllByText('明确表达')).toHaveLength(4);
    expect(screen.getAllByText('暂时推断')).toHaveLength(2);
  });
});
