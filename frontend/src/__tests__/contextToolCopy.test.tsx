import { act, render, screen } from '@testing-library/react';
import { createInstance } from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { expect, it, vi } from 'vitest';

import { ToolConfigCard } from '@/components/config-forms/DynamicToolConfig';
import type { ToolConfig } from '@/api/modules/tools';
import en from '@/i18n/locales/en/app.json';
import zh from '@/i18n/locales/zh-CN/app.json';
import fixtures from '../../../contracts/api/frontend-config-examples.json';

it('updates context tool copy on language change while preserving plugin-provided copy', async () => {
  const i18n = createInstance();
  await i18n.use(initReactI18next).init({
    lng: 'zh-CN', fallbackLng: 'en', defaultNS: 'app',
    resources: { en: { app: en }, 'zh-CN': { app: zh } },
  });
  const tools: ToolConfig[] = ['environment_query', 'task_query', 'current_time', 'custom-tool'].map(name => ({
    ...fixtures.tool, name, display_name: `Raw ${name}`, description: `Schema instructions ${name}`,
    config_specs: [], providers: [], configurable: false,
  }));
  render(<I18nextProvider i18n={i18n}>{tools.map(tool => (
    <ToolConfigCard key={tool.name} tool={tool} values={{}} enabled onUpdateConfig={vi.fn()} onUpdateEnabled={vi.fn()} />
  ))}</I18nextProvider>);
  expect(screen.getByText('当前环境')).toBeInTheDocument();
  expect(screen.getByText('后台任务查询')).toBeInTheDocument();
  expect(screen.getByText('当前时间')).toBeInTheDocument();
  expect(screen.queryByText('Schema instructions environment_query')).not.toBeInTheDocument();
  expect(screen.getByText('Raw custom-tool')).toBeInTheDocument();
  await act(() => i18n.changeLanguage('en'));
  expect(screen.getByText('Current environment')).toBeInTheDocument();
  expect(screen.getByText('Background task status')).toBeInTheDocument();
  expect(screen.getByText('Current time')).toBeInTheDocument();
  expect(screen.queryByText('当前环境')).not.toBeInTheDocument();
  expect(screen.getByText('Schema instructions custom-tool')).toBeInTheDocument();
});
