import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getErrorMessage } from '@/utils/error-handler';
import {
  activateConnection, forgetConnection, listConnectionProfiles, pairCenter,
  type ConnectionProfiles,
} from '@/runtime/connections';

export interface RemoteConnectionDraft {
  address: string;
  name: string;
  deviceName: string;
  token: string;
}

/** Share connection ownership between initial setup and connection management. */
export function useConnectionSetup() {
  const { t } = useTranslation('app');
  const [profiles, setProfiles] = useState<ConnectionProfiles | null>(null);
  const [draft, setDraft] = useState<RemoteConnectionDraft>({ address: '', name: '', deviceName: '', token: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const mounted = useRef(false);
  const inFlight = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    let current = true;
    void listConnectionProfiles().then((result) => {
      if (current) setProfiles(result);
    }).catch(() => {
      if (current) setError(t('connections.loadFailed'));
    });
    return () => { current = false; };
  }, [revision, t]);

  const retry = useCallback(() => {
    setError(null);
    setRevision((value) => value + 1);
  }, []);

  const run = async (action: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try { await action(); }
    catch (failure) {
      if (mounted.current) {
        const detail = getErrorMessage(failure) ?? (typeof failure === 'string' ? failure : '');
        setError(`${t('connections.failed')} ${detail}`.trim());
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  const connect = (profileId: string) => run(() => activateConnection(profileId));
  const pair = () => run(async () => {
    const profile = await pairCenter(draft.address.trim(), draft.token.trim(), draft.name.trim(), draft.deviceName.trim());
    if (!mounted.current) return;
    setDraft((value) => ({ ...value, token: '' }));
    // A paired device is saved even if activation fails; allow retrying that profile.
    setRevision((value) => value + 1);
    await activateConnection(profile.id);
  });
  const forget = (profileId: string) => run(async () => {
    await forgetConnection(profileId);
    if (mounted.current) setRevision((value) => value + 1);
  });

  return { profiles, draft, setDraft, busy, error, retry, connect, pair, forget };
}
