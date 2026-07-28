import type { RefObject } from "react";
import { ExternalLink, Loader2, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import type { PersonalityConfig } from "../../../api/modules/personas";
import { PersonaPreviewStarterChips } from "../PersonaPreviewStarterChips";
import { PersonaProfilePanel } from "../PersonaProfilePanel";
import {
  referenceSummary,
  type CustomPersonaDraft,
  type PresetProfileState,
  type RailItem,
} from "./personaPreviewModel";
import type { PersonaPreviewConversationController } from "./usePersonaPreviewConversation";
import { TypingDots } from "./PersonaPreviewPrimitives";

interface PersonaPreviewDetailProps {
  item?: RailItem;
  mode: "chat" | "profile";
  profileConfig?: PersonalityConfig;
  profileState?: PresetProfileState;
  shouldReduceMotion: boolean;
  transcriptScrollRef: RefObject<HTMLDivElement>;
  conversation: PersonaPreviewConversationController;
  onRetryProfile: () => void;
  onEditReference: (
    draft: CustomPersonaDraft,
    forceResearchRefresh?: boolean,
  ) => void;
}

export function PersonaPreviewDetail({
  item,
  mode,
  profileConfig,
  profileState,
  shouldReduceMotion,
  transcriptScrollRef,
  conversation,
  onRetryProfile,
  onEditReference,
}: PersonaPreviewDetailProps): JSX.Element {
  const { t } = useTranslation("onboarding");
  const {
    activeTranscript,
    draft,
    busy,
    adjustmentDraft,
    adjusting,
    adjustmentError,
    capReached,
    setDraft,
    setAdjustmentDraft,
    send,
    adjustActivePersona,
  } = conversation;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {item?.customDraft?.intent?.reference ? (
        <div className="space-y-2">
          <div
            data-testid="persona-reference-summary"
            className="flex items-center justify-between gap-3 rounded-lg border border-border/55 bg-muted/25 px-3 py-2"
          >
            <div className="min-w-0">
              <div className="text-xs text-muted-foreground">
                {t("personaPreview.reference.currentReference")}
              </div>
              <div className="truncate text-sm font-medium text-foreground">
                {referenceSummary(item.customDraft.intent)}
              </div>
            </div>
            <button
              type="button"
              data-testid="persona-reference-edit"
              onClick={() => onEditReference(item.customDraft!)}
              className="shrink-0 rounded-md px-2.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10"
            >
              {t("personaPreview.reference.edit")}
            </button>
          </div>
          <details
            data-testid="persona-reference-sources"
            className="rounded-lg border border-border/45 bg-background/60 px-3 py-2"
          >
            <summary className="cursor-pointer list-none text-xs text-muted-foreground">
              {item.customDraft.referenceDossier?.grounding_status ===
              "verified"
                ? t("personaPreview.reference.sourcesVerified", {
                    count:
                      item.customDraft.referenceDossier.sources.length,
                  })
                : item.customDraft.referenceDossier?.grounding_status ===
                    "unavailable"
                  ? t("personaPreview.reference.sourcesUnavailable")
                  : item.customDraft.referenceDossier
                        ?.grounding_status === "insufficient"
                    ? t("personaPreview.reference.sourcesInsufficient")
                    : t("personaPreview.reference.sourcesUnverified")}
            </summary>
            <div className="mt-2 space-y-2 border-t border-border/40 pt-2">
              {item.customDraft.referenceDossier?.sources.map(
                (source) => (
                  <a
                    key={source.source_id}
                    href={source.url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-start justify-between gap-3 rounded-md px-2 py-1.5 text-xs hover:bg-muted/55"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-foreground">
                        {source.title || source.domain}
                      </span>
                      <span className="block truncate text-muted-foreground">
                        {source.domain}
                      </span>
                    </span>
                    <ExternalLink
                      className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                  </a>
                ),
              )}
              {item.customDraft.referenceDossier?.warning ? (
                <p className="px-2 text-xs leading-5 text-muted-foreground">
                  {item.customDraft.referenceDossier.warning}
                </p>
              ) : null}
              <button
                type="button"
                data-testid="persona-reference-refresh"
                onClick={() =>
                  onEditReference(item.customDraft!, true)
                }
                className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-primary hover:bg-primary/10"
              >
                <RefreshCw
                  className="h-3.5 w-3.5"
                  aria-hidden="true"
                />
                {t("personaPreview.reference.refreshSources")}
              </button>
            </div>
          </details>
        </div>
      ) : null}

      {mode === "profile" ? (
        profileConfig ? (
          <PersonaProfilePanel
            key={item?.slug}
            config={profileConfig}
          />
        ) : profileState?.status === "error" ? (
          <div
            data-testid="persona-profile-error"
            role="alert"
            className="flex flex-1 flex-col items-center justify-center rounded-lg border border-border/55 bg-background px-6 text-center"
          >
            <p className="text-sm text-muted-foreground">
              {t("personaPreview.profileLoadFailed", {
                name: item?.name || "",
              })}
            </p>
            <button
              type="button"
              className="mt-3 rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
              onClick={onRetryProfile}
            >
              {t("personaPreview.profileRetry")}
            </button>
          </div>
        ) : (
          <div
            data-testid="persona-profile-loading"
            role="status"
            className="flex flex-1 flex-col items-center justify-center rounded-lg border border-border/55 bg-background px-6 text-center"
          >
            <Loader2
              className={cn(
                "h-5 w-5 text-primary",
                !shouldReduceMotion && "animate-spin",
              )}
              aria-hidden="true"
            />
            <p className="mt-3 text-sm text-muted-foreground">
              {t("personaPreview.profileLoading", {
                name: item?.name || "",
              })}
            </p>
          </div>
        )
      ) : (
        <>
          <div
            ref={transcriptScrollRef}
            className="flex-1 overflow-y-auto rounded-xl bg-muted/40 p-4"
          >
            {activeTranscript.length === 0 ? (
              <div className="flex h-full items-center justify-center">
                <p className="max-w-sm text-center text-sm leading-6 text-muted-foreground">
                  {t("personaPreview.emptyHint")}
                </p>
              </div>
            ) : null}
            {activeTranscript.map((turn, index) =>
              turn.kind === "revision-divider" ? (
                <div
                  key={turn.id || `divider-${index}`}
                  data-testid="persona-adjustment-divider"
                  className="my-4 flex items-center gap-3 text-xs text-muted-foreground"
                >
                  <span className="h-px flex-1 bg-border" />
                  <span>
                    {t("personaPreview.adjustment.reanswered")}
                  </span>
                  <span className="h-px flex-1 bg-border" />
                </div>
              ) : (
                <div
                  key={turn.id || index}
                  className={`mb-2 flex ${
                    turn.role === "user"
                      ? "justify-end"
                      : "justify-start"
                  }`}
                >
                  <span
                    data-testid={
                      turn.role === "assistant"
                        ? "persona-preview-assistant-bubble"
                        : "persona-preview-user-bubble"
                    }
                    className={`inline-block max-w-[80%] whitespace-pre-wrap border border-border/55 bg-card px-4 py-2.5 text-sm text-foreground shadow-sm ${
                      turn.role === "user"
                        ? "rounded-xl rounded-tr-sm"
                        : "rounded-xl rounded-tl-sm"
                    } ${turn.superseded ? "opacity-55" : ""}`}
                  >
                    {turn.role === "assistant" &&
                    turn.content === "" ? (
                      <TypingDots
                        shouldReduceMotion={shouldReduceMotion}
                        label={t("personaPreview.waiting")}
                      />
                    ) : (
                      turn.content
                    )}
                  </span>
                </div>
              ),
            )}
          </div>

          <PersonaPreviewStarterChips onPick={setDraft} />

          {item?.customDraft ? (
            <div
              data-testid="persona-adjustment-panel"
              className="rounded-lg border border-border/55 bg-muted/20 p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-sm font-medium text-foreground">
                    {t("personaPreview.adjustment.title")}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {t("personaPreview.adjustment.hint")}
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {(
                    [
                      "shorter",
                      "lessPerformative",
                      "moreNatural",
                    ] as const
                  ).map((key) => (
                    <button
                      key={key}
                      type="button"
                      disabled={adjusting}
                      onClick={() =>
                        setAdjustmentDraft(
                          t(
                            `personaPreview.adjustment.quick.${key}`,
                          ),
                        )
                      }
                      className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
                    >
                      {t(
                        `personaPreview.adjustment.quick.${key}`,
                      )}
                    </button>
                  ))}
                </div>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <input
                  data-testid="persona-adjustment-input"
                  value={adjustmentDraft}
                  disabled={adjusting}
                  onChange={(event) =>
                    setAdjustmentDraft(event.target.value)
                  }
                  onKeyDown={(event) => {
                    if (
                      event.key === "Enter" &&
                      !event.shiftKey
                    ) {
                      event.preventDefault();
                      void adjustActivePersona();
                    }
                  }}
                  placeholder={t(
                    "personaPreview.adjustment.placeholder",
                  )}
                  className="min-w-0 flex-1 rounded-md border border-border/55 bg-background px-3 py-2 text-sm text-foreground outline-none transition-[border-color,box-shadow] duration-200 placeholder:text-muted-foreground/60 focus-visible:border-primary/45 focus-visible:ring-2 focus-visible:ring-primary/15"
                />
                <button
                  type="button"
                  data-testid="persona-adjustment-submit"
                  disabled={
                    !adjustmentDraft.trim() || adjusting || busy
                  }
                  onClick={() => void adjustActivePersona()}
                  className="rounded-md border border-primary/40 px-3 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary/10 disabled:opacity-50"
                >
                  {adjusting
                    ? t("personaPreview.adjustment.adjusting")
                    : t("personaPreview.adjustment.submit")}
                </button>
              </div>
              {adjustmentError ? (
                <p
                  className="mt-2 text-xs text-destructive"
                  role="alert"
                >
                  {adjustmentError}
                </p>
              ) : null}
            </div>
          ) : null}

          <div className="flex items-center gap-2">
            <input
              type="text"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={t(
                "personaPreview.composerPlaceholder",
              )}
              disabled={adjusting || capReached}
              className="flex-1 rounded-md border border-border/55 bg-background px-3 py-2 text-sm text-foreground outline-none transition-[border-color,box-shadow] duration-200 focus-visible:border-primary/45 focus-visible:ring-2 focus-visible:ring-primary/15"
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            <button
              type="button"
              onClick={() => void send()}
              disabled={
                !draft.trim() || busy || adjusting || capReached
              }
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
            >
              {t("personaPreview.send")}
            </button>
          </div>

          {capReached ? (
            <p className="text-xs text-muted-foreground">
              {t("personaPreview.capReached")}
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
