import { useCallback, useEffect, useRef } from 'react';

/** Own the latest request per resource within the current mounted view. */
export function useRequestOwner(scope = '') {
  const owner = useRef({ active: false, scope, requests: new Map<string, symbol>() });
  if (owner.current.scope !== scope) {
    owner.current.requests.clear();
    owner.current.scope = scope;
  }
  useEffect(() => {
    const lifetime = owner.current;
    lifetime.active = true;
    return () => { lifetime.active = false; lifetime.requests.clear(); };
  }, []);
  return useCallback((resource: string) => {
    const lifetime = owner.current;
    if (!lifetime.active || lifetime.scope !== scope) return () => false;
    const request = Symbol(resource);
    lifetime.requests.set(resource, request);
    return () => lifetime.active && lifetime.scope === scope && lifetime.requests.get(resource) === request;
  }, [scope]);
}
