import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Check,
  Loader2,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { ProtectedImage } from '@/components/media/ProtectedImage';
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
  const [avatarHover, setAvatarHover] = React.useState(false);

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
    generationProgress,
    generationStageKey,
    switching,
    selectedInfo,
    switchPrompt,

    // Form state
    prompt,
    setPrompt,

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
  const avatarValue = config.avatar || '';
  React.useEffect(() => {
    setAvatarBroken(false);
  }, [selectedId, avatarValue]);

  const detailTitle = isNewMode
    ? (config.name || t('personality.newPersonality'))
    : (config.name || selectedInfo?.displayName || t('personality.title'));
  const detailDescription = isNewMode
    ? t('personality.newPersonalityDesc')
    : (config.description || selectedInfo?.subtitle || t('settings.personalityDesc'));
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
        draft.avatar = nextAvatar;
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
      {/* Title row */}
      {!embedded ? (
        <div className="border-b border-border/20 px-6 py-5">
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

      <div className={cn('flex-1 overflow-y-auto', embedded ? 'px-5 py-4' : 'p-6')}>
        <div className={cn('w-full space-y-3', embedded ? 'max-w-none' : 'mx-auto max-w-[1080px]')}>
          <section className="space-y-3">
            <div className="flex gap-2 overflow-x-auto pb-1">
              <button
                type="button"
                data-testid="personality-create-card"
                onClick={startNewPersonality}
                className={cn(
                  'group flex h-[78px] w-[76px] shrink-0 flex-col items-center justify-center gap-2 rounded-lg text-xs font-medium transition',
                  isNewMode
                    ? 'bg-primary/10 text-foreground shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.22)]'
                    : 'text-muted-foreground hover:bg-background/70 hover:text-foreground'
                )}
              >
                <div
                  className={cn(
                    'flex h-10 w-10 items-center justify-center rounded-md border border-dashed transition',
                    isNewMode
                      ? 'border-primary/40 bg-background text-primary'
                      : 'border-border/60 bg-background/50 text-muted-foreground group-hover:border-primary/30 group-hover:text-primary'
                  )}
                >
                  <Plus className="h-5 w-5" />
                </div>
                <span className="w-full truncate px-1 text-center">{t('personality.create')}</span>
              </button>

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
                    type="button"
                    onClick={() => selectPersonality(item.id)}
                    className={cn(
                      'group flex h-[78px] w-[76px] shrink-0 flex-col items-center justify-center gap-2 rounded-lg text-xs font-medium transition',
                      isSelected
                        ? 'bg-primary/10 text-foreground shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.22)]'
                        : 'text-muted-foreground hover:bg-background/70 hover:text-foreground'
                    )}
                  >
                    <div
                      className={cn(
                        'relative flex h-10 w-10 items-center justify-center overflow-hidden rounded-md bg-background/70 text-sm font-semibold shadow-[inset_0_0_0_1px_hsl(var(--border)/0.35)] transition',
                        isSelected ? 'text-primary shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.28)]' : 'text-muted-foreground'
                      )}
                    >
                      {selectorAvatarUrl ? (
                        <ProtectedImage
                          src={selectorAvatarUrl}
                          alt={item.displayName}
                          eager
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <span>{initials}</span>
                      )}
                      {isCurrent ? (
                        <span className="absolute right-0.5 top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm">
                          <Check className="h-2.5 w-2.5" />
                        </span>
                      ) : null}
                    </div>
                    <span className="w-full truncate px-1 text-center">{item.displayName}</span>
                  </button>
                );
              })}
            </div>

            <div className="flex flex-col gap-4 rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.58)] px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 flex-1 items-start gap-3">
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
                  onMouseEnter={() => setAvatarHover(true)}
                  onMouseLeave={() => setAvatarHover(false)}
                  onFocus={() => setAvatarHover(true)}
                  onBlur={() => setAvatarHover(false)}
                  disabled={uploadingAvatar}
                  className={cn(
                    'relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-background/80 text-lg font-semibold text-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.24)] transition hover:bg-background hover:shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.22)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-70'
                  )}
                  aria-label={t('personality.actions.uploadAvatar')}
                >
                  {avatarUrl ? (
                    <ProtectedImage
                      src={avatarUrl}
                      alt={detailTitle}
                      eager
                      className="h-full w-full object-cover"
                      onError={() => setAvatarBroken(true)}
                      onProtectedAccessError={() => setAvatarBroken(true)}
                    />
                  ) : (
                    <span className={cn('transition', avatarHover && 'text-primary')}>
                      {uploadingAvatar ? <Loader2 className="h-5 w-5 animate-spin" /> : getInitials(detailTitle)}
                    </span>
                  )}
                  <span
                    className={cn(
                      'pointer-events-none absolute inset-0 flex items-center justify-center bg-background/70 text-foreground opacity-0 backdrop-blur-[1px] transition',
                      (avatarHover || uploadingAvatar) && 'opacity-100'
                    )}
                  >
                    {uploadingAvatar ? (
                      <Loader2 className="h-5 w-5 animate-spin" />
                    ) : (
                      <Upload className="h-5 w-5" />
                    )}
                  </span>
                </button>

                <div className="min-w-0 flex-1">
                  {isNewMode ? (
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-primary/75">
                      {t('personality.creating')}
                    </p>
                  ) : null}
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <h2 className="truncate text-2xl font-semibold tracking-tight text-foreground">
                      {detailTitle}
                    </h2>
                    {!isNewMode && selectedId === currentId ? (
                      <span className="inline-flex items-center rounded-full bg-primary/10 px-2.5 py-0.5 text-[11px] font-medium text-primary shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.18)]">
                        {t('personality.current')}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm leading-6 text-muted-foreground">
                    {detailDescription}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap justify-end gap-2">
                {!isNewMode && selectedId !== currentId && (
                  <Button
                    onClick={switchPersonality}
                    disabled={switching}
                    size="sm"
                    className="rounded-md"
                  >
                    <Check className="mr-2 h-4 w-4" />
                    {switching ? t('personality.switching') : t('personality.switch')}
                  </Button>
                )}
                {isNewMode ? (
                  <Button
                    variant="outline"
                    onClick={cancelNewPersonality}
                    size="sm"
                    className="rounded-md"
                  >
                    {t('personality.cancel')}
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    onClick={reload}
                    size="sm"
                    className="rounded-md"
                  >
                    <RefreshCw className="mr-2 h-4 w-4" />
                    {t('personality.reload')}
                  </Button>
                )}
                <Button
                  onClick={save}
                  disabled={saving || loading}
                  size="sm"
                  className="rounded-md"
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
                    size="sm"
                    className={cn(
                      'rounded-md text-destructive hover:bg-destructive/10 hover:text-destructive'
                    )}
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    {t('personality.delete')}
                  </Button>
                )}
              </div>
            </div>

            {isNewMode ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <Sparkles className="h-4 w-4 text-primary" />
                  {t('personality.generate')}
                </div>
                <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_auto]">
                  <Input
                    value={prompt}
                    onChange={(event) => setPrompt(event.target.value)}
                    placeholder={t('personality.generatePlaceholder')}
                    className="h-10 rounded-md border-0 bg-background/80 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.35)] focus-visible:ring-2 focus-visible:ring-primary/20 focus-visible:ring-offset-0"
                  />
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button onClick={generate} disabled={generating} className="h-10 rounded-md px-4">
                      {generating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
                      {t('personality.generate')}
                    </Button>
                  </div>
                </div>
                {generating ? (
                  <div className="rounded-md bg-primary/5 px-3 py-2.5 shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.12)]">
                    <div className="mb-2 flex items-center justify-between gap-3 text-xs text-muted-foreground">
                      <span className="truncate font-medium text-foreground">
                        {t(`personality.generationStages.${generationStageKey}`)}
                      </span>
                      <span className="shrink-0 tabular-nums">{generationProgress}%</span>
                    </div>
                    <div
                      className="h-2 overflow-hidden rounded-full bg-background"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={generationProgress}
                    >
                      <div
                        className="h-full rounded-full bg-primary transition-all duration-500"
                        style={{ width: `${Math.min(100, Math.max(4, generationProgress))}%` }}
                      />
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>

          {loading ? (
            <div className="flex min-h-[360px] items-center justify-center rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.42)]">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : (
            <section className="pt-1">
              <PersonalityDetailEditor
                config={config}
                patch={patch}
                t={t}
              />
            </section>
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
            <div className="rounded-2xl border border-primary/20 bg-primary/5 px-4 py-4 text-sm leading-7 text-foreground">
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
