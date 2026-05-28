import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { streamChatPreview, type PreviewTurn } from '../../api/modules/chatPreview';
import type { SeedPreview } from '../../api/modules/personas';
import { PersonaPreviewStarterChips } from './PersonaPreviewStarterChips';

const MAX_USER_TURNS_PER_PERSONA = 5;

export interface PersonaPreviewChatProps {
  previews: SeedPreview[];
  onConfirm: (seedSlug: string) => void;
}

type TranscriptMap = Record<string, PreviewTurn[]>;

export function PersonaPreviewChat({
  previews,
  onConfirm,
}: PersonaPreviewChatProps): JSX.Element {
  const { t } = useTranslation('onboarding');
  const sortedPreviews = useMemo(
    () => [...previews].sort((a, b) => a.order - b.order),
    [previews],
  );
  const [activeSeed, setActiveSeed] = useState<string | null>(
    sortedPreviews[0]?.seed_slug ?? null,
  );
  const [transcripts, setTranscripts] = useState<TranscriptMap>({});
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);

  const activeTranscript = activeSeed ? transcripts[activeSeed] ?? [] : [];
  const userTurnCount = activeTranscript.filter((m) => m.role === 'user').length;
  const capReached = userTurnCount >= MAX_USER_TURNS_PER_PERSONA;

  const appendTurn = useCallback((seedSlug: string, turn: PreviewTurn) => {
    setTranscripts((prev) => {
      const list = prev[seedSlug] ?? [];
      return { ...prev, [seedSlug]: [...list, turn] };
    });
  }, []);

  const updateLastAssistantContent = useCallback(
    (seedSlug: string, deltaText: string) => {
      setTranscripts((prev) => {
        const list = prev[seedSlug] ?? [];
        const lastIdx = list.length - 1;
        if (lastIdx < 0 || list[lastIdx].role !== 'assistant') return prev;
        const updated: PreviewTurn = {
          role: 'assistant',
          content: list[lastIdx].content + deltaText,
        };
        return {
          ...prev,
          [seedSlug]: [...list.slice(0, lastIdx), updated],
        };
      });
    },
    [],
  );

  const send = useCallback(async () => {
    if (!activeSeed || !draft.trim() || busy || capReached) return;
    const userTurn: PreviewTurn = { role: 'user', content: draft.trim() };
    const seed = activeSeed;
    const snapshotHistory = transcripts[seed] ?? [];
    appendTurn(seed, userTurn);
    appendTurn(seed, { role: 'assistant', content: '' });
    setDraft('');
    setBusy(true);
    try {
      for await (const chunk of streamChatPreview({
        seed_slug: seed,
        history: snapshotHistory,
        message: userTurn,
      })) {
        updateLastAssistantContent(seed, chunk);
      }
    } catch (err) {
      updateLastAssistantContent(seed, `\n[error: ${(err as Error).message}]`);
    } finally {
      setBusy(false);
    }
  }, [activeSeed, draft, busy, capReached, transcripts, appendTurn, updateLastAssistantContent]);

  const handleChipPick = useCallback((prompt: string) => {
    setDraft(prompt);
  }, []);

  return (
    <div className="grid h-full grid-cols-[200px_1fr] gap-4">
      {/* Left: avatar rail */}
      <div className="flex flex-col gap-2 overflow-y-auto border-r border-[#e6d7c5] pr-2 dark:border-[#5b4a3d]">
        {sortedPreviews.map((p) => (
          <button
            key={p.seed_slug}
            type="button"
            onClick={() => setActiveSeed(p.seed_slug)}
            aria-pressed={activeSeed === p.seed_slug}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-left transition ${
              activeSeed === p.seed_slug
                ? 'bg-[#f4eadf] dark:bg-[#5b4a3d]'
                : 'hover:bg-[#fbf6ef] dark:hover:bg-[#3d2f25]'
            }`}
          >
            <img src={p.avatar} alt="" className="h-10 w-10 rounded-full" />
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{p.name}</div>
              <div className="truncate text-xs text-[#7d685a] dark:text-[#c8b7a7]">
                {p.description}
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* Right: preview chat */}
      <div className="flex flex-col gap-3">
        <div className="flex-1 overflow-y-auto rounded-lg border border-[#e6d7c5] bg-white p-4 dark:border-[#5b4a3d] dark:bg-[#2a2018]">
          {activeTranscript.length === 0 && (
            <p className="text-sm text-[#7d685a] dark:text-[#c8b7a7]">
              {t('personaPreview.emptyHint')}
            </p>
          )}
          {activeTranscript.map((turn, idx) => (
            <div
              key={idx}
              className={`mb-2 ${turn.role === 'user' ? 'text-right' : 'text-left'}`}
            >
              <span
                className={`inline-block max-w-[80%] rounded-2xl px-3 py-2 text-sm ${
                  turn.role === 'user'
                    ? 'bg-[#35261f] text-white dark:bg-[#f4eadf] dark:text-[#35261f]'
                    : 'bg-[#f4eadf] text-[#35261f] dark:bg-[#5b4a3d] dark:text-[#f4eadf]'
                }`}
              >
                {turn.content}
              </span>
            </div>
          ))}
        </div>

        <PersonaPreviewStarterChips onPick={handleChipPick} />

        <div className="flex items-center gap-2">
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t('personaPreview.composerPlaceholder')}
            disabled={capReached}
            className="flex-1 rounded-md border border-[#d8c9b8] bg-white px-3 py-2 text-sm dark:border-[#5b4a3d] dark:bg-[#3d2f25]"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <button
            type="button"
            onClick={send}
            disabled={!draft.trim() || busy || capReached}
            className="rounded-md bg-[#35261f] px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-[#f4eadf] dark:text-[#35261f]"
          >
            {t('personaPreview.send')}
          </button>
        </div>

        {capReached && (
          <p className="text-xs text-[#7d685a] dark:text-[#c8b7a7]">
            {t('personaPreview.capReached')}
          </p>
        )}

        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => activeSeed && onConfirm(activeSeed)}
            disabled={!activeSeed}
            className="rounded-full bg-[#35261f] px-6 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-[#f4eadf] dark:text-[#35261f]"
          >
            {t('personaPreview.confirm')}
          </button>
        </div>
      </div>
    </div>
  );
}
