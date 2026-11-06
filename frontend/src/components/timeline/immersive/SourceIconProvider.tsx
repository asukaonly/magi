import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { sourcesApi } from '@/api/modules/sources';

const SourceIcons = createContext<Record<string, string>>({});

export function SourceIconProvider({ children }: { children: ReactNode }) {
  const [icons, setIcons] = useState<Record<string, string>>({});
  useEffect(() => {
    let active = true;
    void sourcesApi.getStatus().then(({ sources }) => {
      if (!active) return;
      setIcons(Object.fromEntries(sources.filter(source => source.icon).map(source => [
        source.source_name.toLowerCase().replace(/-/g, '_'), source.icon || '',
      ])));
    }).catch(() => { /* Artwork is optional; semantic icons remain available. */ });
    return () => { active = false; };
  }, []);
  return <SourceIcons.Provider value={icons}>{children}</SourceIcons.Provider>;
}

export function useSourceIcon(sourceType: string): string | undefined {
  return useContext(SourceIcons)[sourceType.toLowerCase().replace(/-/g, '_')];
}
