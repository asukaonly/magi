import { render, screen } from '@testing-library/react';
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import App from '@/App';

let observedClient: QueryClient;
vi.mock('@/router', () => ({ default: function QueryProbe() {
  observedClient = useQueryClient();
  const query = useQuery({ queryKey: ['probe'], queryFn: () => Promise.resolve('Ready') });
  return <p>{query.data}</p>;
} }));
vi.mock('@/components/ui/sonner', () => ({ AppToaster: () => null }));
vi.mock('@/components/plugins/PluginRequestRecoveryDialog', () => ({ PluginRequestRecoveryDialog: () => null }));

describe('application query boundary', () => {
  it('provides queries and discards their data when the connected app unmounts', async () => {
    const first = render(<App />);
    expect(await screen.findByText('Ready')).toBeInTheDocument();
    const previous = observedClient;
    expect(previous.getQueryData(['probe'])).toBe('Ready');
    first.unmount();
    expect(previous.getQueryCache().getAll()).toHaveLength(0);
    const second = render(<App />);
    expect(await screen.findByText('Ready')).toBeInTheDocument();
    expect(observedClient).not.toBe(previous);
    second.unmount();
  });
});
