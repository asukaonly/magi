import { useTranslation } from 'react-i18next';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';

export const MemoryOverviewPage = () => {
  const { t } = useTranslation('app');

  return (
    <MemoryPageFrame title={t('memory.overview.title')} description={t('memory.overview.subtitle')}>
      <section className={MEMORY_EMPTY_PANEL_CLASS}>
        {t('memory.overview.empty.loading')}
      </section>
    </MemoryPageFrame>
  );
};

export default MemoryOverviewPage;
