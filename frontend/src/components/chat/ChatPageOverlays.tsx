import { useTranslation } from 'react-i18next';
import { normalizeTraceSnapshot } from '@/domain/chat/state';
import { HistoryImagePreviewDialog } from './HistoryImagePreviewDialog';
import ToolchainDrawer from './ToolchainDrawer';

type HistoryImagePreview = {
  name: string;
  url: string;
};

type ChatPageOverlaysProps = {
  activeTurnId: string | null;
  drawerOpen: boolean;
  historyImagePreview: HistoryImagePreview | null;
  loadingTrace: boolean;
  onCloseHistoryImagePreview: () => void;
  onCloseTraceDrawer: () => void;
  traceSnapshots: Record<string, Parameters<typeof normalizeTraceSnapshot>[0]>;
};

export const ChatPageOverlays = ({
  activeTurnId,
  drawerOpen,
  historyImagePreview,
  loadingTrace,
  onCloseHistoryImagePreview,
  onCloseTraceDrawer,
  traceSnapshots,
}: ChatPageOverlaysProps) => {
  const { t } = useTranslation('app');

  return (
    <>
      <ToolchainDrawer
        open={drawerOpen}
        onOpenChange={(open) => !open && onCloseTraceDrawer()}
        loading={loadingTrace}
        snapshot={normalizeTraceSnapshot(traceSnapshots[activeTurnId || ''] || null)}
        title={t('chat.trace.title')}
        subtitle={t('chat.trace.subtitle')}
      />
      <HistoryImagePreviewDialog
        preview={historyImagePreview}
        onClose={onCloseHistoryImagePreview}
      />
    </>
  );
};