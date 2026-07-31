import { useEffect, useRef } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  AlertCircle,
  BookOpenText,
  CheckCircle2,
  ChevronRight,
  Footprints,
  MessageCircleQuestion,
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
import {
  FIRST_CONTEXT_QUESTION_IDS,
  isFirstContextQuestionId,
  type FirstContextQuestionId,
} from "@/domain/chat/first-context";
import { getMemoryModelStatus } from "./memoryModelStatus";
import HistoryImportFlow from "@/components/history-imports/HistoryImportFlow";
import type { HistoryImportJob } from "@/api/modules/historyImports";
import {
  ONBOARDING_FIELD_CLASS,
  ONBOARDING_SECONDARY_ACTION_CLASS,
} from "./onboardingStyles";

export {
  FIRST_CONTEXT_QUESTION_IDS,
  isFirstContextQuestionId,
  type FirstContextQuestionId,
};

export type FirstContextRoute = "choose" | "question" | "history" | "activity";

export function isFirstContextRoute(value: unknown): value is FirstContextRoute {
  return (
    value === "choose" ||
    value === "question" ||
    value === "history" ||
    value === "activity"
  );
}

const KICKER_CLASS = "text-xs font-semibold tracking-[0.08em] text-primary";
const HEADING_CLASS =
  "font-onboarding-display text-[1.65rem] sm:text-3xl font-semibold leading-[1.3] tracking-[-0.01em] text-foreground outline-none";
const BODY_CLASS = "mt-3 text-[15px] leading-7 text-muted-foreground";
const BADGE_CLASS =
  "rounded-full bg-primary/10 px-2.5 py-0.5 text-[11px] font-medium text-primary";

interface RouteOptionCardProps {
  testId: string;
  icon: React.ReactNode;
  title: string;
  body: string;
  meta: string[];
  onSelect: () => void;
}

function RouteOptionCard({
  testId,
  icon,
  title,
  body,
  meta,
  onSelect,
}: RouteOptionCardProps): JSX.Element {
  return (
    <button
      type="button"
      data-testid={testId}
      className="group flex items-center gap-4 rounded-xl bg-card p-5 text-left shadow-[inset_0_0_0_1px_hsl(var(--border)/0.62),0_14px_32px_-30px_hsl(var(--foreground)/0.28)] transition-[background-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:bg-accent/45 hover:shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.18),0_18px_36px_-30px_hsl(var(--foreground)/0.34)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 focus-visible:ring-offset-2 motion-reduce:transform-none motion-reduce:transition-none"
      onClick={onSelect}
    >
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] font-semibold leading-6 text-foreground">
          {title}
        </span>
        <span className="mt-1 block text-sm leading-6 text-muted-foreground">
          {body}
        </span>
        <span className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground/75">
          {meta.map((entry, index) => (
            <span key={entry} className="inline-flex items-center gap-2">
              {index > 0 ? (
                <span
                  aria-hidden="true"
                  className="h-0.5 w-0.5 rounded-full bg-current opacity-70"
                />
              ) : null}
              {entry}
            </span>
          ))}
        </span>
      </span>
      <ChevronRight
        className="h-4 w-4 shrink-0 text-muted-foreground/50 transition-all duration-200 group-hover:translate-x-0.5 group-hover:text-primary"
        aria-hidden="true"
      />
    </button>
  );
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
  historyImportJobId?: string | null;
  onHistoryImportUpdate: (job: HistoryImportJob | null) => void;
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
  historyImportJobId = null,
  onHistoryImportUpdate,
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
  const shouldReduceMotion = useReducedMotion() ?? false;
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
    <div className="space-y-8" data-testid="first-context-route-chooser">
      <div className="text-center">
        <p className={`${KICKER_CLASS} mb-2.5`}>{t("firstContext.kicker")}</p>
        <h3 ref={routeHeadingRef} tabIndex={-1} className={HEADING_CLASS}>
          {t("firstContext.title")}
        </h3>
        <p className={`${BODY_CLASS} mx-auto max-w-[520px]`}>
          {t("firstContext.body")}
        </p>
      </div>

      <div className="mx-auto grid w-full max-w-2xl grid-cols-1 gap-4">
        <RouteOptionCard
          testId="first-context-route-question"
          icon={<MessageCircleQuestion className="h-5 w-5" aria-hidden="true" />}
          title={t("firstContext.routes.question.title")}
          body={t("firstContext.routes.question.body")}
          meta={[
            t("firstContext.routes.optional"),
            t("firstContext.routes.question.meta"),
          ]}
          onSelect={() => onRouteChange("question")}
        />
        <RouteOptionCard
          testId="first-context-route-history"
          icon={<BookOpenText className="h-5 w-5" aria-hidden="true" />}
          title={t("firstContext.routes.history.title")}
          body={t("firstContext.routes.history.body")}
          meta={[
            t("firstContext.routes.optional"),
            t("firstContext.routes.history.meta"),
          ]}
          onSelect={() => onRouteChange("history")}
        />
        <RouteOptionCard
          testId="first-context-route-activity"
          icon={<Footprints className="h-5 w-5" aria-hidden="true" />}
          title={t("firstContext.routes.activity.title")}
          body={t("firstContext.routes.activity.body")}
          meta={[
            t("firstContext.routes.optional"),
            t("firstContext.routes.activity.meta"),
          ]}
          onSelect={() => onRouteChange("activity")}
        />
      </div>

      <p className="text-center text-xs leading-5 text-muted-foreground/75">
        {t("firstContext.routes.note")}
      </p>
    </div>
  );

  const renderHistoryRoute = () => (
    <div className="space-y-5" data-testid="first-context-history-route">
      <div>
        <div className="flex items-center gap-3">
          <p className={KICKER_CLASS}>{t("firstContext.history.kicker")}</p>
          <span className={BADGE_CLASS}>{t("firstContext.history.badge")}</span>
        </div>
        <h3
          ref={routeHeadingRef}
          tabIndex={-1}
          className={`${HEADING_CLASS} mt-2.5`}
        >
          {t("firstContext.history.title")}
        </h3>
        <p className={BODY_CLASS}>{t("firstContext.history.body")}</p>
      </div>
      <HistoryImportFlow
        initialJobId={historyImportJobId}
        onJobUpdate={onHistoryImportUpdate}
      />
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
      <div className="space-y-6" data-testid="first-context-question-route">
        <div>
          <div className="flex items-center gap-3">
            <p className={KICKER_CLASS}>{t("firstContext.story.kicker")}</p>
            <span className={BADGE_CLASS}>{t("firstContext.story.badge")}</span>
          </div>
          <h3
            ref={routeHeadingRef}
            tabIndex={-1}
            className={`${HEADING_CLASS} mt-2.5`}
          >
            {t("firstContext.story.title")}
          </h3>
          <p id={descriptionId} className={BODY_CLASS}>
            {t("firstContext.story.body")}
          </p>
        </div>

        <div className="rounded-2xl bg-muted/45 p-5 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.48)] sm:p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p
                id={questionDescriptionId}
                className="text-[15px] font-semibold leading-6 text-foreground"
                aria-live="polite"
                data-testid={`first-context-question-${questionId}`}
              >
                {t(`firstContext.story.questions.${questionId}`)}
              </p>
              <p className="mt-1.5 text-xs leading-5 text-muted-foreground">
                {t("firstContext.story.inputHint")}
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 shrink-0 rounded-full px-3 text-xs font-medium text-muted-foreground hover:text-foreground"
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
            rows={5}
            value={storyDraft}
            onChange={(event) => onStoryDraftChange(event.target.value)}
            placeholder={t(`firstContext.story.placeholders.${questionId}`)}
            disabled={storySubmitting || storyLocked}
            aria-invalid={Boolean(storyError)}
            aria-describedby={describedBy || undefined}
            className={`mt-4 min-h-[132px] w-full resize-y px-4 py-3 text-sm leading-6 disabled:cursor-not-allowed disabled:opacity-60 ${ONBOARDING_FIELD_CLASS}`}
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
          ) : (
            <p className="mt-2 text-right text-xs text-muted-foreground/70">
              {t("firstContext.story.shortHint")}
            </p>
          )}
        </div>

        <div className="rounded-lg bg-accent/40 px-4 py-3 text-xs leading-5 text-muted-foreground">
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
      <div>
        <div className="flex items-center gap-3">
          <p className={KICKER_CLASS}>{t("firstContext.activity.kicker")}</p>
          <span className={BADGE_CLASS}>{t("firstContext.activity.badge")}</span>
        </div>
        <h3
          ref={routeHeadingRef}
          tabIndex={-1}
          className={`${HEADING_CLASS} mt-2.5`}
        >
          {t("firstContext.activity.title")}
        </h3>
        <p className={BODY_CLASS}>{t("firstContext.activity.body")}</p>
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

      <p
        data-testid="first-context-scope-note"
        className="text-xs leading-5 text-muted-foreground"
      >
        {t("firstContext.scopeHint")}
      </p>

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

      <p className="text-xs leading-5 text-muted-foreground/75">
        {t("firstContext.note")}
      </p>
    </div>
  );

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <AnimatePresence initial={false} mode="popLayout">
        <motion.div
          key={route}
          initial={shouldReduceMotion ? false : { opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={shouldReduceMotion ? undefined : { opacity: 0, y: -6 }}
          transition={{
            duration: shouldReduceMotion ? 0 : 0.24,
            ease: [0.22, 1, 0.36, 1],
          }}
          data-testid="first-context-route-content"
          className={`mx-auto flex w-full flex-col px-4 py-6 sm:px-5 lg:px-6 ${
            route === "history" ? "mb-auto mt-0" : "my-auto"
          } ${
            route === "history"
              ? "max-w-none"
              : route === "activity"
              ? "max-w-[860px]"
              : route === "question"
                ? "max-w-[800px]"
                : "max-w-[840px]"
          }`}
        >
          {route === "choose"
            ? renderRouteChooser()
            : route === "question"
              ? renderQuestionRoute()
              : route === "history"
                ? renderHistoryRoute()
                : renderActivityRoute()}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

export default FirstContextStep;
