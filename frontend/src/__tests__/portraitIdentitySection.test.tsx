import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import { PortraitIdentitySection } from '@/components/memory/portrait/PortraitIdentitySection';
import { profileApi } from '@/api/modules/profile';

vi.mock('react-i18next', async () => {
  const labels: Record<string, string> = {
    'memory.portrait.loading': '正在读取关于你的内容…',
    'memory.portrait.identity.title': '你是谁',
    'memory.portrait.identity.fields.preferredFormOfAddress': '称呼',
    'memory.portrait.identity.fields.realName': '真实姓名',
    'memory.portrait.identity.fields.birthDate': '生日',
    'memory.portrait.identity.fields.homeLocation': '常住地',
    'memory.portrait.identity.fields.disallowedFormsOfAddress': '不希望使用的称呼',
    'memory.portrait.identity.empty': '未填写',
    'memory.portrait.identity.add': '点击补充',
    'memory.portrait.identity.editField': '修改{{field}}',
    'memory.portrait.identity.source': '来源：{{source}}',
    'memory.portrait.identity.sources.settings_profile': '你的设置',
    'memory.portrait.identity.sources.chat': '对话记忆',
    'memory.portrait.identity.saveSuccess': '已保存',
    'memory.portrait.identity.saveFailed': '保存失败：{{message}}',
    'memory.portrait.identity.loadFailed': '个人资料加载失败',
    'memory.portrait.identity.retry': '重试',
    'memory.portrait.identity.refresh': '从记忆刷新建议',
    'memory.portrait.identity.refreshing': '查找中...',
    'memory.portrait.identity.refreshSuccess': '已生成记忆建议',
    'memory.portrait.identity.suggestionsTitle': '记忆建议',
    'memory.portrait.identity.suggestionsDesc': '这些来自已有记忆。',
    'memory.portrait.identity.suggestionsEmpty': '暂时没有新的建议。',
    'memory.portrait.identity.applySuggestion': '采纳',
  };
  return {
    useTranslation: () => ({
      t: (key: string, opts?: Record<string, unknown>) => {
        const label = labels[key] ?? opts?.defaultValue ?? key;
        return label.replace(/\{\{(\w+)\}\}/g, (_match, name) =>
          name in (opts ?? {}) ? String(opts?.[name]) : `{{${name}}}`
        );
      },
      i18n: { language: 'zh-CN' },
    }),
  };
});

const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('sonner', () => ({ toast: toastMock }));

vi.mock('@/api/modules/profile', () => ({
  profileApi: {
    getMe: vi.fn(),
    updateMe: vi.fn(),
    refreshMe: vi.fn(),
  },
}));

const buildProfile = (overrides: Record<string, unknown> = {}) => ({
  user_id: 'user-1',
  entity_id: 'entity-1',
  display_name: '明日香',
  preferred_form_of_address: '明日香',
  real_name: '',
  birth_date: '',
  birth_year: null,
  age_years: null,
  age_as_of: '',
  home_location: '上海',
  communication: {},
  identity: {},
  preferences: {},
  state: {},
  field_sources: {},
  field_conflicts: {},
  completeness_score: 0.5,
  refreshed_at: 0,
  created_at: 0,
  updated_at: 0,
  ...overrides,
});

describe('PortraitIdentitySection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(profileApi.getMe).mockResolvedValue(buildProfile());
  });

  it('saves a single field inline without touching the others', async () => {
    vi.mocked(profileApi.updateMe).mockResolvedValue(
      buildProfile({ preferred_form_of_address: 'Asuka' }),
    );

    render(<PortraitIdentitySection />);
    fireEvent.click(await screen.findByText('明日香'));

    const input = await screen.findByLabelText('称呼');
    fireEvent.change(input, { target: { value: 'Asuka' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => expect(profileApi.updateMe).toHaveBeenCalledTimes(1));
    expect(profileApi.updateMe).toHaveBeenCalledWith({ preferred_form_of_address: 'Asuka' });
    expect(toastMock.success).toHaveBeenCalledWith('已保存');
    expect(await screen.findByText('Asuka')).toBeInTheDocument();
  });

  it('cancels an edit on Escape without saving', async () => {
    render(<PortraitIdentitySection />);
    fireEvent.click(await screen.findByText('明日香'));

    const input = await screen.findByLabelText('称呼');
    fireEvent.change(input, { target: { value: '别的东西' } });
    fireEvent.keyDown(input, { key: 'Escape' });

    expect(profileApi.updateMe).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('称呼')).not.toBeInTheDocument();
    expect(screen.getByText('明日香')).toBeInTheDocument();
  });

  it('keeps the old value and reports the error when saving fails', async () => {
    vi.mocked(profileApi.updateMe).mockRejectedValue(new Error('network down'));

    render(<PortraitIdentitySection />);
    fireEvent.click(await screen.findByText('明日香'));

    const input = await screen.findByLabelText('称呼');
    fireEvent.change(input, { target: { value: 'Asuka' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('保存失败：network down'));
    expect(screen.getByText('明日香')).toBeInTheDocument();
  });

  it('splits disallowed forms of address on commas when saving', async () => {
    vi.mocked(profileApi.updateMe).mockResolvedValue(buildProfile());

    render(<PortraitIdentitySection />);
    const row = await screen.findByTestId('portrait-identity-field-disallowed_forms_of_address');
    fireEvent.click(within(row).getByText('未填写'));

    const input = await screen.findByLabelText('不希望使用的称呼');
    fireEvent.change(input, { target: { value: '香香, 小香' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => expect(profileApi.updateMe).toHaveBeenCalledTimes(1));
    expect(profileApi.updateMe).toHaveBeenCalledWith({
      disallowed_forms_of_address: ['香香', '小香'],
    });
  });

  it('shows a retry action when the profile fails to load', async () => {
    vi.mocked(profileApi.getMe)
      .mockRejectedValueOnce(new Error('down'))
      .mockResolvedValueOnce(buildProfile());

    render(<PortraitIdentitySection />);
    expect(await screen.findByText('个人资料加载失败')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('明日香')).toBeInTheDocument();
    expect(profileApi.getMe).toHaveBeenCalledTimes(2);
  });

  it('offers memory suggestions and applies one via a single-field save', async () => {
    vi.mocked(profileApi.refreshMe).mockResolvedValue(
      buildProfile({ real_name: '小室哲哉' }),
    );
    vi.mocked(profileApi.updateMe).mockResolvedValue(
      buildProfile({ real_name: '小室哲哉' }),
    );

    render(<PortraitIdentitySection />);
    fireEvent.click(await screen.findByRole('button', { name: '从记忆刷新建议' }));

    expect(await screen.findByText('记忆建议')).toBeInTheDocument();
    expect(await screen.findByText('小室哲哉')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '采纳' }));
    await waitFor(() =>
      expect(profileApi.updateMe).toHaveBeenCalledWith({ real_name: '小室哲哉' }),
    );
    expect(toastMock.success).toHaveBeenCalledWith('已保存');
  });
});
