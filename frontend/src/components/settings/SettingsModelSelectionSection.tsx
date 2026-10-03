import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

const MODEL_SECTIONS = ['llmModels', 'asr', 'tts'] as const;
type ModelSection = typeof MODEL_SECTIONS[number];

export function isModelSelectionSection(section: string): section is ModelSection {
  return section === 'llmModels' || section === 'asr' || section === 'tts';
}

export function SettingsModelSelectionSection({ section, onSectionChange, onConfigureConnections, children }: {
  section: ModelSection;
  onSectionChange: (section: ModelSection) => void;
  onConfigureConnections: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation('app');
  return <div className="space-y-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{t('settings.modelSetup.selectionDescription')}</p>
      {section === 'llmModels' && <Button variant="outline" size="sm" onClick={onConfigureConnections}>{t('settings.modelSetup.openConnections')}</Button>}
    </div>
    <Tabs value={section} onValueChange={(value) => { if (isModelSelectionSection(value)) onSectionChange(value); }}>
      <TabsList aria-label={t('settings.modelSetup.categoriesLabel')} className="h-auto w-full flex-wrap justify-start gap-1 rounded-none bg-transparent p-0">
        {MODEL_SECTIONS.map((value) => <TabsTrigger key={value} value={value}
          className="rounded-none border-b-2 border-transparent px-3 py-2.5 data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
          {t(`settings.modelSetup.categories.${value}`)}
        </TabsTrigger>)}
      </TabsList>
      {MODEL_SECTIONS.map((value) => <TabsContent key={value} value={value} className="mt-5">
        {section === value ? children : null}
      </TabsContent>)}
    </Tabs>
  </div>;
}
