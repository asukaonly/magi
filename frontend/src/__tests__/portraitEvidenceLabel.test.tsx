import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import en from '@/i18n/locales/en/app.json';
import zh from '@/i18n/locales/zh-CN/app.json';
import { PortraitEvidenceLabel, portraitItemText } from '@/components/memory/portrait/PortraitEvidenceLabel';
import type { PortraitDisplayItem } from '@/components/memory/portrait/portraitGrouping';

const item: PortraitDisplayItem = { id: 'a', text: 'stored text', source: '', sourceKey: null, assertionId: 'a', evidenceBasis: 'inferred', basisCount: 3, expression: { kind: 'behavior', value: 'jazz', horizon: 'recent' } };
describe('portrait evidence wording', () => {
  it('renders inference and source count in the selected language', async () => {
    const i18n = createInstance();
    await i18n.init({ lng: 'en', defaultNS: 'app', resources: { en: { app: en }, 'zh-CN': { app: zh } } });
    const view = render(<I18nextProvider i18n={i18n}><PortraitEvidenceLabel item={item} /></I18nextProvider>);
    expect(screen.getByText('Inferred from activity · 3 source records')).toBeInTheDocument();
    expect(portraitItemText(item, i18n.t.bind(i18n))).toContain('recent activity suggests');
    await i18n.changeLanguage('zh-CN');
    view.rerender(<I18nextProvider i18n={i18n}><PortraitEvidenceLabel item={item} /></I18nextProvider>);
    expect(screen.getByText('根据行为推测 · 3 条来源记录')).toBeInTheDocument();
    expect(portraitItemText(item, i18n.t.bind(i18n))).toContain('根据近期活动推测');
  });
});
