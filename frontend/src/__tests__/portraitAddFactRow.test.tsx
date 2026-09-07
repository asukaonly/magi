import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { PortraitAddFactRow } from '@/components/memory/portrait/PortraitAddFactRow';
import { manualEntriesApi } from '@/api/modules/manualEntries';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/api/modules/manualEntries', () => ({ manualEntriesApi: { create: vi.fn() } }));
beforeEach(() => vi.clearAllMocks());

it('waits for a deliberate Enter after composition ends before creating a memory entry', async () => {
  render(<PortraitAddFactRow />);
  const input = screen.getByRole('textbox');
  fireEvent.change(input, { target: { value: '我喜欢mi' } });
  fireEvent.compositionStart(input);
  fireEvent.keyDown(input, { key: 'Enter', keyCode: 13 });
  expect(manualEntriesApi.create).not.toHaveBeenCalled();
  fireEvent.compositionEnd(input);
  fireEvent.keyDown(input, { key: 'Enter', keyCode: 229 });
  fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
  expect(manualEntriesApi.create).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: '我喜欢米饭' } });
  fireEvent.keyDown(input, { key: 'Enter', keyCode: 13 });
  await waitFor(() => expect(manualEntriesApi.create).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ body: '我喜欢米饭' })));
});
