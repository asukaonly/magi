import React, { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Send as TelegramIcon, Eye, EyeOff } from 'lucide-react';

import type { SystemConfig } from '@/api/modules/config';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { LabeledSelectField } from '@/components/settings/form-fields';

interface ChannelsSectionProps {
  draftConfig: SystemConfig;
  patchDraftConfig: (updater: (draft: SystemConfig) => void) => void;
}

export const ChannelsSection: React.FC<ChannelsSectionProps> = ({
  draftConfig,
  patchDraftConfig,
}) => {
  const { t } = useTranslation('app');
  const [showToken, setShowToken] = useState(false);
  const tg = draftConfig.channels.telegram;

  const patchTelegram = useCallback(
    (updater: (tg: SystemConfig['channels']['telegram']) => void) => {
      patchDraftConfig((draft) => {
        updater(draft.channels.telegram);
      });
    },
    [patchDraftConfig],
  );

  const handleAllowedIdsChange = useCallback(
    (value: string) => {
      const ids = value
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      patchTelegram((cfg) => {
        cfg.allowed_user_ids = ids;
      });
    },
    [patchTelegram],
  );

  return (
    <div className="space-y-8">
      {/* Telegram */}
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/10 text-blue-500">
            <TelegramIcon className="h-5 w-5" />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-foreground">Telegram</h3>
              <Badge variant={tg.enabled ? 'default' : 'secondary'} className="text-[10px] px-1.5 py-0">
                {tg.enabled ? t('settings.channels.statusOn') : t('settings.channels.statusOff')}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">{t('settings.channels.telegramDesc')}</p>
          </div>
          <Switch
            aria-label={t('settings.channels.enableTelegram')}
            checked={tg.enabled}
            onCheckedChange={(checked) => patchTelegram((cfg) => { cfg.enabled = checked; })}
          />
        </div>

        {tg.enabled && (
          <div className="space-y-4 rounded-lg border border-border/60 bg-muted/30 p-4">
            {/* Bot Token */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                {t('settings.channels.botToken')}
              </label>
              <div className="flex gap-2">
                <Input
                  type={showToken ? 'text' : 'password'}
                  aria-label={t('settings.channels.botToken')}
                  value={tg.bot_token}
                  placeholder="123456:ABC-DEF..."
                  onChange={(e) => patchTelegram((cfg) => { cfg.bot_token = e.target.value; })}
                  className="font-mono text-xs"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => setShowToken((prev) => !prev)}
                  aria-label={showToken ? 'Hide token' : 'Show token'}
                >
                  {showToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
              </div>
              <p className="text-[11px] text-muted-foreground">
                {t('settings.channels.botTokenHint')}
              </p>
            </div>

            {/* Mode */}
            <div className="space-y-1.5">
              <LabeledSelectField
                label={t('settings.channels.mode')}
                ariaLabel={t('settings.channels.mode')}
                value={tg.mode}
                options={[
                  { label: 'Polling', value: 'polling' },
                  { label: 'Webhook', value: 'webhook' },
                ]}
                onChange={(value) => patchTelegram((cfg) => { cfg.mode = value; })}
              />
            </div>

            {/* Webhook URL (conditional) */}
            {tg.mode === 'webhook' && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  {t('settings.channels.webhookUrl')}
                </label>
                <Input
                  aria-label={t('settings.channels.webhookUrl')}
                  value={tg.webhook_url}
                  placeholder="https://your-domain.com/webhook/telegram"
                  onChange={(e) => patchTelegram((cfg) => { cfg.webhook_url = e.target.value; })}
                  className="text-xs"
                />
              </div>
            )}

            {/* Allowed User IDs */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                {t('settings.channels.allowedUserIds')}
              </label>
              <Input
                aria-label={t('settings.channels.allowedUserIds')}
                value={tg.allowed_user_ids.join(', ')}
                placeholder="123456789, 987654321"
                onChange={(e) => handleAllowedIdsChange(e.target.value)}
                className="text-xs"
              />
              <p className="text-[11px] text-muted-foreground">
                {t('settings.channels.allowedUserIdsHint')}
              </p>
            </div>

            {/* Group Trigger Keyword */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                {t('settings.channels.groupTriggerKeyword')}
              </label>
              <Input
                aria-label={t('settings.channels.groupTriggerKeyword')}
                value={tg.group_trigger_keyword}
                placeholder="magi"
                onChange={(e) => patchTelegram((cfg) => { cfg.group_trigger_keyword = e.target.value; })}
                className="text-xs"
              />
              <p className="text-[11px] text-muted-foreground">
                {t('settings.channels.groupTriggerKeywordHint')}
              </p>
            </div>

            {/* Magi User ID */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                {t('settings.channels.magiUserId')}
              </label>
              <Input
                aria-label={t('settings.channels.magiUserId')}
                value={tg.magi_user_id}
                placeholder="default"
                onChange={(e) => patchTelegram((cfg) => { cfg.magi_user_id = e.target.value; })}
                className="text-xs"
              />
            </div>

            {/* Max Message Length */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                {t('settings.channels.maxMessageLength')}
              </label>
              <Input
                type="number"
                aria-label={t('settings.channels.maxMessageLength')}
                value={tg.max_message_length}
                min={1}
                max={4096}
                onChange={(e) => {
                  const val = parseInt(e.target.value, 10);
                  if (!isNaN(val) && val >= 1 && val <= 4096) {
                    patchTelegram((cfg) => { cfg.max_message_length = val; });
                  }
                }}
                className="w-28 text-xs"
              />
            </div>
          </div>
        )}
      </section>

      {/* Placeholder for future channels */}
      <section className="space-y-2 opacity-50">
        <p className="text-xs text-muted-foreground italic">
          {t('settings.channels.moreComingSoon')}
        </p>
      </section>
    </div>
  );
};

export default ChannelsSection;
