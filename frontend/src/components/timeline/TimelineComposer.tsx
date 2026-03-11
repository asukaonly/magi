import React, { useState } from 'react';
import { ImagePlus, Plus, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

import type { TimelineManualEntryRequest } from '@/api/modules/timeline';

interface TimelineComposerProps {
  submitting?: boolean;
  onSubmit: (payload: TimelineManualEntryRequest) => Promise<void> | void;
}

export const TimelineComposer: React.FC<TimelineComposerProps> = ({
  submitting = false,
  onSubmit,
}) => {
  const { t } = useTranslation('app');
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [text, setText] = useState('');
  const [imageRefInput, setImageRefInput] = useState('');
  const [imageRefs, setImageRefs] = useState<string[]>([]);

  const appendImageRef = () => {
    const trimmed = imageRefInput.trim();
    if (!trimmed || imageRefs.includes(trimmed)) {
      return;
    }
    setImageRefs((current) => [...current, trimmed]);
    setImageRefInput('');
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const payload = {
      title: title.trim(),
      summary: summary.trim(),
      text: text.trim(),
      image_refs: imageRefs,
    };
    if (!payload.title || !payload.summary || !payload.text) {
      return;
    }
    await onSubmit(payload);
    setTitle('');
    setSummary('');
    setText('');
    setImageRefs([]);
    setImageRefInput('');
  };

  return (
    <Card className="border-border/40 bg-card/80 shadow-sm">
      <CardHeader className="pb-4">
        <CardTitle>{t('timeline.composer.titleCard')}</CardTitle>
        <CardDescription>{t('timeline.composer.subtitle')}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <label className="block space-y-2" htmlFor="timeline-title">
            <span className="text-sm font-medium text-foreground">{t('timeline.composer.title')}</span>
            <Input
              id="timeline-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={t('timeline.composer.titlePlaceholder')}
            />
          </label>

          <label className="block space-y-2" htmlFor="timeline-summary">
            <span className="text-sm font-medium text-foreground">{t('timeline.composer.summary')}</span>
            <Input
              id="timeline-summary"
              value={summary}
              onChange={(event) => setSummary(event.target.value)}
              placeholder={t('timeline.composer.summaryPlaceholder')}
            />
          </label>

          <label className="block space-y-2" htmlFor="timeline-text">
            <span className="text-sm font-medium text-foreground">{t('timeline.composer.text')}</span>
            <Textarea
              id="timeline-text"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder={t('timeline.composer.textPlaceholder')}
              className="min-h-[132px]"
            />
          </label>

          <div className="space-y-3">
            <label className="block space-y-2" htmlFor="timeline-image-ref">
              <span className="text-sm font-medium text-foreground">{t('timeline.composer.imageRef')}</span>
              <div className="flex gap-2">
                <Input
                  id="timeline-image-ref"
                  value={imageRefInput}
                  onChange={(event) => setImageRefInput(event.target.value)}
                  placeholder={t('timeline.composer.imagePlaceholder')}
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={appendImageRef}
                  aria-label={t('timeline.composer.addImage')}
                >
                  <Plus className="h-4 w-4" />
                  {t('timeline.composer.addImage')}
                </Button>
              </div>
            </label>

            {imageRefs.length > 0 && (
              <div className="space-y-2">
                {imageRefs.map((imageRef) => (
                  <div
                    key={imageRef}
                    className="flex items-center justify-between rounded-2xl border border-border/40 bg-background/70 px-3 py-2"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <ImagePlus className="h-4 w-4 shrink-0 text-primary" />
                      <span className="truncate text-sm text-foreground">{imageRef}</span>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => setImageRefs((current) => current.filter((item) => item !== imageRef))}
                      aria-label={t('timeline.composer.removeImage')}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <Button
            type="submit"
            className="w-full rounded-xl"
            disabled={submitting || !title.trim() || !summary.trim() || !text.trim()}
            aria-label={t('timeline.composer.submit')}
          >
            {t('timeline.composer.submit')}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
};

export default TimelineComposer;
