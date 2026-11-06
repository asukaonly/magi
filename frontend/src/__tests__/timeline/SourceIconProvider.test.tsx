import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('@/api/modules/sources', () => ({sourcesApi:{getStatus:vi.fn()}}));
import {sourcesApi} from '@/api/modules/sources';
import {SourceIconProvider} from '@/components/timeline/immersive/SourceIconProvider';
import {SourceIcon} from '@/components/timeline/immersive/SourceIcon';
const ICON = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=';
beforeEach(() => vi.resetAllMocks());
describe('timeline source artwork', () => {
  it('loads installed source artwork once for list and detail icons', async () => {
    vi.mocked(sourcesApi.getStatus).mockResolvedValue({sources:[{source_name:'codex-agent-history',icon:ICON}]} as Awaited<ReturnType<typeof sourcesApi.getStatus>>);
    render(<SourceIconProvider><SourceIcon sourceType="codex_agent_history"/><SourceIcon sourceType="codex_agent_history"/></SourceIconProvider>);
    expect(await screen.findAllByTestId('plugin-icon-asset')).toHaveLength(2);
    expect(sourcesApi.getStatus).toHaveBeenCalledTimes(1);
  });
  it('retains source-specific semantic icons when optional artwork fails', async () => {
    vi.mocked(sourcesApi.getStatus).mockRejectedValue(new Error('Unavailable'));
    const {container} = render(<SourceIconProvider><SourceIcon sourceType="chrome_history"/><SourceIcon sourceType="codex_agent_history"/></SourceIconProvider>);
    expect(container.querySelector('.lucide-globe')).toBeInTheDocument();
    expect(container.querySelector('.lucide-sparkles')).toBeInTheDocument();
    expect(screen.queryByTestId('plugin-icon-asset')).not.toBeInTheDocument();
  });
});
