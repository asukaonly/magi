import { useEffect, useRef } from "react";
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Loader2,
  MessageCircleMore,
  RefreshCw,
  Send,
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
import {
  ONBOARDING_PRIMARY_ACTION_CLASS,
  ONBOARDING_SECONDARY_ACTION_CLASS,
} from "./onboardingStyles";

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
  onStorySubmit: () => void;
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
  onStorySubmit,
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

  const routeBackButton = (
    <Button
      type="button"
      variant="ghost"
      className={`${ONBOARDING_SECONDARY_ACTION_CLASS} min-h-11 self-start px-2`}
      onClick={() => onRouteChange("choose")}
      disabled={storySubmitting || storyLocked}
    >
      <ArrowLeft className="h-4 w-4" aria-hidden="true" />
      {t("firstContext.routes.back")}
    </Button>
  );

  const renderRouteChooser = () => (
    <div className="space-y-5" data-testid="first-context-route-chooser">
      <div className="space-y-2">
        <h3
          ref={routeHeadingRef}
          tabIndex={-1}
          className="text-2xl font-semibold leading-8 text-foreground outline-none"
        >
          {t("firstContext.title")}
        </h3>
        <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
          {t("firstContext.body")}
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <button
          type="button"
          data-testid="first-context-route-question"
          className="group min-h-36 rounded-2xl border border-border/80 bg-card px-5 py-5 text-left transition-[border-color,background-color,transform] duration-200 motion-safe:hover:-translate-y-0.5 hover:border-primary/40 hover:bg-primary/[0.035] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 motion-safe:active:translate-y-0 motion-reduce:transform-none"
          onClick={() => onRouteChange("question")}
        >
          <span className="flex items-start gap-4">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
              <MessageCircleMore className="h-5 w-5" aria-hidden="true" />
            </span>
            <span className="space-y-2">
              <span className="block text-base font-semibold text-foreground">
                {t("firstContext.routes.question.title")}
              </span>
              <span className="block text-sm leading-6 text-muted-foreground">
                {t("firstContext.routes.question.body")}
              </span>
              <span className="block text-xs font-medium text-primary/80">
                {t("firstContext.routes.question.meta")}
              </span>
            </span>
          </span>
        </button>

        <button
          type="button"
          data-testid="first-context-route-activity"
          className="group min-h-36 rounded-2xl border border-border/80 bg-card px-5 py-5 text-left transition-[border-color,background-color,transform] duration-200 motion-safe:hover:-translate-y-0.5 hover:border-primary/40 hover:bg-primary/[0.035] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 motion-safe:active:translate-y-0 motion-reduce:transform-none"
          onClick={() => onRouteChange("activity")}
        >
          <span className="flex items-start gap-4">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
              <Activity className="h-5 w-5" aria-hidden="true" />
            </span>
            <span className="space-y-2">
              <span className="block text-base font-semibold text-foreground">
                {t("firstContext.routes.activity.title")}
              </span>
              <span className="block text-sm leading-6 text-muted-foreground">
                {t("firstContext.routes.activity.body")}
              </span>
              <span className="block text-xs font-medium text-primary/80">
                {t("firstContext.routes.activity.meta")}
              </span>
            </span>
          </span>
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
      <div className="space-y-4" data-testid="first-context-question-route">
        {routeBackButton}
        <div className="space-y-2">
          <h3
            ref={routeHeadingRef}
            tabIndex={-1}
            className="text-2xl font-semibold leading-8 text-foreground outline-none"
          >
            {t("firstContext.story.title")}
          </h3>
          <p
            id={descriptionId}
            className="max-w-2xl text-sm leading-6 text-muted-foreground"
          >
            {t("firstContext.story.body")}
          </p>
        </div>

        <div className="rounded-2xl border border-primary/20 bg-primary/[0.035] px-5 py-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="space-y-1.5">
              <span className="text-xs font-medium text-primary/80">
                {t("firstContext.story.questionLabel")}
              </span>
              <p
                id={questionDescriptionId}
                className="max-w-xl text-lg font-medium leading-7 text-foreground"
                aria-live="polite"
                data-testid={`first-context-question-${questionId}`}
              >
                {t(`firstContext.story.questions.${questionId}`)}
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              className="min-h-11 shrink-0"
              onClick={onQuestionChange}
              disabled={storySubmitting || storyLocked}
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              {t("firstContext.story.changeQuestion")}
            </Button>
          </div>

          <div className="mt-5 space-y-2">
            <label
              htmlFor="first-context-story"
              className="text-sm font-medium text-foreground"
            >
              {t("firstContext.story.inputLabel")}
            </label>
            <textarea
              ref={storyTextareaRef}
              id="first-context-story"
              data-testid="first-context-story-input"
              rows={5}
              value={storyDraft}
              onChange={(event) => onStoryDraftChange(event.target.value)}
              placeholder={t("firstContext.story.placeholder")}
              disabled={storySubmitting || storyLocked}
              aria-invalid={Boolean(storyError)}
              aria-describedby={describedBy || undefined}
              className="min-h-32 w-full resize-y rounded-xl border border-input bg-background px-4 py-3 text-sm leading-6 text-foreground outline-none transition-colors placeholder:text-muted-foreground/65 focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 disabled:cursor-not-allowed disabled:opacity-60"
            />
            {storyError ? (
              <p
                id="first-context-story-error"
                role="alert"
                className="flex items-start gap-2 text-sm leading-5 text-destructive"
              >
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{storyError}</span>
              </p>
            ) : null}
          </div>

          <div className="mt-4 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs leading-5 text-muted-foreground">
              {t("firstContext.story.privacyNote")}
            </p>
            <div className="flex shrink-0 flex-col-reverse gap-2 sm:flex-row">
              {storyLocked && !storySubmitted && storyError ? (
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
              ) : null}
              <Button
                type="button"
                size="lg"
                data-testid="first-context-story-submit"
                className={`${ONBOARDING_PRIMARY_ACTION_CLASS} min-h-11 shrink-0`}
                onClick={onStorySubmit}
                disabled={storySubmitting}
              >
                {storySubmitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Send className="h-4 w-4" aria-hidden="true" />
                )}
                {storySubmitting
                  ? t("firstContext.story.submitting")
                  : storySubmitted
                    ? t("firstContext.story.retryEntering")
                    : t("firstContext.story.submit")}
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderActivityRoute = () => (
    <div className="space-y-4" data-testid="first-context-activity-route">
      {routeBackButton}
      <div className="space-y-2">
        <h3
          ref={routeHeadingRef}
          tabIndex={-1}
          className="text-2xl font-semibold leading-8 text-foreground outline-none"
        >
          {t("firstContext.activity.title")}
        </h3>
        <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
          {t("firstContext.activity.body")}
        </p>
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
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-8 pb-7 pt-0 lg:pb-8 lg:pt-0">
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
