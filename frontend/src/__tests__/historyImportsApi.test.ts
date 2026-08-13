import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/api/client';
import { historyImportsApi } from '@/api/modules/historyImports';

describe('historyImportsApi contract', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('discovers plugin importers through the stable collection route', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue([] as any);

    await historyImportsApi.listImporters();

    expect(getSpy).toHaveBeenCalledWith('/memory/history-imports/importers');
  });

  it('previews an export through its plugin and importer identifiers', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({} as any);

    await historyImportsApi.previewWithImporter({
      pluginId: 'platform-history',
      importerId: 'account-export',
      paths: ['/tmp/export.zip'],
    });

    expect(postSpy).toHaveBeenCalledWith(
      '/memory/history-imports/importers/platform-history/account-export/preview',
      { paths: ['/tmp/export.zip'] },
      { timeout: 75_000 },
    );
  });

  it('uses source and participant ids for review and confirmation', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({} as any);
    const patchSpy = vi.spyOn(api, 'patch').mockResolvedValue({} as any);
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({} as any);

    await historyImportsApi.getSourcePreview('him-1', 'conversation:stable-id');
    await historyImportsApi.updateSelection('him-1', ['conversation:stable-id']);
    await historyImportsApi.confirm('him-1', {
      confirmPersonalWriting: false,
      includedSourceIds: ['conversation:stable-id'],
      selfParticipantIds: ['participant:me'],
    });

    expect(getSpy).toHaveBeenCalledWith(
      '/memory/history-imports/him-1/source-preview',
      { params: { source_id: 'conversation:stable-id' } },
    );
    expect(patchSpy).toHaveBeenCalledWith(
      '/memory/history-imports/him-1/selection',
      { included_source_ids: ['conversation:stable-id'] },
    );
    expect(postSpy).toHaveBeenCalledWith(
      '/memory/history-imports/him-1/confirm',
      {
        confirm_personal_writing: false,
        included_source_ids: ['conversation:stable-id'],
        self_participant_ids: ['participant:me'],
      },
    );
  });
});
