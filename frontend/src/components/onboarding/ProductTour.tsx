import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { configApi, type SystemConfig } from '@/api/modules/config';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { EmptyStateAvailableSensors } from '@/components/empty-state/EmptyStateAvailableSensors';
import { cn } from '@/lib/utils';
import { useChatShellStore } from '@/stores/chat-shell';
import { usePluginInstallPanelStore } from '@/stores/pluginInstallPanel';

export interface ProductTourProps {
  /** Called when the first-run setup prompt is completed or skipped. */
  onComplete: () => void;
}

type ProductTourStage = 'checking' | 'memory-model' | 'first-context';

function hasUsableMemoryModel(config: SystemConfig | null): boolean {
  if (!config) {
    return true;
  }

  const embeddingMode = config.memory?.embedding?.mode;
  if (embeddingMode === 'local') {
    const local = config.memory?.embedding?.local;
    return Boolean(local?.managed_model_id || local?.model_dir_path);
  }

  if (embeddingMode === 'remote') {
    const selection = config.llm?.selections?.embedding;
    return Boolean(selection?.provider_id && selection.model);
  }

  return false;
}

export function ProductTour({ onComplete }: ProductTourProps): JSX.Element {
  const { t } = useTranslation('app');
  const [open, setOpen] = useState(true);
  const [stage, setStage] = useState<ProductTourStage>('checking');
  const pluginPanelOpen = usePluginInstallPanelStore((s) => s.open);
  const activePanel = useChatShellStore((s) => s.activePanel);
  const setActivePanel = useChatShellStore((s) => s.setActivePanel);
  const setSettingsNavigationIntent = useChatShellStore((s) => s.setSettingsNavigationIntent);
  const doneRef = useRef(false);
  const awaitingPluginRef = useRef(false);
  const awaitingSettingsRef = useRef(false);

  const finish = useCallback(() => {
    if (doneRef.current) {
      return;
    }
    doneRef.current = true;
    awaitingPluginRef.current = false;
    setOpen(false);
    onComplete();
  }, [onComplete]);

  useEffect(() => {
    if (!pluginPanelOpen && awaitingPluginRef.current && !doneRef.current) {
      awaitingPluginRef.current = false;
      setStage('first-context');
      setOpen(true);
    }
  }, [pluginPanelOpen]);

  useEffect(() => {
    let cancelled = false;
    const loadMemoryModelStatus = async () => {
      try {
        const response = await configApi.get();
        if (cancelled) {
          return;
        }
        setStage(hasUsableMemoryModel(response.data || null) ? 'first-context' : 'memory-model');
      } catch {
        if (!cancelled) {
          setStage('first-context');
        }
      }
    };

    void loadMemoryModelStatus();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (activePanel !== 'settings' && awaitingSettingsRef.current && !doneRef.current) {
      awaitingSettingsRef.current = false;
      setStage('first-context');
      setOpen(true);
    }
  }, [activePanel]);

  const preventDismiss = (event: Event) => {
    event.preventDefault();
  };

  const openMemoryModelSettings = () => {
    awaitingSettingsRef.current = true;
    setOpen(false);
    setStage('first-context');
    setSettingsNavigationIntent({ section: 'llmModels' });
    setActivePanel('settings');
  };

  if (stage === 'checking') {
    return <></>;
  }

  const showMemoryModelPrompt = stage === 'memory-model';

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        className={cn('overflow-hidden p-0', showMemoryModelPrompt ? 'max-w-[36rem]' : 'max-w-[44rem]')}
        hideClose
        onEscapeKeyDown={preventDismiss}
        onInteractOutside={preventDismiss}
        onPointerDownOutside={preventDismiss}
      >
        <DialogHeader
          className={cn(
            'px-7',
            showMemoryModelPrompt
              ? 'pb-2 pt-7'
              : 'border-b border-border/55 bg-muted/25 py-6'
          )}
        >
          {showMemoryModelPrompt ? null : (
            <div className="mb-3 w-fit rounded-full border border-primary/20 bg-background px-3 py-1 text-xs font-medium text-primary">
              {t('productTour.firstContextKicker')}
            </div>
          )}
          <DialogTitle className="max-w-xl text-xl font-semibold leading-7">
            {showMemoryModelPrompt
              ? t('productTour.memoryModelTitle')
              : t('productTour.firstContextTitle')}
          </DialogTitle>
          <DialogDescription className="max-w-xl text-sm leading-6">
            {showMemoryModelPrompt
              ? t('productTour.memoryModelBody')
              : t('productTour.firstContextBody')}
          </DialogDescription>
        </DialogHeader>

        {showMemoryModelPrompt ? (
          <div className="px-7 pb-6 pt-2">
            <p className="max-w-xl text-sm leading-6 text-muted-foreground">
              {t('productTour.memoryModelImpact')}
            </p>
          </div>
        ) : (
          <div className="px-7 py-5">
            <EmptyStateAvailableSensors
              showBrowseAll={false}
              fallbackPluginIds={['chrome-history', 'git-activity']}
              onConnectStart={() => {
                awaitingPluginRef.current = true;
                setOpen(false);
              }}
              onConnectDone={finish}
            />
            <p className="mt-4 text-xs leading-5 text-muted-foreground">
              {t('productTour.firstContextNote')}
            </p>
          </div>
        )}

        <DialogFooter className="justify-end border-border/55 bg-background px-7 py-4">
          {showMemoryModelPrompt ? (
            <>
              <Button
                variant="ghost"
                onClick={() => {
                  setStage('first-context');
                }}
              >
                {t('productTour.memoryModelSkip')}
              </Button>
              <Button onClick={openMemoryModelSettings}>
                {t('productTour.memoryModelConfigure')}
              </Button>
            </>
          ) : (
            <Button onClick={finish}>
              {t('productTour.connectLater')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default ProductTour;
