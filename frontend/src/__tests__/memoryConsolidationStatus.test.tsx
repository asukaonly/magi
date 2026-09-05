import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import zh from '@/i18n/locales/zh-CN/app.json';
import { MemoryConsolidationStatus } from '@/components/memory/MemoryConsolidationStatus';
import { memoryApi, type MemoryConsolidationStatus as Status } from '@/api/modules/memory';

vi.mock('@/api/modules/memory', () => ({ memoryApi: { getConsolidationStatus: vi.fn(), requestConsolidation: vi.fn() } }));
const status = (state: Status['state'], reason_code: string): Status => ({ state, reason_code, stats: {}, pending_events: 0 });
async function setup(onCompleted = vi.fn()) {
  const i18n = createInstance();
  await i18n.init({ lng: 'zh-CN', defaultNS: 'app', resources: { 'zh-CN': { app: zh } } });
  render(<I18nextProvider i18n={i18n}><MemoryConsolidationStatus onCompleted={onCompleted} /></I18nextProvider>);
  return onCompleted;
}
beforeEach(() => { vi.resetAllMocks(); });
describe('experience consolidation status', () => {
  it('retries a failed status read and schedules one bounded request', async () => {
    vi.mocked(memoryApi.getConsolidationStatus).mockRejectedValueOnce(new Error('offline')).mockResolvedValue(status('waiting', 'not_run'));
    vi.mocked(memoryApi.requestConsolidation).mockResolvedValue({ scheduled: true });
    await setup();
    fireEvent.click(await screen.findByRole('button', { name: zh.memory.pending.retry }));
    fireEvent.click(await screen.findByRole('button', { name: zh.memory.consolidation.request }));
    expect(await screen.findByText(zh.memory.consolidation.reasons.queued)).toBeInTheDocument();
    expect(memoryApi.requestConsolidation).toHaveBeenCalledTimes(1);
  });
  it('refreshes results after an already-running job finishes', async () => {
    vi.mocked(memoryApi.getConsolidationStatus).mockResolvedValueOnce({ ...status('running', 'running'), last_run_at: 100 }).mockResolvedValue({ ...status('ready', 'ready'), last_run_at: 100 });
    const completed = await setup();
    await screen.findByText(zh.memory.consolidation.reasons.running);
    await waitFor(() => expect(completed).toHaveBeenCalledTimes(1), { timeout: 6000 });
    expect(screen.getByText(zh.memory.consolidation.reasons.ready)).toBeInTheDocument();
  }, 8000);
});
