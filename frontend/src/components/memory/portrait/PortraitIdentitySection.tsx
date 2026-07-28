import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Pencil, Plus, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { profileApi, type UserProfileProjection } from '@/api/modules/profile';
import {
  toProfileDraft,
  toProfileFieldPatch,
  type ProfileFieldKey,
} from '@/components/profile/profileDraft';
import { ProfileFieldSource } from '@/components/profile/ProfileFieldSource';
import { PortraitAddFactRow } from '@/components/memory/portrait/PortraitAddFactRow';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface IdentityFieldDef {
  key: ProfileFieldKey;
  /** snake_case key used by profile.field_sources */
  sourceKey: string;
  type?: string;
  placeholderKey?: string;
}

const IDENTITY_FIELDS: IdentityFieldDef[] = [
  { key: 'preferredFormOfAddress', sourceKey: 'preferred_form_of_address' },
  { key: 'realName', sourceKey: 'real_name' },
  { key: 'birthDate', sourceKey: 'birth_date', type: 'date' },
  { key: 'homeLocation', sourceKey: 'home_location', placeholderKey: 'homeLocation' },
  {
    key: 'disallowedFormsOfAddress',
    sourceKey: 'disallowed_forms_of_address',
    placeholderKey: 'disallowedForms',
  },
];

export const PortraitIdentitySection = ({
  onFactSubmitted,
}: {
  onFactSubmitted?: () => void;
}) => {
  const { t } = useTranslation('app');
  const [profile, setProfile] = useState<UserProfileProjection | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [editingField, setEditingField] = useState<ProfileFieldKey | null>(null);
  const [editValue, setEditValue] = useState('');
  const [savingField, setSavingField] = useState<ProfileFieldKey | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [suggestion, setSuggestion] = useState<ReturnType<typeof toProfileDraft> | null>(null);
  const [showEmptyFields, setShowEmptyFields] = useState(false);
  const loadRequestRef = useRef(0);

  const loadProfile = useCallback(async () => {
    const requestId = loadRequestRef.current + 1;
    loadRequestRef.current = requestId;
    setLoading(true);
    try {
      const nextProfile = await profileApi.getMe();
      if (requestId !== loadRequestRef.current) return;
      setProfile(nextProfile);
      setLoadFailed(false);
      setSuggestion(null);
    } catch {
      if (requestId !== loadRequestRef.current) return;
      setLoadFailed(true);
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  const draft = useMemo(() => toProfileDraft(profile), [profile]);

  const { filledFields, emptyFields } = useMemo(() => {
    const filled: IdentityFieldDef[] = [];
    const empty: IdentityFieldDef[] = [];
    for (const field of IDENTITY_FIELDS) {
      (draft[field.key].trim() ? filled : empty).push(field);
    }
    return { filledFields: filled, emptyFields: empty };
  }, [draft]);

  const suggestionItems = useMemo(() => {
    if (!suggestion) return [];
    return IDENTITY_FIELDS.map((field) => ({
      ...field,
      value: suggestion[field.key].trim(),
    })).filter((item) => item.value && item.value !== draft[item.key].trim());
  }, [draft, suggestion]);

  const startEdit = (field: IdentityFieldDef) => {
    if (savingField) return;
    setEditingField(field.key);
    setEditValue(draft[field.key]);
  };

  const cancelEdit = () => {
    setEditingField(null);
    setEditValue('');
  };

  const applyFieldValue = async (field: ProfileFieldKey, value: string) => {
    if (savingField) return;
    setSavingField(field);
    try {
      const nextProfile = await profileApi.updateMe(toProfileFieldPatch(field, value));
      setProfile(nextProfile);
      toast.success(t('memory.portrait.identity.saveSuccess'));
      setEditingField(null);
      setEditValue('');
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error(t('memory.portrait.identity.saveFailed', { message }));
      cancelEdit();
    } finally {
      setSavingField(null);
    }
  };

  const commitEdit = (field: ProfileFieldKey, value: string) => {
    // Escape cancels first; the ensuing blur must not resurrect the edit.
    if (editingField !== field) return;
    if (value.trim() === draft[field].trim()) {
      cancelEdit();
      return;
    }
    void applyFieldValue(field, value);
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const nextProfile = await profileApi.refreshMe();
      setSuggestion(toProfileDraft(nextProfile));
      toast.success(t('memory.portrait.identity.refreshSuccess'));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error(t('memory.portrait.identity.saveFailed', { message }));
    } finally {
      setRefreshing(false);
    }
  };

  const renderFieldRow = (field: IdentityFieldDef) => {
    const isEditing = editingField === field.key;
    const isSaving = savingField === field.key;
    const value = draft[field.key].trim();
    return (
      <div
        key={field.key}
        data-testid={`portrait-identity-field-${field.sourceKey}`}
        className="group grid gap-1 border-b border-[hsl(var(--memory-divider)/0.4)] py-2 last:border-b-0 sm:grid-cols-[minmax(7rem,9rem)_minmax(0,1fr)_auto] sm:items-center sm:gap-4"
      >
        <span className="text-xs text-[hsl(var(--memory-muted))]">
          {t(`memory.portrait.identity.fields.${field.key}`)}
        </span>
        {isEditing ? (
          <Input
            autoFocus
            type={field.type ?? 'text'}
            value={editValue}
            disabled={isSaving}
            aria-label={t(`memory.portrait.identity.fields.${field.key}`)}
            placeholder={
              field.placeholderKey
                ? t(`memory.portrait.identity.placeholders.${field.placeholderKey}`)
                : undefined
            }
            onChange={(event) => setEditValue(event.target.value)}
            onBlur={() => commitEdit(field.key, editValue)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                commitEdit(field.key, editValue);
              } else if (event.key === 'Escape') {
                event.preventDefault();
                cancelEdit();
              }
            }}
            className="h-8 max-w-sm text-sm"
          />
        ) : (
          <span className="flex min-w-0 flex-wrap items-baseline gap-x-3">
            <button
              type="button"
              onClick={() => startEdit(field)}
              className="min-w-0 truncate text-left text-[0.95rem] leading-7 text-[hsl(var(--memory-title))] outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.14)]"
            >
              {value || (
                <span className="text-[hsl(var(--memory-muted))]">
                  {t('memory.portrait.identity.empty')}
                </span>
              )}
            </button>
            <ProfileFieldSource profile={profile} fieldKey={field.sourceKey} />
          </span>
        )}
        {!isEditing ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => startEdit(field)}
            disabled={savingField !== null}
            aria-label={t('memory.portrait.identity.editField', {
              field: t(`memory.portrait.identity.fields.${field.key}`),
            })}
            className="min-h-9 rounded-mem-sm px-2.5 text-[hsl(var(--memory-body))] opacity-0 transition-opacity hover:bg-[hsl(var(--memory-panel-subtle)/0.72)] hover:text-[hsl(var(--memory-title))] focus-visible:opacity-100 group-hover:opacity-100 max-sm:hidden"
          >
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        ) : null}
      </div>
    );
  };

  return (
    <section data-testid="portrait-identity">
      <header className="flex items-baseline justify-between gap-4">
        <h2 className="text-[13px] font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.portrait.identity.title')}
        </h2>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => void handleRefresh()}
          disabled={refreshing || loading || loadFailed}
          className="min-h-9 rounded-mem-sm px-2.5 text-xs text-[hsl(var(--memory-muted))] hover:bg-[hsl(var(--memory-panel-subtle)/0.72)] hover:text-[hsl(var(--memory-title))]"
        >
          {refreshing ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <Sparkles className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          )}
          {refreshing
            ? t('memory.portrait.identity.refreshing')
            : t('memory.portrait.identity.refresh')}
        </Button>
      </header>

      {loading ? (
        <p role="status" className="mt-4 flex items-center gap-2 text-sm text-[hsl(var(--memory-muted))]">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          {t('memory.portrait.loading', { defaultValue: '正在读取关于你的内容…' })}
        </p>
      ) : loadFailed ? (
        <div className="mt-4 flex items-center gap-3">
          <p className="text-sm text-[hsl(var(--memory-muted))]">
            {t('memory.portrait.identity.loadFailed')}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => void loadProfile()}
            className="min-h-9 rounded-mem-sm px-2.5 text-xs text-[hsl(var(--memory-body))] hover:bg-[hsl(var(--memory-panel-subtle)/0.72)] hover:text-[hsl(var(--memory-title))]"
          >
            {t('memory.portrait.identity.retry')}
          </Button>
        </div>
      ) : (
        <div className="mt-2">
          {filledFields.map(renderFieldRow)}
          {emptyFields.length > 0 ? (
            showEmptyFields ? (
              emptyFields.map(renderFieldRow)
            ) : (
              <button
                type="button"
                data-testid="portrait-identity-show-empty"
                onClick={() => setShowEmptyFields(true)}
                className="mt-1 flex min-h-9 items-center gap-1.5 rounded-mem-sm px-1 text-xs text-[hsl(var(--memory-muted))] outline-none transition-colors hover:text-[hsl(var(--memory-title))] focus-visible:ring-2 focus-visible:ring-[hsl(var(--memory-accent)/0.14)]"
              >
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                {t('memory.portrait.identity.completeFields', {
                  fields: emptyFields
                    .map((field) => t(`memory.portrait.identity.fields.${field.key}`))
                    .join(t('memory.portrait.identity.fieldSeparator')),
                })}
              </button>
            )
          ) : null}
        </div>
      )}

      {suggestion ? (
        <div className="mt-4 rounded-mem-sm bg-[hsl(var(--memory-panel-subtle)/0.32)] px-4 py-3">
          <h3 className="text-xs font-semibold text-[hsl(var(--memory-title))]">
            {t('memory.portrait.identity.suggestionsTitle')}
          </h3>
          <p className="mt-1 text-xs leading-5 text-[hsl(var(--memory-muted))]">
            {t('memory.portrait.identity.suggestionsDesc')}
          </p>
          {suggestionItems.length > 0 ? (
            <div className="mt-2 divide-y divide-[hsl(var(--memory-divider)/0.4)]">
              {suggestionItems.map((item) => (
                <div
                  key={item.key}
                  className="grid gap-2 py-2 sm:grid-cols-[minmax(7rem,9rem)_minmax(0,1fr)_auto] sm:items-center"
                >
                  <span className="text-xs text-[hsl(var(--memory-muted))]">
                    {t(`memory.portrait.identity.fields.${item.key}`)}
                  </span>
                  <span className="min-w-0 text-sm text-[hsl(var(--memory-title))]">{item.value}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => void applyFieldValue(item.key, item.value)}
                    disabled={savingField !== null}
                    className="min-h-9 rounded-mem-sm px-2.5 text-[hsl(var(--memory-body))] hover:bg-[hsl(var(--memory-panel-subtle)/0.72)] hover:text-[hsl(var(--memory-title))]"
                  >
                    {t('memory.portrait.identity.applySuggestion')}
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-sm text-[hsl(var(--memory-muted))]">
              {t('memory.portrait.identity.suggestionsEmpty')}
            </p>
          )}
        </div>
      ) : null}

      {!loading && !loadFailed ? (
        <PortraitAddFactRow onSubmitted={onFactSubmitted} />
      ) : null}
    </section>
  );
};

export default PortraitIdentitySection;
