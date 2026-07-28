import { AnimatePresence, motion } from "framer-motion";
import { ExternalLink, PencilLine } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { ONBOARDING_FIELD_MUTED_CLASS } from "../onboardingStyles";
import { PersonaReferenceEditor } from "../PersonaReferenceEditor";
import { referenceUrlsAreValid } from "./personaPreviewModel";
import type { PersonaGenerationController } from "./usePersonaGenerationController";
import { GenerationStageStatusIcon } from "./PersonaPreviewPrimitives";

interface PersonaCreationPanelProps {
  controller: PersonaGenerationController;
  shouldReduceMotion: boolean;
  onCancel: () => void;
}

export function PersonaCreationPanel({
  controller,
  shouldReduceMotion,
  onCancel,
}: PersonaCreationPanelProps): JSX.Element {
  const { t } = useTranslation("onboarding");
  const {
    creationDraft,
    descriptionExpanded,
    stages,
    error,
    compatibilityRetry,
    enablingCompatibility,
    generating,
    creationNeedsConfirmation,
    setDescriptionExpanded,
    editDescription,
    updateReference,
    updateFidelityLevel,
    updateConstraintsText,
    updateResearchPreference,
    updateReferenceUrlsText,
    handleResolveOrGenerate,
    enableCompatibilityAndRetry,
  } = controller;
  const showDescriptionSummary =
    Boolean(creationDraft?.resolution) && creationNeedsConfirmation;
  const showDescriptionEditor =
    !showDescriptionSummary || descriptionExpanded;
  const referenceValid =
    !creationNeedsConfirmation ||
    (creationDraft !== null &&
      creationDraft.referenceConfirmed &&
      (creationDraft.reference.sourceKind === "original" ||
        Boolean(creationDraft.reference.name.trim())) &&
      (creationDraft.reference.sourceKind === "original" ||
        creationDraft.reference.sourceKind ===
          "private_person_reference" ||
        creationDraft.researchPreference === "disabled" ||
        referenceUrlsAreValid(creationDraft.referenceUrlsText)));
  const buttonLabel =
    creationDraft?.phase === "resolving"
      ? t("personaPreview.reference.resolving")
      : creationDraft?.phase === "verifying"
        ? t("personaPreview.reference.verifying")
        : creationDraft?.phase === "generating"
          ? t("personaPreview.generating")
          : creationNeedsConfirmation
            ? t("personaPreview.reference.confirmAndGenerate")
            : t("personaPreview.generate");

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <motion.div
        layout
        className="flex-1 overflow-y-auto px-1 py-1 sm:px-4 sm:py-3 lg:px-7"
      >
        <AnimatePresence initial={false} mode="popLayout">
          {showDescriptionSummary && !descriptionExpanded ? (
            <motion.div
              layout
              key="description-summary"
              data-testid="persona-custom-description-summary"
              initial={
                shouldReduceMotion ? false : { opacity: 0, y: -8 }
              }
              animate={{ opacity: 1, y: 0 }}
              exit={
                shouldReduceMotion
                  ? undefined
                  : { opacity: 0, y: -5 }
              }
              transition={{
                duration: shouldReduceMotion ? 0 : 0.24,
                ease: [0.22, 1, 0.36, 1],
              }}
              className="flex items-center justify-between gap-4 rounded-lg bg-accent/75 px-4 py-3 shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.12)]"
            >
              <p className="min-w-0 truncate text-sm font-semibold text-foreground">
                {creationDraft?.description}
              </p>
              <button
                type="button"
                data-testid="persona-custom-description-edit"
                onClick={() => setDescriptionExpanded(true)}
                className="group flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-muted-foreground transition-colors duration-200 hover:bg-background/65 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/15 motion-reduce:transition-none"
              >
                <PencilLine
                  className="h-3.5 w-3.5"
                  aria-hidden="true"
                />
                {t("personaPreview.reference.edit")}
              </button>
            </motion.div>
          ) : null}
        </AnimatePresence>

        <motion.div
          layout
          aria-hidden={!showDescriptionEditor}
          className={cn(
            "grid transition-[grid-template-rows,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none",
            showDescriptionEditor
              ? "grid-rows-[1fr] opacity-100"
              : "pointer-events-none grid-rows-[0fr] opacity-0",
          )}
        >
          <div className="min-h-0 overflow-hidden">
            <div>
              {!showDescriptionSummary ? (
                <>
                  <h3 className="text-base font-semibold tracking-[-0.01em] text-foreground">
                    {t("personaPreview.createCustomTitle")}
                  </h3>
                  <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted-foreground">
                    {t("personaPreview.createCustomHint")}
                  </p>
                </>
              ) : null}
              <textarea
                data-testid="persona-custom-description"
                value={creationDraft?.description || ""}
                onChange={(event) =>
                  editDescription(event.target.value)
                }
                placeholder={t(
                  "personaPreview.customDescriptionPlaceholder",
                )}
                disabled={generating || !showDescriptionEditor}
                tabIndex={showDescriptionEditor ? undefined : -1}
                rows={2}
                className={cn(
                  "w-full resize-none rounded-lg px-4 py-3 text-base leading-7 disabled:opacity-70",
                  ONBOARDING_FIELD_MUTED_CLASS,
                  !showDescriptionSummary && "mt-4",
                )}
              />
            </div>
          </div>
        </motion.div>

        <AnimatePresence initial={false}>
          {creationDraft?.resolution && creationNeedsConfirmation ? (
            <motion.div
              layout
              key="persona-reference-editor"
              initial={
                shouldReduceMotion ? false : { opacity: 0, y: 12 }
              }
              animate={{ opacity: 1, y: 0 }}
              exit={
                shouldReduceMotion
                  ? undefined
                  : { opacity: 0, y: 8 }
              }
              transition={{
                duration: shouldReduceMotion ? 0 : 0.28,
                ease: [0.22, 1, 0.36, 1],
              }}
            >
              <PersonaReferenceEditor
                resolution={creationDraft.resolution}
                value={creationDraft.reference}
                fidelityLevel={creationDraft.fidelityLevel}
                constraintsText={creationDraft.constraintsText}
                researchPreference={creationDraft.researchPreference}
                referenceUrlsText={creationDraft.referenceUrlsText}
                referenceUrlsValid={referenceUrlsAreValid(
                  creationDraft.referenceUrlsText,
                )}
                disabled={generating}
                onChange={updateReference}
                onFidelityLevelChange={updateFidelityLevel}
                onConstraintsTextChange={updateConstraintsText}
                onResearchPreferenceChange={updateResearchPreference}
                onReferenceUrlsTextChange={updateReferenceUrlsText}
              />
              {creationDraft.verificationSources.length > 0 ? (
                <details
                  data-testid="persona-reference-verification-sources"
                  className="mt-4 rounded-lg border border-border/45 bg-muted/20 px-3 py-2"
                >
                  <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                    {t(
                      "personaPreview.reference.verificationSources",
                      {
                        count:
                          creationDraft.verificationSources.length,
                      },
                    )}
                  </summary>
                  <div className="mt-2 space-y-1 border-t border-border/40 pt-2">
                    {creationDraft.verificationSources.map(
                      (source) => (
                        <a
                          key={source.source_id}
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-xs hover:bg-background"
                        >
                          <span className="truncate">
                            {source.title || source.domain}
                          </span>
                          <ExternalLink
                            className="h-3.5 w-3.5 shrink-0"
                            aria-hidden="true"
                          />
                        </a>
                      ),
                    )}
                  </div>
                </details>
              ) : null}
            </motion.div>
          ) : null}
        </AnimatePresence>

        {generating ? (
          <div
            data-testid="persona-generation-progress"
            role="status"
            aria-live="polite"
            className="mt-4 overflow-hidden rounded-lg border border-border/45 bg-muted/30 p-4"
          >
            <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <span
                className={cn(
                  "h-2 w-2 rounded-full bg-primary",
                  !shouldReduceMotion && "animate-pulse",
                )}
                aria-hidden="true"
              />
              <span>
                {creationDraft?.phase === "resolving"
                  ? t("personaPreview.reference.resolving")
                  : creationDraft?.phase === "verifying"
                    ? t("personaPreview.reference.verifying")
                    : t("personaPreview.generating")}
              </span>
            </div>
            {stages.length > 0 ? (
              <ul className="mt-3 space-y-1.5">
                {stages.map((stage) => {
                  const isRunning = stage.status === "running";
                  const isCompleted = stage.status === "completed";
                  return (
                    <li
                      key={stage.stage_id}
                      data-testid={
                        isRunning
                          ? "persona-generation-stage-running"
                          : undefined
                      }
                      aria-current={isRunning ? "step" : undefined}
                      className={cn(
                        "flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors duration-300",
                        isRunning &&
                          "bg-background/80 text-foreground shadow-sm",
                        isCompleted && "text-foreground/80",
                        !isRunning &&
                          !isCompleted &&
                          "text-muted-foreground/70",
                      )}
                    >
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                        <GenerationStageStatusIcon
                          status={stage.status}
                          shouldReduceMotion={shouldReduceMotion}
                        />
                      </span>
                      <span
                        className={cn(isRunning && "font-medium")}
                      >
                        {t(
                          `personaPreview.generationStages.${stage.stage_id}`,
                          {
                            defaultValue:
                              stage.label || stage.stage_id,
                          },
                        )}
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </div>
        ) : null}

        {compatibilityRetry ? (
          <div
            className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-500/35 bg-amber-500/10 px-3 py-2.5"
            role="alert"
            data-testid="persona-fake-ip-compatibility"
          >
            <div className="min-w-0 flex-1">
              <div className="text-xs font-medium text-foreground">
                {t("settings.fakeIpCompatibilityPromptTitle", {
                  ns: "app",
                })}
              </div>
              <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                {error ||
                  t("settings.fakeIpCompatibilityPromptDesc", {
                    ns: "app",
                  })}
              </div>
            </div>
            <button
              type="button"
              onClick={() => void enableCompatibilityAndRetry()}
              disabled={enablingCompatibility}
              className="shrink-0 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
            >
              {enablingCompatibility
                ? t("settings.fakeIpCompatibilityEnabling", {
                    ns: "app",
                  })
                : t("settings.fakeIpCompatibilityEnableRetry", {
                    ns: "app",
                  })}
            </button>
          </div>
        ) : error ? (
          <p className="mt-3 text-xs text-destructive" role="alert">
            {error}
          </p>
        ) : null}
      </motion.div>

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={generating}
          className="rounded-md px-4 py-2 text-sm text-muted-foreground transition-colors duration-200 hover:bg-muted/70 hover:text-foreground disabled:opacity-50 motion-reduce:transition-none"
        >
          {t("personaPreview.cancelCreate")}
        </button>
        <button
          type="button"
          data-testid="persona-custom-generate"
          onClick={() => void handleResolveOrGenerate()}
          aria-busy={generating}
          disabled={
            !creationDraft?.description.trim() ||
            generating ||
            !referenceValid
          }
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
        >
          {buttonLabel}
        </button>
      </div>
    </div>
  );
}
