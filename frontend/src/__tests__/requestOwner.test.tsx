import { StrictMode } from 'react';
import { renderHook } from '@testing-library/react';
import { expect, it } from 'vitest';
import { useRequestOwner } from '@/hooks/useRequestOwner';

it('isolates resources and invalidates old requests, departed scopes and unmounted callbacks', () => {
  const { result, rerender, unmount } = renderHook(({ scope }) => useRequestOwner(scope), { initialProps: { scope: 'A' }, wrapper: StrictMode });
  const startA = result.current;
  const first = startA('list');
  const other = startA('sidebar');
  const latest = startA('list');
  expect(first()).toBe(false);
  expect(other()).toBe(true);
  expect(latest()).toBe(true);
  rerender({ scope: 'B' });
  const current = result.current('list');
  expect(latest()).toBe(false);
  expect(startA('list')()).toBe(false);
  expect(current()).toBe(true);
  rerender({ scope: 'A' });
  expect(other()).toBe(false);
  const last = result.current('list');
  unmount();
  expect(last()).toBe(false);
  expect(result.current('list')()).toBe(false);
});
