import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createInstance } from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import en from '@/i18n/locales/en/app.json';
import zh from '@/i18n/locales/zh-CN/app.json';
import enOnboarding from '@/i18n/locales/en/onboarding.json';
import zhOnboarding from '@/i18n/locales/zh-CN/onboarding.json';
import { pluginsApi, type PluginInstallPlan } from '@/api/modules/plugins';
import { PluginRegistryPlanReview } from '@/components/plugins/PluginRegistryPlanReview';
import { closurePlan, planFor } from './fixtures/pluginInstallPlan';

async function setup(language = 'en') {
  const i18n = createInstance();
  await i18n.use(initReactI18next).init({ lng: language, fallbackLng: 'en', resources: { en: { app: en, onboarding: enOnboarding }, 'zh-CN': { app: zh, onboarding: zhOnboarding } }, interpolation: { escapeValue: false } });
  return i18n;
}

describe('registry plan approval', () => {
  beforeEach(() => vi.restoreAllMocks());

  it.each(['en', 'zh-CN'])('reviews all packages, versions, reasons and permissions in %s before exact approval', async language => {
    const plan = closurePlan();
    plan.changes[0].entry.capabilities.push(
      { capability: 'memory_search', scope: ['current_user'], optional: true, reason: 'Recall evidence.', reason_i18n: {} },
      { capability: 'interaction_ask', scope: ['current_session'], optional: true, reason: 'Ask the user.', reason_i18n: {} },
    );
    vi.spyOn(pluginsApi, 'getInstallPlan').mockResolvedValue(plan);
    const confirm = vi.fn();
    const i18n = await setup(language);
    const user = userEvent.setup();
    render(<I18nextProvider i18n={i18n}><PluginRegistryPlanReview pluginId={plan.target_id} update onConfirm={confirm} onCancel={vi.fn()} /></I18nextProvider>);
    expect((await screen.findAllByText('api.example.test'))[0]).toBeVisible();
    for (const change of plan.changes) {
      const section = screen.getByRole('region', { name: change.entry.name });
      expect(section).toHaveTextContent(change.entry.plugin_id);
      expect(section).toHaveTextContent('1.0.0 → 2.0.0');
      expect(within(section).getByText(i18n.t('settings.marketplace.plan.permissions', { ns: 'app' }))).toBeInTheDocument();
    }
    expect(screen.getByText(i18n.t('settings.marketplace.plan.reason.consumer', { ns: 'app', name: 'Shared library' }))).toBeInTheDocument();
    expect(screen.getAllByText(i18n.t('settings.marketplace.capability.memory_search.scope', { ns: 'app' }))[0]).toBeVisible();
    expect(screen.getAllByText(i18n.t('settings.marketplace.capability.interaction_ask.scope', { ns: 'app' }))[0]).toBeVisible();
    expect(screen.queryByText('current_user')).not.toBeInTheDocument();
    expect(screen.queryByText('current_session')).not.toBeInTheDocument();
    expect(screen.getByText(i18n.t('settings.marketplace.plan.details', { ns: 'app' })).closest('details')).toHaveAttribute('open');
    expect(confirm).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: i18n.t('settings.marketplace.plan.confirmUpdate', { ns: 'app' }) }));
    expect(confirm).toHaveBeenCalledExactlyOnceWith(plan);
    expect(document.body.textContent).not.toMatch(/settings\.marketplace\.plan\./);
  });

  it.each(['en', 'zh-CN'])('keeps first-install purposes visible and technical details expandable in %s', async language => {
    const plan = planFor('browser');
    const target = plan.changes[0];
    target.entry.name = 'Browser';
    target.entry.icon_data = 'data:image/svg+xml;base64,PHN2Zy8+';
    target.entry.execution_mode = 'trusted_process';
    target.entry.capabilities = [{ capability: 'filesystem_read', scope: ['/browser/history'], optional: false, reason: 'Read browsing history', reason_i18n: { 'zh-CN': '读取浏览记录' } }];
    const dependency = closurePlan().changes[0];
    dependency.action = 'reuse';
    dependency.reason = 'dependency of browser';
    dependency.entry.capabilities = [{ capability: 'network', scope: ['api.example.test'], optional: true, reason: 'Fetch place names', reason_i18n: { 'zh-CN': '下载地名数据' } }];
    plan.changes = [dependency, target];
    vi.spyOn(pluginsApi, 'getInstallPlan').mockResolvedValue(plan);
    const confirm = vi.fn();
    const i18n = await setup(language);
    const user = userEvent.setup();
    render(<I18nextProvider i18n={i18n}><PluginRegistryPlanReview pluginId="browser" update={false} connectionName="Browser" onConfirm={confirm} onCancel={vi.fn()} /></I18nextProvider>);
    const path = await screen.findByText('/browser/history');
    expect(path).not.toBeVisible();
    expect(screen.getByRole('heading', { name: i18n.t('pluginInstallPanel.installTitle', { ns: 'onboarding', name: 'Browser' }) })).toBeVisible();
    expect(screen.getByTestId('plugin-icon-asset')).toHaveAttribute('src', target.entry.icon_data);
    expect(screen.getAllByText(language === 'en' ? 'Read browsing history' : '读取浏览记录')[0]).toBeVisible();
    expect(screen.getAllByText('api.example.test')[0]).toBeVisible();
    expect(screen.getByText(i18n.t('settings.marketplace.plan.nativeAccess', { ns: 'app' }))).toBeVisible();
    const details = screen.getByText(i18n.t('settings.marketplace.plan.details', { ns: 'app' }));
    await user.click(details);
    expect(path).toBeVisible();
    const regions = within(details.closest('details')!).getAllByRole('region');
    expect(regions.map(region => region.getAttribute('aria-label'))).toEqual(['Browser', 'Shared library']);
    expect(within(regions[1]).getByText(i18n.t('settings.marketplace.plan.action.reuse', { ns: 'app' }))).toBeVisible();
    expect(regions[0]).toHaveTextContent(i18n.t('settings.marketplace.plan.trustedMode', { ns: 'app' }));
    expect(regions[1]).toHaveTextContent(i18n.t('settings.marketplace.plan.restrictedMode', { ns: 'app' }));
    await user.click(screen.getByRole('button', { name: i18n.t('pluginInstallPanel.installContinue', { ns: 'onboarding' }) }));
    expect(confirm).toHaveBeenCalledExactlyOnceWith(plan);
    expect(confirm.mock.calls[0][0].changes[0]).toBe(dependency);
    expect(document.body.textContent).not.toMatch(/settings\.marketplace\.|pluginInstallPanel\./);
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
