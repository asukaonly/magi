import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  FolderOpen,
  Loader2,
  RotateCcw,
  Users,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  historyImportsApi,
  type HistoryImportJob,
} from "@/api/modules/historyImports";
import { Button } from "@/components/ui/button";
import { pickDirectory, pickMarkdownFiles } from "@/runtime/desktop";

interface FirstContextHistoryImportProps {
  initialJobId?: string | null;
  onJobUpdate: (job: HistoryImportJob | null) => void;
}

const SELF_ALIASES = new Set([
  "user",
  "human",
  "me",
  "我",
  "本人",
  "自己",
]);

function errorReason(error: unknown): string {
  if (!error || typeof error !== "object") {
    return "unknown";
  }
  const candidate = error as {
    message?: unknown;
    details?: unknown;
    code?: unknown;
  };
  for (const value of [candidate.details, candidate.message, candidate.code]) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "unknown";
}

export function FirstContextHistoryImport({
  initialJobId = null,
  onJobUpdate,
}: FirstContextHistoryImportProps): JSX.Element {
  const { t, i18n } = useTranslation("onboarding");
  const [job, setJob] = useState<HistoryImportJob | null>(null);
  const [loading, setLoading] = useState(Boolean(initialJobId));
  const [action, setAction] = useState<
    "preview" | "confirm" | "resume" | "delete" | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedParticipants, setSelectedParticipants] = useState<string[]>([]);
  const [personalWritingConfirmed, setPersonalWritingConfirmed] = useState(false);
  const onJobUpdateRef = useRef(onJobUpdate);
  onJobUpdateRef.current = onJobUpdate;

  const applyJob = useCallback(
    (nextJob: HistoryImportJob): void => {
      setJob(nextJob);
      setSelectedParticipants((current) => {
        if (current.length > 0) {
          return current;
        }
        const saved = nextJob.self_participants.filter(
          (name) =>
            !nextJob.participants.find(
              (participant) =>
                participant.name === name && participant.is_document_author,
            ),
        );
        if (saved.length > 0) {
          return saved;
        }
        return nextJob.participants
          .filter(
            (participant) =>
              !participant.is_document_author &&
              SELF_ALIASES.has(participant.name.trim().toLocaleLowerCase()),
          )
          .map((participant) => participant.name);
      });
      if (
        nextJob.self_participants.some((name) =>
          nextJob.participants.some(
            (participant) =>
              participant.name === name && participant.is_document_author,
          ),
        )
      ) {
        setPersonalWritingConfirmed(true);
      }
      onJobUpdateRef.current(nextJob);
    },
    [],
  );

  useEffect(() => {
    if (!initialJobId || job?.job_id === initialJobId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    historyImportsApi
      .get(initialJobId)
      .then((loaded) => {
        if (!cancelled) {
          applyJob(loaded);
        }
      })
      .catch((loadError) => {
        if (!cancelled) {
          setError(errorReason(loadError));
          onJobUpdateRef.current(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [applyJob, initialJobId, job?.job_id]);

  useEffect(() => {
    if (!job || !["ready", "running"].includes(job.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      historyImportsApi
        .get(job.job_id)
        .then(applyJob)
        .catch(() => {
          // Keep the last confirmed progress visible; manual retry remains available.
        });
    }, 1200);
    return () => window.clearInterval(timer);
  }, [applyJob, job]);

  const previewPaths = async (paths: string[]): Promise<void> => {
    if (paths.length === 0) {
      return;
    }
    setAction("preview");
    setError(null);
    try {
      applyJob(await historyImportsApi.previewMarkdown(paths));
    } catch (previewError) {
      setError(errorReason(previewError));
    } finally {
      setAction(null);
    }
  };

  const chooseFiles = async (): Promise<void> => {
    await previewPaths(await pickMarkdownFiles());
  };

  const chooseFolder = async (): Promise<void> => {
    const folder = await pickDirectory();
    if (folder) {
      await previewPaths([folder]);
    }
  };

  const toggleParticipant = (name: string): void => {
    setSelectedParticipants((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : [...current, name],
    );
  };

  const requiresChatIdentity =
    job?.detected_kind === "chat" || job?.detected_kind === "mixed";
  const requiresWritingConfirmation =
    job?.detected_kind === "document" || job?.detected_kind === "mixed";
  const canConfirm = Boolean(
    job &&
      (!requiresChatIdentity || selectedParticipants.length > 0) &&
      (!requiresWritingConfirmation || personalWritingConfirmed),
  );

  const confirmImport = async (): Promise<void> => {
    if (!job || !canConfirm) {
      return;
    }
    setAction("confirm");
    setError(null);
    try {
      applyJob(
        await historyImportsApi.confirm(job.job_id, {
          selfParticipants: selectedParticipants,
          confirmPersonalWriting: personalWritingConfirmed,
        }),
      );
    } catch (confirmError) {
      setError(errorReason(confirmError));
    } finally {
      setAction(null);
    }
  };

  const resumeImport = async (): Promise<void> => {
    if (!job) {
      return;
    }
    setAction("resume");
    setError(null);
    try {
      applyJob(await historyImportsApi.resume(job.job_id));
    } catch (resumeError) {
      setError(errorReason(resumeError));
    } finally {
      setAction(null);
    }
  };

  const chooseAgain = async (): Promise<void> => {
    if (!job) {
      return;
    }
    setAction("delete");
    setError(null);
    try {
      await historyImportsApi.delete(job.job_id);
      setJob(null);
      setSelectedParticipants([]);
      setPersonalWritingConfirmed(false);
      onJobUpdateRef.current(null);
    } catch (deleteError) {
      setError(errorReason(deleteError));
    } finally {
      setAction(null);
    }
  };

  const chatParticipants = useMemo(
    () => job?.participants.filter((participant) => !participant.is_document_author) ?? [],
    [job],
  );
  const progress = job
    ? Math.min(100, Math.round((job.imported_count / Math.max(job.total_records, 1)) * 100))
    : 0;
  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(i18n.resolvedLanguage ?? i18n.language, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }),
    [i18n.language, i18n.resolvedLanguage],
  );
  const translatedError = error
    ? t(`firstContext.history.errors.${error}`, {
        defaultValue: t("firstContext.history.errors.unknown"),
      })
    : null;

  if (loading) {
    return (
      <div
        role="status"
        className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground"
      >
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        {t("firstContext.history.loading")}
      </div>
    );
  }

  if (!job) {
    return (
      <div className="space-y-4" data-testid="history-import-empty">
        <div className="rounded-2xl bg-muted/35 p-5 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.5)] sm:p-6">
          <div className="flex items-start gap-4">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <FileText className="h-5 w-5" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <h4 className="text-[15px] font-semibold leading-6 text-foreground">
                {t("firstContext.history.picker.title")}
              </h4>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                {t("firstContext.history.picker.body")}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  type="button"
                  onClick={() => void chooseFiles()}
                  disabled={action !== null}
                >
                  {action === "preview" ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <FileText className="h-4 w-4" aria-hidden="true" />
                  )}
                  {t("firstContext.history.picker.files")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void chooseFolder()}
                  disabled={action !== null}
                >
                  <FolderOpen className="h-4 w-4" aria-hidden="true" />
                  {t("firstContext.history.picker.folder")}
                </Button>
              </div>
            </div>
          </div>
        </div>
        <p className="text-xs leading-5 text-muted-foreground/80">
          {t("firstContext.history.picker.note")}
        </p>
        {translatedError ? (
          <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            {translatedError}
          </p>
        ) : null}
      </div>
    );
  }

  if (job.quick_ready) {
    const complete = job.status === "completed";
    const failed = job.status === "failed";
    return (
      <div className="space-y-5" data-testid="history-import-ready">
        <div className="rounded-2xl border border-primary/15 bg-primary/[0.045] p-5 sm:p-6">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <h4 className="text-[15px] font-semibold text-foreground">
                {t("firstContext.history.ready.title", {
                  count: job.quick_imported_count,
                })}
              </h4>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                {complete
                  ? t("firstContext.history.ready.completed")
                  : failed
                    ? t("firstContext.history.ready.failed")
                    : t("firstContext.history.ready.background")}
              </p>
              <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-primary/10">
                <div
                  className="h-full rounded-full bg-primary transition-[width] duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {t("firstContext.history.ready.progress", {
                  imported: job.imported_count,
                  total: job.total_records,
                })}
              </p>
            </div>
          </div>
        </div>
        {failed ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => void resumeImport()}
            disabled={action !== null}
          >
            {action === "resume" ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
            )}
            {t("firstContext.history.ready.retry")}
          </Button>
        ) : null}
        {translatedError ? (
          <p role="alert" className="text-sm text-destructive">
            {translatedError}
          </p>
        ) : null}
        <p className="text-xs leading-5 text-muted-foreground/80">
          {t("firstContext.history.ready.note")}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5" data-testid="history-import-preview">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
        <span>{t("firstContext.history.preview.files", { count: job.source_files.length })}</span>
        <span aria-hidden="true">·</span>
        <span>{t("firstContext.history.preview.records", { count: job.total_records })}</span>
        <span aria-hidden="true">·</span>
        <span>{t(`firstContext.history.preview.kind.${job.detected_kind}`)}</span>
      </div>

      {requiresChatIdentity ? (
        <section className="rounded-xl border border-border/70 bg-card p-4">
          <div className="flex items-start gap-3">
            <Users className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <h4 className="text-sm font-semibold text-foreground">
                {t("firstContext.history.identity.title")}
              </h4>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {t("firstContext.history.identity.body")}
              </p>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {chatParticipants.map((participant) => (
                  <label
                    key={participant.name}
                    className="flex cursor-pointer items-start gap-3 rounded-lg border border-border/60 px-3 py-2.5 transition-colors hover:bg-accent/45"
                  >
                    <input
                      type="checkbox"
                      className="mt-1 h-4 w-4 rounded border-border accent-primary"
                      checked={selectedParticipants.includes(participant.name)}
                      onChange={() => toggleParticipant(participant.name)}
                    />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-foreground">
                        {participant.name}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                        {t("firstContext.history.identity.messageCount", {
                          count: participant.message_count,
                        })}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {requiresWritingConfirmation ? (
        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-border/70 bg-card p-4">
          <input
            type="checkbox"
            className="mt-1 h-4 w-4 rounded border-border accent-primary"
            checked={personalWritingConfirmed}
            onChange={(event) => setPersonalWritingConfirmed(event.target.checked)}
          />
          <span>
            <span className="block text-sm font-semibold text-foreground">
              {t("firstContext.history.writing.title")}
            </span>
            <span className="mt-1 block text-xs leading-5 text-muted-foreground">
              {t("firstContext.history.writing.body")}
            </span>
          </span>
        </label>
      ) : null}

      <section className="overflow-hidden rounded-xl border border-border/70 bg-card">
        <div className="border-b border-border/60 px-4 py-3 text-xs font-medium text-muted-foreground">
          {t("firstContext.history.preview.sample")}
        </div>
        <div className="divide-y divide-border/50">
          {job.preview_records.slice(0, 4).map((record) => (
            <div
              key={`${record.session_id}:${record.session_seq}`}
              className="px-4 py-3"
            >
              <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                <span className="font-medium text-foreground/80">
                  {record.is_document_author
                    ? record.source_name
                    : record.speaker_name}
                </span>
                <span>
                  {record.timestamp_confidence === "explicit"
                    ? dateFormatter.format(new Date(record.event_at * 1000))
                    : t("firstContext.history.preview.sourceOrder")}
                </span>
              </div>
              <p className="mt-1.5 line-clamp-2 text-sm leading-6 text-foreground/85">
                {record.content}
              </p>
            </div>
          ))}
        </div>
      </section>

      {job.warnings.length > 0 ? (
        <div className="space-y-1 rounded-lg bg-amber-50/80 px-3.5 py-3 text-xs leading-5 text-amber-900 dark:bg-amber-950/25 dark:text-amber-200">
          {job.warnings.map((warning) => (
            <p key={warning}>
              {t(`firstContext.history.warnings.${warning}`)}
            </p>
          ))}
        </div>
      ) : null}

      {translatedError ? (
        <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {translatedError}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button
          type="button"
          variant="ghost"
          onClick={() => void chooseAgain()}
          disabled={action !== null}
        >
          {action === "delete" ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
          )}
          {t("firstContext.history.preview.chooseAgain")}
        </Button>
        <Button
          type="button"
          size="lg"
          onClick={() => void confirmImport()}
          disabled={!canConfirm || action !== null}
        >
          {action === "confirm" ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
          )}
          {action === "confirm"
            ? t("firstContext.history.preview.importing")
            : t("firstContext.history.preview.confirm")}
        </Button>
      </div>
    </div>
  );
}

export default FirstContextHistoryImport;
