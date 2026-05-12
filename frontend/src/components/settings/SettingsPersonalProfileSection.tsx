import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { RefreshCw, Save } from 'lucide-react';
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

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(toDraft(profile)), [draft, profile]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    profileApi.getMe()
      .then((nextProfile) => {
        if (cancelled) return;
        setProfile(nextProfile);
        setDraft(toDraft(nextProfile));
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
      setProfile(nextProfile);
      setDraft(toDraft(nextProfile));
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
            <RefreshCw className="mr-1.5 h-4 w-4" />
            {refreshing ? t('settings.personalProfile.refreshing') : t('settings.personalProfile.refresh')}
          </Button>
          <Button type="button" size="sm" onClick={handleSave} disabled={!dirty || saving || refreshing}>
            <Save className="mr-1.5 h-4 w-4" />
            {saving ? t('settings.saving') : t('settings.personalProfile.save')}
          </Button>
        </div>
      </div>

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