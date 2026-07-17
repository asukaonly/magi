import { Loader2, TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Switch } from '@/components/ui/switch';
import type { GovernanceLabelFn, LayerRecord } from '../governanceModel';

export type GovernanceDestructiveAction = 'delete_event' | 'forget_entity';

export function GovernanceDestructiveActionDialog({
  action,
  record,
  open,
  loading,
  error,
  deleteRawEntityEvents,
  onDeleteRawEntityEventsChange,
  onOpenChange,
  onConfirm,
  label,
}: {
  action: GovernanceDestructiveAction | null;
  record: LayerRecord | null;
  open: boolean;
  loading: boolean;
  error: string | null;
  deleteRawEntityEvents: boolean;
  onDeleteRawEntityEventsChange: (checked: boolean) => void;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  label: GovernanceLabelFn;
}) {
  const isEntity = action === 'forget_entity';
  const isManualEntry = action === 'delete_event' && record?.sourceKind === 'manual_entry';
  const isChatEvent = action === 'delete_event' && record?.sourceKind === 'chat';
  const title = isEntity
    ? label('destructiveConfirm.entityTitle', '确认忘记这个实体？')
    : isManualEntry
      ? label('destructiveConfirm.manualEntryTitle', '删除这条手记和相关记忆？')
      : isChatEvent
        ? label('destructiveConfirm.chatEventTitle', '让 Magi 忘记这条消息形成的记忆？')
        : label('destructiveConfirm.eventTitle', '确认删除这条原始事件？');
  const description = isEntity
    ? label(
        'destructiveConfirm.entityDescription',
        '系统会移除这个实体，以及由它产生的关系、判断和摘要，并阻止旧数据把它重新建立出来。'
      )
    : isManualEntry
      ? label(
          'destructiveConfirm.manualEntryDescription',
          '这条手记会从时间线中移除，附件将无法再从 Magi 打开，由它形成的相关记忆也会一并清理。附件文件可能仍留在本机存储中，但 Magi 不会再提供访问入口。此操作无法撤销。'
        )
      : isChatEvent
        ? label(
            'destructiveConfirm.chatEventDescription',
            '由这条消息形成的相关记忆会被清理，但聊天中的原消息会保留。如需删除原消息，请在聊天中操作。'
          )
        : label(
            'destructiveConfirm.eventDescription',
            '这条历史记录会被移除，由它产生的记忆也会一并清理。此操作无法撤销。'
          );
  const confirmLabel = error
    ? label('destructiveConfirm.retry', '重试')
    : isEntity && deleteRawEntityEvents
      ? label('destructiveConfirm.confirmEntityWithHistory', '连同原始记录一起忘记')
      : isEntity
        ? label('destructiveConfirm.confirmEntity', '只忘记整理后的记忆')
        : isManualEntry
          ? label('destructiveConfirm.confirmManualEntry', '删除手记')
          : isChatEvent
            ? label('destructiveConfirm.confirmChatEvent', '只忘记相关记忆')
            : label('destructiveConfirm.confirmEvent', '确认删除');

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!loading) onOpenChange(nextOpen);
      }}
    >
      <DialogContent
        className="max-w-md overflow-hidden p-0"
        closeLabel={label('destructiveConfirm.close', '关闭')}
        hideClose={loading}
      >
        <DialogHeader className="border-b border-border/60 bg-red-50/60 px-6 pb-5 pt-6 dark:bg-red-950/20">
          <div className="flex items-start gap-3 pr-8">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300">
              <TriangleAlert className="h-4 w-4" aria-hidden="true" />
            </span>
            <div className="min-w-0 space-y-2">
              <DialogTitle className="text-base leading-6">{title}</DialogTitle>
              <DialogDescription className="break-words leading-6">
                {description}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-4 px-6 py-5">
          <div className="rounded-lg border border-border/60 bg-muted/25 px-3.5 py-3">
            <p className="text-xs text-muted-foreground">
              {label('destructiveConfirm.selectedRecord', '将处理的记录')}
            </p>
            <p className="mt-1 break-words text-sm font-medium text-foreground">
              {record?.title || label('destructiveConfirm.unknownRecord', '当前记录')}
            </p>
          </div>

          {isEntity ? (
            <div className="rounded-lg border border-border/60 px-3.5 py-3.5">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <label
                    htmlFor="delete-raw-entity-events"
                    className="cursor-pointer text-sm font-medium text-foreground"
                  >
                    {label(
                      'destructiveConfirm.deleteRawEntityEvents',
                      '连同相关原始记录一起删除'
                    )}
                  </label>
                  <p
                    id="delete-raw-entity-events-help"
                    className="mt-1.5 text-xs leading-5 text-muted-foreground"
                  >
                    {deleteRawEntityEvents
                      ? label(
                          'destructiveConfirm.deleteRawEntityEventsOn',
                          '范围更大：相关历史事件会被删除，其中同时记录的其他内容也可能受影响。'
                        )
                      : label(
                          'destructiveConfirm.deleteRawEntityEventsOff',
                          '原始历史会保留；以后直接查询历史时，仍可能看到当时记录过这个实体。'
                        )}
                  </p>
                </div>
                <Switch
                  id="delete-raw-entity-events"
                  checked={deleteRawEntityEvents}
                  onCheckedChange={onDeleteRawEntityEventsChange}
                  disabled={loading}
                  aria-describedby="delete-raw-entity-events-help"
                />
              </div>
            </div>
          ) : null}

          {error ? (
            <p
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 px-3.5 py-3 text-sm leading-5 text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300"
            >
              {error}
            </p>
          ) : null}
        </div>

        <DialogFooter className="border-border/60 bg-muted/15 px-6 py-4">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            {label('destructiveConfirm.cancel', '取消')}
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={loading}>
            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
