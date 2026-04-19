import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Check,
  Loader2,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { personasApi } from '@/api/modules/personas';
import PersonalityDetailEditor from '@/components/PersonalityDetailEditor';
import {
  usePersonality,
  getInitials,
} from '@/hooks';

interface PersonalityModernProps {
  embedded?: boolean;
}

const PersonalityModern: React.FC<PersonalityModernProps> = ({ embedded = false }) => {
  const { t } = useTranslation('app');
  const avatarInputRef = React.useRef<HTMLInputElement | null>(null);
  const [uploadingAvatar, setUploadingAvatar] = React.useState(false);
  const [avatarBroken, setAvatarBroken] = React.useState(false);

  const {
    // State
    config,
    list,
    currentId,
    selectedId,
    isNewMode,
    loading,
    saving,
    generating,
    switching,
    selectedInfo,
    switchPrompt,

    // Form state
    prompt,
    setPrompt,
    targetLanguage,
    setTargetLanguage,

    // Actions
    patch,
    selectPersonality,
    startNewPersonality,
    cancelNewPersonality,
    save,
    generate,
    switchPersonality,
    confirmSwitchPersonality,
    cancelSwitchPersonality,
    deleteConfirmOpen,
    requestDeletePersonality,
    confirmDeletePersonality,
    cancelDeletePersonality,
    reload,
  } = usePersonality();

  // Reset broken state whenever the selected persona or its avatar changes.
  // Watching the config avatar handles the race condition where the old
  // persona's broken avatar fires onError before the new config loads.
  const avatarValue = config.persona_entity.basic_profile.avatar || '';
  React.useEffect(() => {
    setAvatarBroken(false);
  }, [selectedId, avatarValue]);

  const detailTitle = isNewMode
    ? (config.persona_entity.basic_profile.name || t('personality.newPersonality'))
    : (config.persona_entity.basic_profile.name || selectedInfo?.displayName || t('personality.title'));
  const detailDescription = isNewMode
    ? t('personality.newPersonalityDesc')
    : (config.persona_entity.basic_profile.description || selectedInfo?.subtitle || t('settings.personalityDesc'));
  const avatarUrl = avatarValue && !avatarBroken ? personasApi.getAvatarUrl(avatarValue) : '';

  const handleAvatarUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploadingAvatar(true);
    try {
      const response = await personasApi.uploadAvatar(file);
      const nextAvatar = response.data?.url || response.data?.filename;
      if (!nextAvatar) {
        return;
      }

      patch((draft) => {
        draft.persona_entity.basic_profile.avatar = nextAvatar;
      });
      setAvatarBroken(false);
    } catch (error) {
      toast.error((error as Error)?.message || t('personality.avatarUploadFailed'));
    } finally {
      setUploadingAvatar(false);
      event.target.value = '';
    }
  };

  return (
    <div className={cn('flex h-full min-h-0 flex-col overflow-hidden', embedded ? 'bg-transparent' : 'bg-background')}>
      <div
        className={cn(
          'border-b border-border/40 bg-muted/20',
          embedded ? 'border-b-0 bg-transparent px-0 pb-3 pt-1' : 'px-6 py-5'
        )}
      >
      {/* Title row */}
      {!embedded ? (
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">
              {t('personality.title')}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t('settings.personalityDesc')}
            </p>
          </div>
        </div>
      ) : null}
      {/* Avatar selector row */}
      <div className="flex gap-3 overflow-x-auto pb-2">
          <button
            type="button"
            data-testid="personality-create-card"
            onClick={startNewPersonality}
            className="group relative flex shrink-0 flex-col items-center gap-2"
          >
            <div
              className={cn(
                'relative flex h-16 w-16 items-center justify-center rounded-2xl border-2 transition',
                isNewMode
                  ? 'border-primary bg-primary/10 shadow-sm'
                  : 'border-dashed border-border bg-muted/30 group-hover:border-primary group-hover:bg-primary/5'
              )}
            >
              <Plus
                className={cn(
                  'h-6 w-6 transition',
                  isNewMode ? 'text-primary' : 'text-muted-foreground group-hover:text-primary'
                )}
              />
            </div>
            <span
              className={cn(
                'text-xs font-medium transition',
                isNewMode ? 'text-foreground' : 'text-muted-foreground group-hover:text-foreground'
              )}
            >
              {t('personality.create')}
            </span>
          </button>

          {/* Personality Avatars */}
          {list.map((item) => {
            const isSelected = item.id === selectedId;
            const isCurrent = item.id === currentId;
            const initials = getInitials(item.displayName);
            const selectorAvatarValue =
              item.id === selectedId ? (avatarValue || item.avatar || '') : (item.avatar || '');
            const selectorAvatarUrl =
              selectorAvatarValue && !(item.id === selectedId && avatarBroken)
                ? personasApi.getAvatarUrl(selectorAvatarValue)
                : '';

            return (
              <button
                key={item.id}
                onClick={() => selectPersonality(item.id)}
                className="group relative flex shrink-0 flex-col items-center gap-2"
              >
                <div
                  className={cn(
                    'relative flex h-16 w-16 items-center justify-center rounded-2xl border-2 transition',
                    isSelected
                      ? 'border-primary bg-primary/10 shadow-sm'
                      : 'border-border/50 bg-muted/30 hover:border-primary/50 hover:bg-muted/50'
                  )}
                >
                  {selectorAvatarUrl ? (
                    <img
                      src={selectorAvatarUrl}
                      alt={item.displayName}
                      className="h-full w-full rounded-[14px] bg-neutral-200 object-cover dark:bg-neutral-700"
                    />
                  ) : (
                    <span
                      className={cn(
                        'text-lg font-semibold',
                        isSelected ? 'text-primary' : 'text-muted-foreground'
                      )}
                    >
                      {initials}
                    </span>
                  )}
                  {/* Current-in-use badge */}
                  {isCurrent && (
                    <div className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm">
                      <Check className="h-3 w-3" />
                    </div>
                  )}
                </div>
                <div className="max-w-[80px] truncate text-center">
                  <span
                    className={cn(
                      'block text-xs font-medium',
                      isSelected ? 'text-foreground' : 'text-muted-foreground'
                    )}
                  >
                    {item.displayName}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Detail section: Scrollable config cards */}
      <div className={cn('flex-1 overflow-y-auto', embedded ? 'pt-3' : 'p-6')}>
        <div className="space-y-5">
          {/* Detail Header with Actions */}
          <div className="flex flex-col gap-4 rounded-3xl border border-primary/20 bg-muted/20 p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 flex-1 items-start gap-4">
                <input
                  ref={avatarInputRef}
                  data-testid="personality-avatar-input"
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(event) => {
                    void handleAvatarUpload(event);
                  }}
                />
                <button
                  type="button"
                  onClick={() => avatarInputRef.current?.click()}
                  disabled={uploadingAvatar}
                  className={cn(
                    'group relative flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-3xl border border-border/60 transition hover:border-primary/50 disabled:cursor-not-allowed disabled:opacity-70',
                    avatarUrl
                      ? 'bg-neutral-200 hover:bg-neutral-300 dark:bg-neutral-700 dark:hover:bg-neutral-600'
                      : 'bg-background hover:bg-primary/5'
                  )}
                  aria-label={t('personality.actions.uploadAvatar')}
                >
                  {avatarUrl ? (
                    <img
                      src={avatarUrl}
                      alt={detailTitle}
                      className="h-full w-full object-cover"
                      onError={() => setAvatarBroken(true)}
                    />
                  ) : (
                    <div className="flex flex-col items-center gap-1 text-muted-foreground transition group-hover:text-primary">
                      <span className="text-xl font-semibold">
                        {getInitials(detailTitle)}
                      </span>
                      <span className="text-[11px] font-medium">
                        {uploadingAvatar ? t('personality.actions.uploadingAvatar') : t('personality.actions.uploadAvatar')}
                      </span>
                    </div>
                  )}
                  {!avatarUrl ? (
                    <div className="pointer-events-none absolute inset-0 rounded-3xl ring-1 ring-inset ring-border/40" />
                  ) : null}
                </button>

                <div className="min-w-0 flex-1">
                {isNewMode ? (
                  <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary/80">
                    {t('personality.creating')}
                  </p>
                ) : null}
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <h2 className="text-2xl font-semibold tracking-tight text-foreground">
                    {detailTitle}
                  </h2>
                  {!isNewMode && selectedId === currentId ? (
                    <span className="inline-flex items-center rounded-full border border-primary/25 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
                      {t('personality.current')}
                    </span>
                  ) : null}
                </div>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {detailDescription}
                </p>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-wrap gap-2">
                {!isNewMode && selectedId !== currentId && (
                  <Button onClick={switchPersonality} disabled={switching} className="rounded-2xl">
                    <Check className="mr-2 h-4 w-4" />
                    {switching ? t('personality.switching') : t('personality.switch')}
                  </Button>
                )}
                {isNewMode ? (
                  <Button
                    variant="outline"
                    onClick={cancelNewPersonality}
                    className="rounded-2xl"
                  >
                    {t('personality.cancel')}
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    onClick={reload}
                    className="rounded-2xl"
                  >
                    <RefreshCw className="mr-2 h-4 w-4" />
                    {t('personality.reload')}
                  </Button>
                )}
                <Button
                  onClick={save}
                  disabled={saving || loading}
                  className="rounded-2xl"
                >
                  <Check className="mr-2 h-4 w-4" />
                  {isNewMode
                    ? (saving ? t('personality.creating') : t('personality.create'))
                    : (saving ? t('personality.saving') : t('personality.save'))}
                </Button>
                {!isNewMode && (
                  <Button
                    variant="outline"
                    onClick={requestDeletePersonality}
                    disabled={selectedId === currentId}
                    className="rounded-2xl border-destructive/35 text-destructive hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    {t('personality.delete')}
                  </Button>
                )}
              </div>
            </div>

            {/* AI Generate Section */}
            {isNewMode ? (
              <div className="w-full max-w-2xl space-y-3 border-t border-border/30 pt-4">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <Sparkles className="h-4 w-4 text-primary" />
                  {t('personality.generate')}
                </div>
                <div className="flex flex-col gap-2 xl:flex-row">
                  <Input
                    value={prompt}
                    onChange={(event) => setPrompt(event.target.value)}
                    placeholder={t('personality.generatePlaceholder')}
                    className="h-11 rounded-2xl"
                  />
                  <select
                    className="h-11 rounded-2xl border border-input bg-background px-4 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
                    value={targetLanguage}
                    onChange={(event) => setTargetLanguage(event.target.value)}
                  >
                    <option value="Auto">{t('personality.languages.auto')}</option>
                    <option value="Chinese">{t('personality.languages.chinese')}</option>
                    <option value="English">{t('personality.languages.english')}</option>
                    <option value="Japanese">{t('personality.languages.japanese')}</option>
                  </select>
                  <Button onClick={generate} disabled={generating} className="h-11 rounded-2xl px-5">
                    <Sparkles className="mr-2 h-4 w-4" />
                    {t('personality.generate')}
                  </Button>
                </div>
              </div>
            ) : null}
          </div>

          {/* Configuration Cards */}
          {loading ? (
            <div className="flex min-h-[360px] items-center justify-center rounded-3xl border border-border/50 bg-muted/30">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : (
            <div className="rounded-xl border border-border bg-background p-2.5">
              <PersonalityDetailEditor
                config={config}
                patch={patch}
                t={t}
              />
            </div>
          )}
        </div>
      </div>

      <Dialog
        open={Boolean(switchPrompt)}
        onOpenChange={(open) => {
          if (!open && !switching) {
            cancelSwitchPersonality();
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('personality.switchPromptTitle')}</DialogTitle>
            <DialogDescription>
              {switchPrompt
                ? t('personality.switchConfirm', {
                    from: switchPrompt.fromName,
                    to: switchPrompt.toName,
                  })
                : ''}
            </DialogDescription>
          </DialogHeader>
          <div className="px-6 pb-2">
            <div className="rounded-2xl border border-primary/20 bg-primary/6 px-4 py-4 text-sm leading-7 text-foreground">
              {switchPrompt?.phrase}
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={cancelSwitchPersonality}
              disabled={switching}
            >
              {t('personality.cancel')}
            </Button>
            <Button
              type="button"
              onClick={() => {
                void confirmSwitchPersonality();
              }}
              disabled={switching}
            >
              {switching ? t('personality.switching') : t('personality.confirmSwitch')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteConfirmOpen} onOpenChange={(open) => { if (!open) cancelDeletePersonality(); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('personality.deleteTitle')}</DialogTitle>
            <DialogDescription>
              {t('personality.deleteConfirm', { name: selectedInfo?.displayName || '' })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={cancelDeletePersonality}>
              {t('personality.cancel')}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => { void confirmDeletePersonality(); }}
            >
              {t('personality.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default PersonalityModern;
