import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Save, Sparkles } from 'lucide-react';
import { toast } from 'sonner';

import { profileApi, type UserProfilePatch, type UserProfileProjection } from '@/api/modules/profile';
import { SettingsGroup, SettingsSectionShell } from '@/components/settings/SettingsSectionPrimitives';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';

interface ProfileDraft {
  realName: string;
  birthDate: string;
  preferredFormOfAddress: string;
  disallowedFormsOfAddress: string;
  homeLocation: string;
}

type ProfileFieldKey = keyof ProfileDraft;

const suggestionFields: Array<{ key: ProfileFieldKey; labelKey: string }> = [
  { key: 'realName', labelKey: 'settings.personalProfile.fields.realName' },
  { key: 'birthDate', labelKey: 'settings.personalProfile.fields.birthDate' },
  { key: 'homeLocation', labelKey: 'settings.personalProfile.fields.homeLocation' },
  { key: 'preferredFormOfAddress', labelKey: 'settings.personalProfile.fields.preferredFormOfAddress' },
  { key: 'disallowedFormsOfAddress', labelKey: 'settings.personalProfile.fields.disallowedFormsOfAddress' },
];

const emptyDraft: ProfileDraft = {
  realName: '',
  birthDate: '',
  preferredFormOfAddress: '',
  disallowedFormsOfAddress: '',
  homeLocation: '',
};

function toDraft(profile: UserProfileProjection | null): ProfileDraft {
  if (!profile) {
    return emptyDraft;
  }
  const disallowed = profile.communication.disallowed_forms_of_address;
  return {
    realName: profile.real_name || '',
    birthDate: profile.birth_date || '',
    preferredFormOfAddress: profile.preferred_form_of_address || '',
    disallowedFormsOfAddress: Array.isArray(disallowed) ? disallowed.join(', ') : '',
    homeLocation: profile.home_location || '',
  };
}

function toPatch(draft: ProfileDraft): UserProfilePatch {
  return {
    real_name: draft.realName.trim(),
    birth_date: draft.birthDate.trim(),
    preferred_form_of_address: draft.preferredFormOfAddress.trim(),
    disallowed_forms_of_address: draft.disallowedFormsOfAddress
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
    home_location: draft.homeLocation.trim(),
  };
}

function FieldSource({ profile, fieldKey }: { profile: UserProfileProjection | null; fieldKey: string }) {
  const { t } = useTranslation('app');
  const source = profile?.field_sources?.[fieldKey];
  if (!source || typeof source !== 'object') {
    return null;
  }
  const record = source as Record<string, unknown>;
  const sourceLabel = String(record.source || '');
  if (!sourceLabel) {
    return null;
  }
  return (
    <span className="text-[11px] leading-5 text-muted-foreground">
      {t('settings.personalProfile.source', { source: t(`settings.personalProfile.sources.${sourceLabel}`, { defaultValue: sourceLabel }) })}
    </span>
  );
}

function TextField({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  children?: ReactNode;
}) {
  return (
    <label className="space-y-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <Input
        type={type}
        value={value}
        placeholder={placeholder}
        aria-label={label}
        onChange={(event) => onChange(event.target.value)}
      />
      {children}
    </label>
  );
}

export function SettingsPersonalProfileSection() {
  const { t } = useTranslation('app');
  const [profile, setProfile] = useState<UserProfileProjection | null>(null);
  const [draft, setDraft] = useState<ProfileDraft>(emptyDraft);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [memorySuggestion, setMemorySuggestion] = useState<ProfileDraft | null>(null);

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(toDraft(profile)), [draft, profile]);
  const suggestionItems = useMemo(() => {
    if (!memorySuggestion) {
      return [];
    }
    return suggestionFields
      .map((field) => ({
        ...field,
        label: t(field.labelKey),
        value: memorySuggestion[field.key].trim(),
      }))
      .filter((item) => item.value && item.value !== draft[item.key].trim());
  }, [draft, memorySuggestion, t]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    profileApi.getMe()
      .then((nextProfile) => {
        if (cancelled) return;
        setProfile(nextProfile);
        setDraft(toDraft(nextProfile));
        setMemorySuggestion(null);
      })
      .catch((error) => {
        if (!cancelled) {
          toast.error(t('settings.personalProfile.loadFailed', { message: error?.message || String(error) }));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const patchDraft = (patch: Partial<ProfileDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const nextProfile = await profileApi.updateMe(toPatch(draft));
      setProfile(nextProfile);
      setDraft(toDraft(nextProfile));
      setMemorySuggestion(null);
      toast.success(t('settings.personalProfile.saveSuccess'));
    } catch (error: any) {
      toast.error(t('settings.personalProfile.saveFailed', { message: error?.message || String(error) }));
    } finally {
      setSaving(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const nextProfile = await profileApi.refreshMe();
      setMemorySuggestion(toDraft(nextProfile));
      toast.success(t('settings.personalProfile.refreshSuccess'));
    } catch (error: any) {
      toast.error(t('settings.personalProfile.loadFailed', { message: error?.message || String(error) }));
    } finally {
      setRefreshing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <LoadingSpinner />
        <span>{t('settings.personalProfile.loading')}</span>
      </div>
    );
  }

  return (
    <SettingsSectionShell>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
        <div className="space-y-1">
          <p className="text-sm text-muted-foreground">{t('settings.personalProfile.description')}</p>
          {profile?.age_years !== null && profile?.age_years !== undefined ? (
            <p className="text-xs text-muted-foreground">
              {t('settings.personalProfile.derivedAge', { age: profile.age_years, date: profile.age_as_of })}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center justify-start gap-2 sm:justify-end">
          <Button type="button" variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing || saving}>
            <Sparkles className="mr-1.5 h-4 w-4" />
            {refreshing ? t('settings.personalProfile.refreshing') : t('settings.personalProfile.refresh')}
          </Button>
          <Button type="button" size="sm" onClick={handleSave} disabled={!dirty || saving || refreshing}>
            <Save className="mr-1.5 h-4 w-4" />
            {saving ? t('settings.saving') : t('settings.personalProfile.save')}
          </Button>
        </div>
      </div>

      {memorySuggestion ? (
        <section className="rounded-lg border border-border/70 bg-muted/20 px-4 py-3">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-foreground">{t('settings.personalProfile.suggestionsTitle')}</h3>
              <p className="max-w-3xl text-xs leading-6 text-muted-foreground">
                {t('settings.personalProfile.suggestionsDesc')}
              </p>
            </div>
            <span className="text-xs text-muted-foreground">
              {t('settings.personalProfile.suggestionsCount', { count: suggestionItems.length })}
            </span>
          </div>
          {suggestionItems.length > 0 ? (
            <div className="mt-3 divide-y divide-border/60">
              {suggestionItems.map((item) => (
                <div key={item.key} className="grid gap-2 py-2 sm:grid-cols-[140px_minmax(0,1fr)_auto] sm:items-center">
                  <div className="text-xs text-muted-foreground">{item.label}</div>
                  <div className="min-w-0 text-sm text-foreground">{item.value}</div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => patchDraft({ [item.key]: item.value })}
                  >
                    {t('settings.personalProfile.applySuggestion')}
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">{t('settings.personalProfile.suggestionsEmpty')}</p>
          )}
        </section>
      ) : null}

      <SettingsGroup title={t('settings.personalProfile.identityTitle')} description={t('settings.personalProfile.identityDesc')}>
        <div className="grid gap-4 md:grid-cols-2">
          <TextField label={t('settings.personalProfile.fields.realName')} value={draft.realName} onChange={(value) => patchDraft({ realName: value })}>
            <FieldSource profile={profile} fieldKey="real_name" />
          </TextField>
          <TextField label={t('settings.personalProfile.fields.birthDate')} type="date" value={draft.birthDate} onChange={(value) => patchDraft({ birthDate: value })}>
            <FieldSource profile={profile} fieldKey="birth_date" />
          </TextField>
          <TextField label={t('settings.personalProfile.fields.homeLocation')} value={draft.homeLocation} placeholder={t('settings.personalProfile.placeholders.homeLocation')} onChange={(value) => patchDraft({ homeLocation: value })}>
            <FieldSource profile={profile} fieldKey="home_location" />
          </TextField>
        </div>
      </SettingsGroup>

      <SettingsGroup title={t('settings.personalProfile.communicationTitle')} description={t('settings.personalProfile.communicationDesc')}>
        <div className="grid gap-4 md:grid-cols-2">
          <TextField label={t('settings.personalProfile.fields.preferredFormOfAddress')} value={draft.preferredFormOfAddress} onChange={(value) => patchDraft({ preferredFormOfAddress: value })}>
            <FieldSource profile={profile} fieldKey="preferred_form_of_address" />
          </TextField>
          <TextField label={t('settings.personalProfile.fields.disallowedFormsOfAddress')} value={draft.disallowedFormsOfAddress} placeholder={t('settings.personalProfile.placeholders.disallowedForms')} onChange={(value) => patchDraft({ disallowedFormsOfAddress: value })}>
            <FieldSource profile={profile} fieldKey="disallowed_forms_of_address" />
          </TextField>
        </div>
      </SettingsGroup>
    </SettingsSectionShell>
  );
}
