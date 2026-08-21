import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { personasApi, type SeedPreview } from "../../api/modules/personas";
import type { LLMConfig } from "../../api/modules/config";
import {
  buildRailItems,
  type CustomPersonaDraft,
  type PersonaCreationDraft,
  type PresetProfileState,
  type RailItem,
} from "./persona-preview/personaPreviewModel";
import { usePersonaDraftRegistry } from "./persona-preview/usePersonaDraftRegistry";
import { usePersonaGenerationController } from "./persona-preview/usePersonaGenerationController";
import { usePersonaPreviewConversation } from "./persona-preview/usePersonaPreviewConversation";
import { PreviewAvatar } from "./persona-preview/PersonaPreviewPrimitives";
import { PersonaPicker } from "./persona-preview/PersonaPicker";
import { PersonaCreationPanel } from "./persona-preview/PersonaCreationPanel";
import { PersonaPreviewDetail } from "./persona-preview/PersonaPreviewDetail";
import type { PersonaPreviewRoute } from "./persona-preview/personaPreviewRoute";

export type {
  CustomPersonaDraft,
  PersonaCreationDraft,
} from "./persona-preview/personaPreviewModel";

export interface PersonaPreviewChatProps {
  previews: SeedPreview[];
  /** Whether builtin seed previews are still loading. */
  previewsLoading: boolean;
  /** The persona slug selected by the parent onboarding flow. */
  activeSeed: string | null;
  /**
   * Seed locale ("zh" / "en") the previews were loaded with — forwarded to the
   * preview endpoint so a seed_slug resolves against the right preset folder.
   */
  locale?: string;
  /**
   * The in-progress (unsaved) onboarding LLM config. Passed to the preview
   * endpoint as `llm_override` and to persona generation, so both work before
   * the user has persisted their selections / started the LLM runtime.
   */
  llmConfig?: LLMConfig;
  /** Requests a selection change from the parent onboarding flow. */
  onActiveSeedChange: (seedSlug: string | null) => void;
  /** Disables all persona interactions while the selection is being confirmed. */
  disabled: boolean;
  /** Persistent confirmation failure shown until retry or selection change. */
  confirmationError: string | null;
  /** Custom drafts to re-hydrate (e.g. after an onboarding reload). */
  initialCustomPersonas?: CustomPersonaDraft[];
  /** Fires whenever the set of custom drafts changes, so the parent can persist them. */
  onCustomPersonasChange?: (drafts: CustomPersonaDraft[]) => void;
  /** Restores an unfinished custom-persona creation or reference-editing draft. */
  initialCreationDraft?: PersonaCreationDraft | null;
  /** Persists the unfinished custom-persona creation state through onboarding reloads. */
  onCreationDraftChange?: (draft: PersonaCreationDraft | null) => void;
  /** Restores the last visible persona picker, preview, profile, or creation view. */
  initialRoute?: PersonaPreviewRoute;
  /** Persists the visible persona subview independently from any retained draft. */
  onRouteChange?: (route: PersonaPreviewRoute) => void;
  /**
   * Fires when persona generation starts (true) / finishes (false), so the
   * parent can disable step navigation while a generation is in flight.
   */
  onGeneratingChange?: (generating: boolean) => void;
}

export function PersonaPreviewChat({
  previews,
  previewsLoading,
  activeSeed,
  locale,
  llmConfig,
  onActiveSeedChange,
  disabled,
  confirmationError,
  initialCustomPersonas,
  onCustomPersonasChange,
  initialCreationDraft,
  onCreationDraftChange,
  initialRoute,
  onRouteChange,
  onGeneratingChange,
}: PersonaPreviewChatProps): JSX.Element {
  const { t } = useTranslation("onboarding");
  const shouldReduceMotion = useReducedMotion() ?? false;
  const registry = usePersonaDraftRegistry({
    initialDrafts: initialCustomPersonas ?? [],
    onChange: onCustomPersonasChange,
  });
  const customDrafts = registry.drafts;
  const railItems = buildRailItems(previews, customDrafts);

  const [route, setRoute] = useState<PersonaPreviewRoute>(
    () => initialRoute ?? (initialCreationDraft ? "create" : "picker"),
  );
  const stage = route === "picker" ? "picker" : "detail";
  const mode =
    route === "profile" ? "profile" : route === "create" ? "create" : "chat";
  const changeRoute = useCallback(
    (nextRoute: PersonaPreviewRoute) => {
      setRoute(nextRoute);
      onRouteChange?.(nextRoute);
    },
    [onRouteChange],
  );
  const [presetProfiles, setPresetProfiles] = useState<
    Record<string, PresetProfileState>
  >({});

  const activeItem = railItems.find((item) => item.slug === activeSeed);
  const conversation = usePersonaPreviewConversation({
    activeSeed,
    activeItem,
    disabled,
    locale,
    llmConfig,
    registry,
  });
  const handleGenerated = useCallback(() => {
    changeRoute("chat");
  }, [changeRoute]);
  const handleEditRequested = useCallback(() => {
    changeRoute("create");
  }, [changeRoute]);
  const generation = usePersonaGenerationController({
    disabled,
    llmConfig,
    initialCreationDraft,
    onCreationDraftChange,
    onActiveSeedChange,
    onGenerated: handleGenerated,
    onEditRequested: handleEditRequested,
    clearTranscript: conversation.clearTranscript,
    registry,
  });

  const {
    creationDraft,
    generating,
    startNewCreation,
    cancelCreation,
    editCustomReference,
  } = generation;

  useEffect(() => {
    if (
      !previewsLoading &&
      !disabled &&
      railItems.length > 0 &&
      !railItems.some((item) => item.slug === activeSeed)
    ) {
      onActiveSeedChange(railItems[0].slug);
    }
  }, [activeSeed, disabled, onActiveSeedChange, previewsLoading, railItems]);

  const onGeneratingChangeRef = useRef(onGeneratingChange);
  onGeneratingChangeRef.current = onGeneratingChange;
  const creationBlocksNavigation =
    generating ||
    (stage === "detail" && mode === "create" && creationDraft !== null);
  useEffect(() => {
    onGeneratingChangeRef.current?.(creationBlocksNavigation);
  }, [creationBlocksNavigation]);

  const profileLocale = locale || "en";
  const activeProfileKey =
    activeItem && !activeItem.isCustom
      ? `${profileLocale}:${activeItem.slug}`
      : null;
  const activeProfileState = activeProfileKey
    ? presetProfiles[activeProfileKey]
    : undefined;
  const activeProfileConfig = activeItem?.config ?? activeProfileState?.config;
  const transcriptScrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = transcriptScrollRef.current;
    if (element) {
      element.scrollTop = element.scrollHeight;
    }
  }, [conversation.activeTranscript]);

  const loadPresetProfile = useCallback(
    async (item: RailItem, force = false) => {
      if (item.isCustom || item.config) return;
      const key = `${profileLocale}:${item.slug}`;
      const cached = presetProfiles[key];
      if (!force && cached) {
        return;
      }

      setPresetProfiles((current) => ({
        ...current,
        [key]: { status: "loading" },
      }));
      try {
        const response = await personasApi.getPresetConfig(
          item.slug,
          profileLocale,
        );
        if (!response.data) {
          throw new Error("Persona profile is unavailable");
        }
        setPresetProfiles((current) => ({
          ...current,
          [key]: { status: "success", config: response.data },
        }));
      } catch {
        setPresetProfiles((current) => ({
          ...current,
          [key]: { status: "error" },
        }));
      }
    },
    [presetProfiles, profileLocale],
  );

  useEffect(() => {
    if (route === "profile" && activeItem) {
      void loadPresetProfile(activeItem);
    }
  }, [activeItem, loadPresetProfile, route]);

  const showActiveProfile = useCallback(() => {
    if (!activeItem) return;
    changeRoute("profile");
  }, [activeItem, changeRoute]);

  const enterPersona = useCallback(
    (item: RailItem, nextMode: "chat" | "profile") => {
      onActiveSeedChange(item.slug);
      if (nextMode === "profile") {
        changeRoute("profile");
      } else {
        changeRoute("chat");
      }
    },
    [changeRoute, onActiveSeedChange],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {confirmationError && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/35 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          {confirmationError}
        </div>
      )}
      {/* 标题与模式 tab 同行:让左 rail 和右内容区顶部对齐。detail 阶段左侧带返回 picker 的按钮。 */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-1">
        <div className="flex min-w-0 items-center gap-1.5">
          {stage === 'detail' ? (
            <button
              type="button"
              data-testid="persona-back-to-picker"
              onClick={() => changeRoute("picker")}
              disabled={disabled}
              aria-label={t('personaPreview.backToPicker')}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors duration-200 hover:bg-muted/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 disabled:opacity-40 motion-reduce:transition-none"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            </button>
          ) : null}
          {stage === 'detail' && mode !== 'create' && activeItem ? (
            <div className="flex min-w-0 items-center gap-3">
              <PreviewAvatar name={activeItem.name} avatar={activeItem.avatar} />
              <h1 className="truncate font-onboarding-display text-[1.65rem] font-bold leading-snug text-foreground">
                {activeItem.name}
              </h1>
            </div>
          ) : (
            <h1 className="font-onboarding-display text-[1.9rem] font-bold leading-snug text-foreground">
              {stage === 'detail' && mode === 'create'
                ? t('personaPreview.createCustomTitle')
                : t('steps.personaPreview')}
            </h1>
          )}
        </div>
        {stage === 'detail' && mode !== 'create' ? (
          <div
            role="group"
            aria-label={t('personaPreview.modeLabel', { name: activeItem?.name || '' })}
            className="flex w-fit shrink-0 items-center gap-1 rounded-lg bg-muted/45 p-1"
          >
            <button
              type="button"
              data-testid="persona-mode-chat"
              aria-pressed={mode === 'chat'}
              onClick={() => changeRoute("chat")}
              className={cn(
                'rounded-md px-3 py-1.5 text-sm transition-colors',
                mode === 'chat'
                  ? 'bg-background font-medium text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {t('personaPreview.talkWith', { name: activeItem?.name || '' })}
            </button>
            <button
              type="button"
              data-testid="persona-mode-profile"
              aria-pressed={mode === 'profile'}
              onClick={showActiveProfile}
              disabled={!activeItem}
              className={cn(
                'rounded-md px-3 py-1.5 text-sm transition-colors disabled:opacity-50',
                mode === 'profile'
                  ? 'bg-background font-medium text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {t('personaPreview.learnAbout', { name: activeItem?.name || '' })}
            </button>
          </div>
        ) : null}
      </div>
      <AnimatePresence initial={false} mode="wait">
        {stage === "picker" ? (
          <PersonaPicker
            items={railItems}
            activeSeed={activeSeed}
            disabled={disabled}
            shouldReduceMotion={shouldReduceMotion}
            onSelect={onActiveSeedChange}
            onEnter={enterPersona}
            onCreate={startNewCreation}
          />
        ) : (
          <motion.div
            key="persona-detail"
            className="flex min-h-0 flex-1 flex-col"
            initial={shouldReduceMotion ? false : { opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: shouldReduceMotion ? 0 : 0.24, ease: [0.22, 1, 0.36, 1] }}
          >
      <fieldset
        disabled={disabled}
        className="m-0 flex min-h-0 min-w-0 flex-1 flex-col border-0 p-0"
      >
        <legend className="sr-only">{t('steps.personaPreview')}</legend>
      {/* Detail: either the preview chat or the custom-persona composer.
          人格切换统一回到 picker 完成,这里不再有左侧 rail。 */}
      {mode === "create" ? (
        <PersonaCreationPanel
          controller={generation}
          shouldReduceMotion={shouldReduceMotion}
          onCancel={() => {
            changeRoute("picker");
            cancelCreation();
          }}
        />
      ) : (
        <PersonaPreviewDetail
          item={activeItem}
          mode={mode === "profile" ? "profile" : "chat"}
          profileConfig={activeProfileConfig}
          profileState={activeProfileState}
          shouldReduceMotion={shouldReduceMotion}
          transcriptScrollRef={transcriptScrollRef}
          conversation={conversation}
          onRetryProfile={() => {
            if (activeItem) {
              void loadPresetProfile(activeItem, true);
            }
          }}
          onEditReference={editCustomReference}
        />
      )}
      </fieldset>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
