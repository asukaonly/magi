import { useCallback, useEffect, useMemo, useState } from "react";
import {
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  historyImportsApi,
  type HistoryImportJob,
} from "@/api/modules/historyImports";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import HistoryImportFlow from "./HistoryImportFlow";

const ACTIVE_IMPORT_STATUSES = new Set(["ready", "running"]);

function jobProgress(job: HistoryImportJob): number {
  return Math.min(
    100,
    Math.round((job.imported_count / Math.max(job.total_records, 1)) * 100),
  );
}

function jobLabel(job: HistoryImportJob, fallback: string): string {
  const first = job.included_files[0] || job.source_files[0];
  if (!first) {
    return fallback;
  }
  return job.included_files.length > 1
    ? `${first} +${job.included_files.length - 1}`
    : first;
}

export default function HistoryImportsSection(): JSX.Element {
  const { t, i18n } = useTranslation("app");
  const [jobs, setJobs] = useState<HistoryImportJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<HistoryImportJob | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);

  const loadJobs = useCallback(async (): Promise<void> => {
    try {
      const nextJobs = await historyImportsApi.list();
      setJobs(nextJobs);
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  const activeKey = useMemo(
    () =>
      jobs
        .filter((job) => ACTIVE_IMPORT_STATUSES.has(job.status))
        .map((job) => `${job.job_id}:${job.updated_at}`)
        .join("|"),
    [jobs],
  );

  useEffect(() => {
    if (!activeKey) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      void loadJobs();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [activeKey, loadJobs]);

  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(i18n.resolvedLanguage ?? i18n.language, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }),
    [i18n.language, i18n.resolvedLanguage],
  );

  const updateJob = (job: HistoryImportJob | null): void => {
    if (!job) {
      void loadJobs();
      return;
    }
    setJobs((current) => {
      const withoutJob = current.filter((item) => item.job_id !== job.job_id);
      return [job, ...withoutJob].sort((left, right) => right.created_at - left.created_at);
    });
  };

  const retryJob = async (jobId: string): Promise<void> => {
    setRetryingJobId(jobId);
    try {
      updateJob(await historyImportsApi.resume(jobId));
    } catch {
      toast.error(t("memory.sourcesPage.historyImports.continueFailed"));
    } finally {
      setRetryingJobId(null);
    }
  };

  const deleteJob = async (): Promise<void> => {
    if (!deleteTarget) {
      return;
    }
    setDeleting(true);
    try {
      await historyImportsApi.delete(deleteTarget.job_id);
      setJobs((current) =>
        current.filter((job) => job.job_id !== deleteTarget.job_id),
      );
      setDeleteTarget(null);
    } catch {
      toast.error(t("memory.sourcesPage.historyImports.deleteFailed"));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      <section
        data-testid="history-imports-section"
        className="rounded-mem-lg bg-[hsl(var(--memory-panel-elevated)/0.38)] px-5 py-4 sm:px-6"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-base font-semibold tracking-[-0.01em] text-[hsl(var(--memory-title))]">
              {t("memory.sourcesPage.historyImports.title")}
            </h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-[hsl(var(--memory-muted))]">
              {t("memory.sourcesPage.historyImports.body")}
            </p>
          </div>
          <Button
            type="button"
            variant={creating ? "ghost" : "secondary"}
            size="sm"
            className="h-8 rounded-lg px-3 text-xs"
            onClick={() => setCreating((current) => !current)}
          >
            {creating ? (
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {creating
              ? t("memory.sourcesPage.historyImports.close")
              : t("memory.sourcesPage.historyImports.add")}
          </Button>
        </div>

        {creating ? (
          <div className="mt-4 border-t border-[hsl(var(--memory-border)/0.58)] pt-5">
            <HistoryImportFlow onJobUpdate={updateJob} />
          </div>
        ) : null}

        {!creating ? (
          <div className="mt-3">
            {loading ? (
              <div
                role="status"
                className="flex min-h-12 items-center gap-2 text-xs text-[hsl(var(--memory-muted))]"
              >
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                {t("memory.sourcesPage.historyImports.loading")}
              </div>
            ) : error ? (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-[hsl(var(--memory-panel-subtle)/0.52)] px-4 py-3 text-sm text-[hsl(var(--memory-body))]">
                <span>{t("memory.sourcesPage.historyImports.error")}</span>
                <Button type="button" variant="ghost" size="sm" onClick={() => void loadJobs()}>
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                  {t("memory.sourcesPage.historyImports.retry")}
                </Button>
              </div>
            ) : jobs.length === 0 ? (
              <div className="border-t border-[hsl(var(--memory-border)/0.48)] pt-3 text-xs leading-5 text-[hsl(var(--memory-muted))]">
                {t("memory.sourcesPage.historyImports.empty")}
              </div>
            ) : (
              <div className="divide-y divide-[hsl(var(--memory-border)/0.48)] border-t border-[hsl(var(--memory-border)/0.48)]">
                {jobs.map((job) => {
                  const progress = jobProgress(job);
                  const active = ACTIVE_IMPORT_STATUSES.has(job.status);
                  return (
                    <div
                      key={job.job_id}
                      className="grid gap-3 py-3 lg:grid-cols-[minmax(0,1fr)_130px_170px_auto] lg:items-center"
                    >
                      <div className="flex min-w-0 items-start gap-3">
                        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-[hsl(var(--memory-title))]">
                            {jobLabel(job, t("memory.sourcesPage.historyImports.untitled"))}
                          </p>
                          <p className="mt-0.5 text-xs text-[hsl(var(--memory-muted))]">
                            {t("memory.sourcesPage.historyImports.fileCount", {
                              count: job.included_files.length,
                            })}
                          </p>
                        </div>
                      </div>
                      <div className="text-xs text-[hsl(var(--memory-body))]">
                        <p>{t(`memory.sourcesPage.historyImports.status.${job.status}`)}</p>
                        {active ? (
                          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[hsl(var(--memory-accent)/0.1)]">
                            <div
                              className="h-full rounded-full bg-[hsl(var(--memory-accent))] transition-[width] duration-300"
                              style={{ width: `${progress}%` }}
                            />
                          </div>
                        ) : null}
                      </div>
                      <div className="text-xs leading-5 text-[hsl(var(--memory-muted))]">
                        <p>{dateFormatter.format(new Date(job.created_at * 1000))}</p>
                        <p>
                          {t("memory.sourcesPage.historyImports.progress", {
                            progress,
                          })}
                        </p>
                      </div>
                      <div className="flex items-center gap-1 lg:justify-end">
                        {job.status === "failed" ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => void retryJob(job.job_id)}
                            disabled={retryingJobId === job.job_id}
                          >
                            {retryingJobId === job.job_id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                            ) : (
                              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                            )}
                            {t("memory.sourcesPage.historyImports.continue")}
                          </Button>
                        ) : null}
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-9 w-9 text-[hsl(var(--memory-muted))] hover:text-destructive"
                          aria-label={t("memory.sourcesPage.historyImports.deleteAction", {
                            name: jobLabel(job, t("memory.sourcesPage.historyImports.untitled")),
                          })}
                          onClick={() => setDeleteTarget(job)}
                        >
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ) : null}
      </section>

      <Dialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => {
          if (!open && !deleting) {
            setDeleteTarget(null);
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("memory.sourcesPage.historyImports.deleteTitle")}</DialogTitle>
            <DialogDescription>
              {t("memory.sourcesPage.historyImports.deleteBody", {
                name: deleteTarget
                  ? jobLabel(
                      deleteTarget,
                      t("memory.sourcesPage.historyImports.untitled"),
                    )
                  : "",
              })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setDeleteTarget(null)}
              disabled={deleting}
            >
              {t("memory.sourcesPage.historyImports.keep")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void deleteJob()}
              disabled={deleting}
            >
              {deleting ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              )}
              {t("memory.sourcesPage.historyImports.deleteConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
