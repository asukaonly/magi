import { useEffect, useRef } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  RefreshCw,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  InstallableCatalogMode,
  InstallableItem,
} from "@/api/modules/systemSuggestions";
import type { LLMConfig } from "@/api/modules/config";
import { EmptyStateAvailableSensors } from "@/components/empty-state/EmptyStateAvailableSensors";
import { Button } from "@/components/ui/button";
import type { PluginInstallDoneInfo } from "@/stores/pluginInstallPanel";
import { localizedPluginText } from "@/utils/plugin-display-groups";
import { getMemoryModelStatus } from "./memoryModelStatus";
import { ONBOARDING_SECONDARY_ACTION_CLASS } from "./onboardingStyles";

export const FIRST_CONTEXT_QUESTION_IDS = [
  "recent_feeling",
  "repeating_content",
  "personal_time",
  "reluctant_routine",
] as const;

export type FirstContextQuestionId =
  (typeof FIRST_CONTEXT_QUESTION_IDS)[number];

export type FirstContextRoute = "choose" | "question" | "activity";

export function isFirstContextQuestionId(
  value: unknown,
): value is FirstContextQuestionId {
  return FIRST_CONTEXT_QUESTION_IDS.includes(value as FirstContextQuestionId);
}

export function isFirstContextRoute(value: unknown): value is FirstContextRoute {
  return value === "choose" || value === "question" || value === "activity";
}

interface FirstContextStepProps {
  llmConfig: LLMConfig;
  route: FirstContextRoute;
  questionId: FirstContextQuestionId;
  storyDraft: string;
  storySubmitting?: boolean;
  storyLocked?: boolean;
  storySubmitted?: boolean;
  storyError?: string | null;
  onRouteChange: (route: FirstContextRoute) => void;
  onQuestionChange: () => void;
  onStoryDraftChange: (value: string) => void;
  onStoryContinueWithoutConfirmation: () => void;
  installableItems?: InstallableItem[];
  installableCatalogMode?: InstallableCatalogMode | null;
  installableLoading?: boolean;
  installableError?: Error | null;
  onRetryInstallable?: () => void;
  connectedPluginIds?: string[];
  connectedCountsByPluginId?: Record<string, number | null>;
  onConnectDone: (pluginId: string, info?: PluginInstallDoneInfo) => void;
}

export function FirstContextStep({
  llmConfig,
  route,
  questionId,
  storyDraft,
  storySubmitting = false,
  storyLocked = false,
  storySubmitted = false,
  storyError = null,
  onRouteChange,
  onQuestionChange,
  onStoryDraftChange,
  onStoryContinueWithoutConfirmation,
  installableItems,
  installableCatalogMode,
  installableLoading,
  installableError,
  onRetryInstallable,
  connectedPluginIds = [],
  connectedCountsByPluginId = {},
  onConnectDone,
}: FirstContextStepProps): JSX.Element {
  const { t, i18n } = useTranslation("onboarding");
  const storyTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const routeHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const previousRouteRef = useRef<FirstContextRoute>(route);
  const memoryModelMissing = getMemoryModelStatus(llmConfig) === "missing";
  const connectedCount = connectedPluginIds.length;
  const language = i18n.resolvedLanguage ?? i18n.language;
  const connectedPluginName = (pluginId: string): string => {
    const item = installableItems?.find((candidate) => candidate.plugin_id === pluginId);
    return item
      ? localizedPluginText(item.name, item.name_i18n, language)
      : pluginId;
  };
  const preparedCount = connectedPluginIds.reduce((total, pluginId) => {
    const value = connectedCountsByPluginId[pluginId];
    return typeof value === "number" && Number.isFinite(value)
      ? total + value
      : total;
  }, 0);

  useEffect(() => {
    const previousRoute = previousRouteRef.current;
    previousRouteRef.current = route;
    if (previousRoute === route) {
      return;
    }
    window.requestAnimationFrame(() => {
      if (route === "question") {
        storyTextareaRef.current?.focus();
        return;
      }
      routeHeadingRef.current?.focus();
    });
  }, [route]);

  const renderRouteChooser = () => (
    <div className="space-y-7" data-testid="first-context-route-chooser">
      <div className="max-w-[840px]">
        <p className="mb-3 text-xs font-semibold tracking-[0.08em] text-primary">
          {t("firstContext.kicker")}
        </p>
        <h3
          ref={routeHeadingRef}
          tabIndex={-1}
          className="text-[clamp(1.75rem,2.6vw,2.15rem)] font-semibold leading-[1.25] tracking-[-0.035em] text-foreground outline-none"
        >
          {t("firstContext.title")}
        </h3>
        <p className="mt-3 max-w-[810px] text-base leading-7 text-muted-foreground">
          {t("firstContext.body")}
        </p>
      </div>

      <div className="grid gap-3.5 md:grid-cols-2">
        <button
          type="button"
          data-testid="first-context-route-question"
          className="group grid min-h-[170px] grid-cols-[48px_minmax(0,1fr)_24px] items-start gap-3.5 rounded-[15px] border border-border/80 bg-card/65 px-[18px] py-[21px] text-left transition-[border-color,background-color,box-shadow,transform] duration-200 motion-safe:hover:-translate-y-0.5 hover:border-primary/40 hover:bg-card hover:shadow-[0_16px_38px_-30px_hsl(var(--foreground)/0.56)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 focus-visible:ring-offset-2 motion-safe:active:translate-y-0 motion-reduce:transform-none"
          onClick={() => onRouteChange("question")}
        >
          <span
            className="grid h-[46px] w-[46px] place-items-center rounded-[15px] bg-background text-xl font-bold text-primary shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.17)]"
            aria-hidden="true"
          >
            {t("firstContext.routes.question.symbol")}
          </span>
          <span>
            <span className="block text-base font-semibold leading-6 tracking-[-0.015em] text-foreground">
              {t("firstContext.routes.question.title")}
            </span>
            <span className="mt-1.5 block text-[13px] leading-[1.65] text-muted-foreground">
              {t("firstContext.routes.question.body")}
            </span>
            <span className="mt-3 flex flex-wrap gap-1.5">
              <span className="rounded-full bg-background px-2 py-1 text-[11px] leading-none text-muted-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.75)]">
                {t("firstContext.routes.optional")}
              </span>
              <span className="rounded-full bg-background px-2 py-1 text-[11px] leading-none text-muted-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.75)]">
                {t("firstContext.routes.question.meta")}
              </span>
            </span>
          </span>
          <ChevronRight
            className="mt-0.5 h-5 w-5 text-primary transition-transform duration-200 group-hover:translate-x-0.5"
            aria-hidden="true"
          />
        </button>

        <button
          type="button"
          data-testid="first-context-route-activity"
          className="group grid min-h-[170px] grid-cols-[48px_minmax(0,1fr)_24px] items-start gap-3.5 rounded-[15px] border border-border/80 bg-card/65 px-[18px] py-[21px] text-left transition-[border-color,background-color,box-shadow,transform] duration-200 motion-safe:hover:-translate-y-0.5 hover:border-primary/40 hover:bg-card hover:shadow-[0_16px_38px_-30px_hsl(var(--foreground)/0.56)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 focus-visible:ring-offset-2 motion-safe:active:translate-y-0 motion-reduce:transform-none"
          onClick={() => onRouteChange("activity")}
        >
          <span
            className="grid h-[46px] w-[46px] place-items-center rounded-[15px] bg-background text-xl font-bold text-primary shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.17)]"
            aria-hidden="true"
          >
            {t("firstContext.routes.activity.symbol")}
          </span>
          <span>
            <span className="block text-base font-semibold leading-6 tracking-[-0.015em] text-foreground">
              {t("firstContext.routes.activity.title")}
            </span>
            <span className="mt-1.5 block text-[13px] leading-[1.65] text-muted-foreground">
              {t("firstContext.routes.activity.body")}
            </span>
            <span className="mt-3 flex flex-wrap gap-1.5">
              <span className="rounded-full bg-background px-2 py-1 text-[11px] leading-none text-muted-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.75)]">
                {t("firstContext.routes.optional")}
              </span>
              <span className="rounded-full bg-background px-2 py-1 text-[11px] leading-none text-muted-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.75)]">
                {t("firstContext.routes.activity.meta")}
              </span>
            </span>
          </span>
          <ChevronRight
            className="mt-0.5 h-5 w-5 text-primary transition-transform duration-200 group-hover:translate-x-0.5"
            aria-hidden="true"
          />
        </button>
      </div>

      <p className="text-xs leading-5 text-muted-foreground">
        {t("firstContext.routes.note")}
      </p>
    </div>
  );

  const renderQuestionRoute = () => {
    const descriptionId = "first-context-story-description";
    const questionDescriptionId = "first-context-story-question";
    const errorId = storyError ? "first-context-story-error" : undefined;
    const describedBy = [descriptionId, questionDescriptionId, errorId]
      .filter(Boolean)
      .join(" ");
    return (
      <div className="space-y-5" data-testid="first-context-question-route">
        <div className="flex items-start justify-between gap-5">
          <div className="max-w-[840px]">
            <p className="mb-3 text-xs font-semibold tracking-[0.08em] text-primary">
              {t("firstContext.story.kicker")}
            </p>
            <h3
              ref={routeHeadingRef}
              tabIndex={-1}
              className="text-[clamp(1.75rem,2.6vw,2.15rem)] font-semibold leading-[1.25] tracking-[-0.035em] text-foreground outline-none"
            >
              {t("firstContext.story.title")}
            </h3>
          </div>
          <span className="hidden shrink-0 rounded-full bg-accent/75 px-3 py-2 text-xs font-semibold text-primary sm:inline-flex">
            {t("firstContext.story.badge")}
          </span>
        </div>
        <div className="-mt-2">
          <p
            id={descriptionId}
            className="max-w-[810px] text-base leading-7 text-muted-foreground"
          >
            {t("firstContext.story.body")}
          </p>
        </div>

        <div className="overflow-hidden rounded-2xl border border-border/80 bg-card/70">
          <div className="px-5 py-5 sm:px-6 sm:py-6">
            <div className="flex items-baseline justify-between gap-4">
              <p
                id={questionDescriptionId}
                className="text-sm font-semibold leading-6 text-foreground"
                aria-live="polite"
                data-testid={`first-context-question-${questionId}`}
              >
                {t(`firstContext.story.questions.${questionId}`)}
              </p>
              <span className="shrink-0 text-xs text-muted-foreground">
                {t("firstContext.story.shortHint")}
              </span>
            </div>

            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {t("firstContext.story.inputHint")}
            </p>

            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                className="h-9 rounded-full px-3 text-xs font-medium text-muted-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.9)]"
                onClick={onQuestionChange}
                disabled={storySubmitting || storyLocked}
              >
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                {t("firstContext.story.changeQuestion")}
              </Button>
            </div>

            <label htmlFor="first-context-story" className="sr-only">
              {t("firstContext.story.inputLabel")}
            </label>
            <textarea
              ref={storyTextareaRef}
              id="first-context-story"
              data-testid="first-context-story-input"
              rows={7}
              value={storyDraft}
              onChange={(event) => onStoryDraftChange(event.target.value)}
              placeholder={t("firstContext.story.placeholder")}
              disabled={storySubmitting || storyLocked}
              aria-invalid={Boolean(storyError)}
              aria-describedby={describedBy || undefined}
              className="mt-4 min-h-[205px] w-full resize-y rounded-xl border border-input bg-background px-4 py-3.5 text-sm leading-6 text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-muted-foreground/65 focus-visible:border-primary/60 focus-visible:ring-4 focus-visible:ring-primary/10 disabled:cursor-not-allowed disabled:opacity-60"
            />
            {storyError ? (
              <p
                id="first-context-story-error"
                role="alert"
                className="mt-2 flex items-start gap-2 text-sm leading-5 text-destructive"
              >
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{storyError}</span>
              </p>
            ) : null}
          </div>
        </div>

        <div className="rounded-xl bg-accent/30 px-4 py-3 text-xs leading-5 text-muted-foreground">
          <p>{t("firstContext.story.contextNote")}</p>
          <p className="mt-1 opacity-80">{t("firstContext.story.privacyNote")}</p>
        </div>

        {storyLocked && !storySubmitted && storyError ? (
          <div className="flex justify-end">
            <Button
              type="button"
              variant="ghost"
              size="lg"
              data-testid="first-context-story-continue-without-confirmation"
              className={`${ONBOARDING_SECONDARY_ACTION_CLASS} min-h-11 shrink-0`}
              onClick={onStoryContinueWithoutConfirmation}
              disabled={storySubmitting}
            >
              {t("firstContext.story.continueWithoutConfirmation")}
            </Button>
          </div>
        ) : null}
      </div>
    );
  };

  const renderActivityRoute = () => (
    <div className="space-y-5" data-testid="first-context-activity-route">
      <div className="flex items-start justify-between gap-5">
        <div className="max-w-[840px]">
          <p className="mb-3 text-xs font-semibold tracking-[0.08em] text-primary">
            {t("firstContext.activity.kicker")}
          </p>
          <h3
            ref={routeHeadingRef}
            tabIndex={-1}
            className="text-[clamp(1.75rem,2.6vw,2.15rem)] font-semibold leading-[1.25] tracking-[-0.035em] text-foreground outline-none"
          >
            {t("firstContext.activity.title")}
          </h3>
          <p className="mt-3 max-w-[810px] text-base leading-7 text-muted-foreground">
            {t("firstContext.activity.body")}
          </p>
        </div>
        <span className="hidden shrink-0 rounded-full bg-accent/75 px-3 py-2 text-xs font-semibold text-primary sm:inline-flex">
          {t("firstContext.activity.badge")}
        </span>
      </div>

      {memoryModelMissing ? (
        <div
          data-testid="first-context-memory-warning"
          className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50/80 px-3.5 py-3 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <span className="space-y-1">
            <span className="block font-medium">
              {t("firstContext.memoryWarningTitle")}
            </span>
            <span className="block text-xs leading-5 opacity-80">
              {t("firstContext.memoryWarningBody")}
            </span>
          </span>
        </div>
      ) : null}

      <div
        data-testid="first-context-scope-note"
        className="text-xs leading-5 text-muted-foreground"
      >
        {t("firstContext.scopeHint")}
      </div>

      {connectedCount > 0 ? (
        <div className="flex items-start gap-3 rounded-lg border border-primary/18 bg-primary/5 px-3.5 py-3 text-sm">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <span className="space-y-2">
            <span className="block font-medium text-foreground">
              {t("firstContext.connectedCount", { count: connectedCount })}
            </span>
            <span className="flex flex-wrap gap-1.5">
              {connectedPluginIds.map((pluginId) => (
                <span
                  key={pluginId}
                  className="rounded-full border border-primary/15 bg-background/70 px-2 py-0.5 text-xs font-medium text-foreground"
                >
                  {connectedPluginName(pluginId)}
                </span>
              ))}
            </span>
            {preparedCount > 0 ? (
              <span className="block text-xs leading-5 text-muted-foreground">
                {t("firstContext.preparedCount", { count: preparedCount })}
              </span>
            ) : (
              <span className="block text-xs leading-5 text-muted-foreground">
                {t("firstContext.connectedHint")}
              </span>
            )}
          </span>
        </div>
      ) : null}

      <EmptyStateAvailableSensors
        variant="first_context"
        showBrowseAll={false}
        panelContext="first_context"
        excludePluginIds={connectedPluginIds}
        installableItems={installableItems}
        installableCatalogMode={installableCatalogMode}
        installableLoading={installableLoading}
        installableError={installableError}
        onRetryInstallable={onRetryInstallable}
        onConnectDone={onConnectDone}
      />

      <p className="text-xs leading-5 text-muted-foreground">
        {t("firstContext.note")}
      </p>
    </div>
  );

  return (
    <div className="h-full min-h-0 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-[1040px] flex-col gap-5 px-4 pb-8 pt-0 sm:px-5 lg:px-6">
        {route === "choose"
          ? renderRouteChooser()
          : route === "question"
            ? renderQuestionRoute()
            : renderActivityRoute()}
      </div>
    </div>
  );
}

export default FirstContextStep;
