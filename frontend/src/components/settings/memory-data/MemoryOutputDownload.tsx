import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { invoke } from '@tauri-apps/api/core';
import { z } from 'zod';
import { getRuntimeConfig, getRuntimeGeneration } from '@/runtime/config';
import { Button } from '@/components/ui/button';

export function MemoryOutputDownload({ operationId }: { operationId: string }) {
  const { t } = useTranslation('app');
  const [phase, setPhase] = useState<'ready' | 'saving' | 'failed' | 'saved'>('ready');
  const generation = useRef(0);
  useEffect(() => { setPhase('ready'); return () => { generation.current += 1; }; }, [operationId]);
  const save = async () => {
    const owner = ++generation.current;
    const connection = getRuntimeGeneration();
    const current = () => owner === generation.current && connection === getRuntimeGeneration();
    setPhase('saving');
    try {
      const response = await invoke<unknown>('download_portability_file', { operationId, profileId: getRuntimeConfig().profileId });
      const path = z.string().min(1).nullable().parse(response);
      if (current()) setPhase(path === null ? 'ready' : 'saved');
    } catch {
      if (current()) setPhase('failed');
    }
  };
  return <div className="mt-3 space-y-2">
    <Button type="button" size="sm" variant="outline" disabled={phase === 'saving'} onClick={() => { void save(); }}>
      {t(phase === 'saving' ? 'centerFiles.downloading' : 'centerFiles.download')}
    </Button>
    {phase === 'failed' && <p role="alert" className="text-xs text-destructive">{t('centerFiles.downloadFailed')}</p>}
    {phase === 'saved' && <p role="status" className="text-xs text-muted-foreground">{t('centerFiles.downloadSaved')}</p>}
  </div>;
}
