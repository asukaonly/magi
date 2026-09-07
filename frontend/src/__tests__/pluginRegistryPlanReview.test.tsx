import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createInstance } from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import en from '@/i18n/locales/en/app.json';
import zh from '@/i18n/locales/zh-CN/app.json';
import { pluginsApi, type PluginInstallPlan } from '@/api/modules/plugins';
import { PluginRegistryPlanReview } from '@/components/plugins/PluginRegistryPlanReview';
import { closurePlan, planFor } from './fixtures/pluginInstallPlan';

async function setup(language = 'en') {
  const i18n = createInstance();
  await i18n.use(initReactI18next).init({ lng: language, fallbackLng: 'en', resources: { en: { app: en }, 'zh-CN': { app: zh } }, interpolation: { escapeValue: false } });
  return i18n;
}

describe('registry plan approval', () => {
  beforeEach(() => vi.restoreAllMocks());

  it.each(['en', 'zh-CN'])('reviews all packages, versions, reasons and permissions in %s before exact approval', async language => {
    const plan = closurePlan();
    vi.spyOn(pluginsApi, 'getInstallPlan').mockResolvedValue(plan);
    const confirm = vi.fn();
    const i18n = await setup(language);
    const user = userEvent.setup();
    render(<I18nextProvider i18n={i18n}><PluginRegistryPlanReview pluginId={plan.target_id} update onConfirm={confirm} onCancel={vi.fn()} /></I18nextProvider>);
    await screen.findByText('api.example.test');
    for (const change of plan.changes) {
      const section = screen.getByRole('region', { name: change.entry.name });
      expect(section).toHaveTextContent(change.entry.plugin_id);
      expect(section).toHaveTextContent('1.0.0 → 2.0.0');
      expect(within(section).getByText(i18n.t('settings.marketplace.plan.permissions', { ns: 'app' }))).toBeInTheDocument();
    }
    expect(screen.getByText(i18n.t('settings.marketplace.plan.reason.consumer', { ns: 'app', name: 'fixture_library' }))).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: i18n.t('settings.marketplace.plan.confirm', { ns: 'app' }) }));
    expect(confirm).toHaveBeenCalledExactlyOnceWith(plan);
    expect(document.body.textContent).not.toMatch(/settings\.marketplace\.plan\./);
  });

  it('blocks approval on load failure and retries explicitly', async () => {
    vi.spyOn(pluginsApi, 'getInstallPlan').mockRejectedValueOnce(new Error('offline')).mockResolvedValue(planFor('photo-library'));
    const i18n = await setup();
    const user = userEvent.setup();
    const confirm = vi.fn();
    render(<I18nextProvider i18n={i18n}><PluginRegistryPlanReview pluginId="photo-library" update={false} onConfirm={confirm} onCancel={vi.fn()} /></I18nextProvider>);
    expect(await screen.findByRole('alert')).toHaveTextContent('offline');
    const button = screen.getByRole('button', { name: en.settings.marketplace.plan.confirm });
    expect(button).toBeDisabled();
    await user.click(screen.getByRole('button', { name: en.settings.marketplace.plan.retry }));
    await waitFor(() => expect(button).toBeEnabled());
    expect(confirm).not.toHaveBeenCalled();
  });

  it('ignores a late plan for the previous target and allows cancellation without approval', async () => {
    let resolveOld!: (plan: PluginInstallPlan) => void;
    const pending = new Promise<PluginInstallPlan>(resolve => { resolveOld = resolve; });
    vi.spyOn(pluginsApi, 'getInstallPlan').mockReturnValueOnce(pending).mockResolvedValue(planFor('new-target'));
    const i18n = await setup();
    const confirm = vi.fn();
    const cancel = vi.fn();
    const view = (id: string) => <I18nextProvider i18n={i18n}><PluginRegistryPlanReview pluginId={id} update={false} onConfirm={confirm} onCancel={cancel} /></I18nextProvider>;
    const { rerender } = render(view('old-target'));
    expect(screen.getByRole('button', { name: en.settings.marketplace.plan.confirm })).toBeDisabled();
    rerender(view('new-target'));
    await screen.findByRole('region', { name: 'new-target' });
    await act(async () => { resolveOld(planFor('old-target')); });
    expect(screen.queryByRole('region', { name: 'old-target' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: en.settings.marketplace.consent.cancel }));
    expect(cancel).toHaveBeenCalledOnce();
    expect(confirm).not.toHaveBeenCalled();
  });
});
