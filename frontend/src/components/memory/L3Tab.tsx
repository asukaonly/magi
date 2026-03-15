/**
 * L3Tab - L3 Reflection/Summaries tab component
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { FileText } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { L3Summary, MemoryStatistics } from '@/api/modules/memory';
import { formatTimestamp } from '@/hooks/useMemory';

interface L3TabProps {
  stats: MemoryStatistics['l3'];
  summaries: L3Summary[];
}

export const L3Tab: React.FC<L3TabProps> = ({ stats, summaries }) => {
  const { t } = useTranslation('app');

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-4">
          <div className="text-2xl font-bold">{stats.summary_count}</div>
          <div className="text-sm text-muted-foreground">{t('memory.l3.summaryCount')}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            {t('memory.l3.summaries')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {summaries.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l3.noSummaries')}
            </div>
          ) : (
            <div className="space-y-4 max-h-96 overflow-y-auto">
              {summaries.map((summary) => (
                <div key={summary.summary_id} className="p-4 border rounded-lg">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Badge>{summary.summary_type}</Badge>
                      <Badge variant="outline">{summary.summary_category}</Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {formatTimestamp(summary.created_at)}
                    </span>
                  </div>
                  <p className="text-sm">{summary.content}</p>
                  {summary.key_topics?.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {summary.key_topics.map((topic, i) => (
                        <Badge key={i} variant="secondary" className="text-xs">{topic}</Badge>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default L3Tab;
