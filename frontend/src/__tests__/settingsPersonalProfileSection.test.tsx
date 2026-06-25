import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';

import { SettingsPersonalProfileSection } from '@/components/settings/SettingsPersonalProfileSection';
import { profileApi, type UserProfileProjection } from '@/api/modules/profile';

const { translateMock } = vi.hoisted(() => ({
  translateMock: (key: string) => {
    const translations: Record<string, string> = {
      'settings.personalProfile.loading': '正在加载个人资料...',
      'settings.personalProfile.description': '这些是你主动告诉 Magi 的信息，会优先用于称呼、上下文和画像。',
      'settings.personalProfile.identityTitle': '基本资料',
      'settings.personalProfile.identityDesc': '用于展示、上下文和画像的稳定身份字段。',
      'settings.personalProfile.communicationTitle': '称呼与沟通',
      'settings.personalProfile.communicationDesc': 'Magi 应该如何称呼你，以及基础沟通上下文。',
      'settings.personalProfile.refresh': '查看记忆建议',
      'settings.personalProfile.refreshing': '查找中...',
      'settings.personalProfile.save': '保存资料',
      'settings.personalProfile.suggestionsTitle': '记忆建议',
      'settings.personalProfile.suggestionsDesc': '这些来自已有记忆。采纳后再保存，才会成为你手动确认的资料。',
      'settings.personalProfile.applySuggestion': '采纳',
      'settings.personalProfile.fields.realName': '真实姓名',
      'settings.personalProfile.fields.birthDate': '生日',
      'settings.personalProfile.fields.homeLocation': '常住地',
      'settings.personalProfile.fields.preferredFormOfAddress': '希望如何称呼我',
      'settings.personalProfile.fields.disallowedFormsOfAddress': '不希望使用的称呼',
      'settings.personalProfile.placeholders.homeLocation': '城市或地区',
      'settings.personalProfile.placeholders.disallowedForms': '用英文逗号分隔多个称呼',
      'settings.personalProfile.saveSuccess': '个人资料已保存',
      'settings.personalProfile.refreshSuccess': '已生成记忆建议',
      'settings.saving': '保存中...',
    };
    return translations[key] ?? key;
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: translateMock,
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock('@/api/modules/profile', () => ({
  profileApi: {
    getMe: vi.fn(),
    refreshMe: vi.fn(),
    updateMe: vi.fn(),
  },
}));

function profile(overrides: Partial<UserProfileProjection>): UserProfileProjection {
  return {
    user_id: 'local_user',
    entity_id: 'user:local_user',
    display_name: '',
    preferred_form_of_address: '',
    real_name: '',
    birth_date: '',
    birth_year: null,
    age_years: null,
    age_as_of: '',
    home_location: '',
    communication: {},
    identity: {},
    preferences: {},
    state: {},
    field_sources: {},
    field_conflicts: {},
    completeness_score: 0,
    refreshed_at: 0,
    created_at: 0,
    updated_at: 0,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(profileApi.getMe).mockReset();
  vi.mocked(profileApi.refreshMe).mockReset();
  vi.mocked(profileApi.updateMe).mockReset();
});

it('shows memory suggestions without overwriting the current draft', async () => {
  vi.mocked(profileApi.getMe).mockResolvedValue(profile({
    real_name: '手动姓名',
    preferred_form_of_address: '手动称呼',
  }));
  vi.mocked(profileApi.refreshMe).mockResolvedValue(profile({
    real_name: '记忆姓名',
    preferred_form_of_address: '记忆称呼',
  }));

  render(<SettingsPersonalProfileSection />);

  const realNameInput = await screen.findByLabelText('真实姓名');
  expect(realNameInput).toHaveValue('手动姓名');

  await userEvent.click(screen.getByRole('button', { name: /查看记忆建议/ }));

  expect(await screen.findByText('记忆建议')).toBeInTheDocument();
  expect(screen.getByText('记忆姓名')).toBeInTheDocument();
  expect(realNameInput).toHaveValue('手动姓名');

  await userEvent.click(screen.getAllByRole('button', { name: '采纳' })[0]);

  await waitFor(() => {
    expect(realNameInput).toHaveValue('记忆姓名');
  });
});
