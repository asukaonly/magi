import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertCircle,
  BookOpenText,
  CheckCircle2,
  Eye,
  ExternalLink,
  FileArchive,
  FileText,
  FolderOpen,
  Loader2,
  MessagesSquare,
  NotebookPen,
  RotateCcw,
  UserRound,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  historyImportsApi,
  type HistoryImportJob,
  type HistoryImporterSpec,
  type HistoryImportSourcePreview,
  type HistoryImportSourceSummary,
} from "@/api/modules/historyImports";
import {
  pluginsApi,
  type PluginRegistryEntry,
} from "@/api/modules/plugins";
import { PluginIcon } from "@/components/plugins/PluginIcon";
import { Button } from "@/components/ui/button";
import { createMarkdownComponents } from "@/components/ui/markdown-components";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  openExternalUrl,
  pickDirectory,
  pickHistoryImportFiles,
  pickMarkdownFiles,
} from "@/runtime/desktop";
import { usePluginInstallPanelStore } from "@/stores/pluginInstallPanel";
import { localizedPluginText } from "@/utils/plugin-display-groups";
import {
  canRetryHistoryImport,
  historyImportProgress,
} from "./historyImportProgress";

interface HistoryImportFlowProps {
  initialJobId?: string | null;
  onJobUpdate: (job: HistoryImportJob | null) => void;
  confirmationPlacement?: "inline" | "footer";
  onActionStateChange?: (state: HistoryImportFlowActionState) => void;
}

export interface HistoryImportFlowHandle {
  confirm: () => Promise<boolean>;
  discard: () => Promise<boolean>;
}

export interface HistoryImportFlowActionState {
  canConfirm: boolean;
  busy: boolean;
}

const documentPreviewMarkdownComponents = createMarkdownComponents("comfortable");

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

export const HistoryImportFlow = forwardRef<
  HistoryImportFlowHandle,
  HistoryImportFlowProps
>(function HistoryImportFlow(
  {
    initialJobId = null,
    onJobUpdate,
    confirmationPlacement = "inline",
    onActionStateChange,
  },
  ref,
): JSX.Element {
  const { t, i18n } = useTranslation("onboarding");
  const [job, setJob] = useState<HistoryImportJob | null>(null);
  const [loading, setLoading] = useState(Boolean(initialJobId));
  const [importers, setImporters] = useState<HistoryImporterSpec[]>([]);
  const [installCandidates, setInstallCandidates] = useState<PluginRegistryEntry[]>([]);
  const [importersLoading, setImportersLoading] = useState(true);
  const [importersError, setImportersError] = useState(false);
  const [selfParticipantIds, setSelfParticipantIds] = useState<string[]>([]);
  const [action, setAction] = useState<
    "preview" | "confirm" | "resume" | "delete" | null
  >(null);
  const [previewTarget, setPreviewTarget] = useState<string | null>(null);
  const [selectionBusy, setSelectionBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewSource, setPreviewSource] =
    useState<HistoryImportSourceSummary | null>(null);
  const [sourcePreview, setSourcePreview] =
    useState<HistoryImportSourcePreview | null>(null);
  const [sourcePreviewLoading, setSourcePreviewLoading] = useState(false);
  const [sourcePreviewError, setSourcePreviewError] = useState<string | null>(null);
  const [progressPollingFailed, setProgressPollingFailed] = useState(false);
  const [progressRefreshBusy, setProgressRefreshBusy] = useState(false);
  const onJobUpdateRef = useRef(onJobUpdate);
  onJobUpdateRef.current = onJobUpdate;
  const openPluginInstallPanel = usePluginInstallPanelStore((state) => state.openPanel);

  const applyJob = useCallback(
    (nextJob: HistoryImportJob): void => {
      setJob(nextJob);
      const validParticipantIds = new Set(
        nextJob.participants.map((participant) => participant.participant_id),
      );
      setSelfParticipantIds((current) => {
        const candidate = nextJob.self_participant_ids.length > 0
          ? nextJob.self_participant_ids
          : current;
        return candidate.filter((participantId) =>
          validParticipantIds.has(participantId));
      });
      onJobUpdateRef.current(nextJob);
    },
    [],
  );

  const loadPlatformOptions = useCallback(async (forceRegistry = false): Promise<void> => {
    setImportersLoading(true);
    const [availableResult, registryResult] = await Promise.allSettled([
      historyImportsApi.listImporters(),
      pluginsApi.getRegistry(forceRegistry ? { force: true } : undefined),
    ]);
    const nextImporters = availableResult.status === "fulfilled"
      ? availableResult.value
      : [];
    setImporters(nextImporters);
    if (registryResult.status === "fulfilled") {
      const availablePluginIds = new Set(
        nextImporters.map((importer) => importer.plugin_id),
      );
      setInstallCandidates(
        registryResult.value.plugins.filter(
          (entry) =>
            entry.official &&
            !availablePluginIds.has(entry.plugin_id) &&
            entry.contribution_types.includes("history_importer"),
        ),
      );
    } else {
      setInstallCandidates([]);
    }
    setImportersError(
      availableResult.status === "rejected" || registryResult.status === "rejected",
    );
    setImportersLoading(false);
  }, []);

  useEffect(() => {
    void loadPlatformOptions();
  }, [loadPlatformOptions]);

  const installPlatformImporter = useCallback(
    (candidate: PluginRegistryEntry): void => {
      openPluginInstallPanel(candidate.plugin_id, {
        install: !candidate.installed,
        pluginName: localizedPluginText(
          candidate.name,
          candidate.name_i18n,
          i18n.language,
        ),
        pluginIcon: candidate.icon,
        context: "history_import",
        onDone: () => {
          void loadPlatformOptions(true);
        },
      });
    },
    [i18n.language, loadPlatformOptions, openPluginInstallPanel],
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
      setProgressPollingFailed(false);
      return;
    }
    let stopped = false;
    let timer: number | null = null;
    const poll = (): void => {
      historyImportsApi
        .get(job.job_id)
        .then((nextJob) => {
          if (stopped) {
            return;
          }
          setProgressPollingFailed(false);
          applyJob(nextJob);
        })
        .catch(() => {
          if (!stopped) {
            setProgressPollingFailed(true);
          }
        });
    };
    timer = window.setTimeout(poll, 1200);
    return () => {
      stopped = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [applyJob, job]);

  const refreshProgress = async (): Promise<void> => {
    if (!job || progressRefreshBusy) {
      return;
    }
    setProgressRefreshBusy(true);
    try {
      applyJob(await historyImportsApi.get(job.job_id));
      setProgressPollingFailed(false);
    } catch {
      setProgressPollingFailed(true);
    } finally {
      setProgressRefreshBusy(false);
    }
  };

  const previewPaths = async (paths: string[]): Promise<void> => {
    if (paths.length === 0) {
      return;
    }
    setAction("preview");
    setPreviewTarget("markdown");
    setError(null);
    try {
      applyJob(await historyImportsApi.previewMarkdown(paths));
    } catch (previewError) {
      setError(errorReason(previewError));
    } finally {
      setAction(null);
      setPreviewTarget(null);
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

  const choosePlatformExport = async (
    importer: HistoryImporterSpec,
  ): Promise<void> => {
    const paths = await pickHistoryImportFiles(
      importer.accepted_extensions,
      t("firstContext.history.platform.fileFilter"),
    );
    if (paths.length === 0) {
      return;
    }
    setAction("preview");
    const importerKey = `${importer.plugin_id}:${importer.importer_id}`;
    setPreviewTarget(importerKey);
    setError(null);
    try {
      applyJob(
        await historyImportsApi.previewWithImporter({
          pluginId: importer.plugin_id,
          importerId: importer.importer_id,
          paths,
        }),
      );
    } catch (previewError) {
      setError(errorReason(previewError));
    } finally {
      setAction(null);
      setPreviewTarget(null);
    }
  };

  const updateIncludedSources = async (
    nextIncluded: string[],
    busyKey: string,
  ): Promise<void> => {
    if (!job || selectionBusy || action !== null) {
      return;
    }
    if (
      nextIncluded.length === job.included_source_ids.length &&
      nextIncluded.every((sourceId) => job.included_source_ids.includes(sourceId))
    ) {
      return;
    }
    const previous = job;
    setError(null);
    setSelectionBusy(busyKey);
    setJob({
      ...job,
      included_source_ids: nextIncluded,
      sources: job.sources.map((source) =>
        ({ ...source, included: nextIncluded.includes(source.source_id) }),
      ),
    });
    try {
      applyJob(
        await historyImportsApi.updateSelection(job.job_id, nextIncluded),
      );
    } catch (selectionError) {
      applyJob(previous);
      setError(errorReason(selectionError));
    } finally {
      setSelectionBusy(null);
    }
  };

  const toggleSource = async (sourceId: string): Promise<void> => {
    if (!job) {
      return;
    }
    const nextIncluded = job.included_source_ids.includes(sourceId)
      ? job.included_source_ids.filter((id) => id !== sourceId)
      : job.sources.map((source) => source.source_id).filter(
          (id) => id === sourceId || job.included_source_ids.includes(id),
        );
    await updateIncludedSources(nextIncluded, sourceId);
  };

  const selectAllSources = async (): Promise<void> => {
    if (job) {
      await updateIncludedSources(
        job.sources.map((source) => source.source_id),
        "__all__",
      );
    }
  };

  const invertSourceSelection = async (): Promise<void> => {
    if (job) {
      const included = new Set(job.included_source_ids);
      await updateIncludedSources(
        job.sources
          .map((source) => source.source_id)
          .filter((sourceId) => !included.has(sourceId)),
        "__invert__",
      );
    }
  };

  const openSourcePreview = async (
    source: HistoryImportSourceSummary,
  ): Promise<void> => {
    if (!job) {
      return;
    }
    setPreviewSource(source);
    setSourcePreview(null);
    setSourcePreviewError(null);
    setSourcePreviewLoading(true);
    try {
      setSourcePreview(
        await historyImportsApi.getSourcePreview(job.job_id, source.source_id),
      );
    } catch (previewError) {
      setSourcePreviewError(errorReason(previewError));
    } finally {
      setSourcePreviewLoading(false);
    }
  };

  const includedSources = useMemo(
    () => job?.sources.filter((source) => source.included) ?? [],
    [job],
  );
  const isConversationImport = job?.detected_kind === "chat";
  const validParticipantIds = useMemo(
    () => new Set(job?.participants.map((participant) => participant.participant_id) ?? []),
    [job?.participants],
  );
  const hasValidSelfIdentity = selfParticipantIds.length > 0 &&
    selfParticipantIds.every((participantId) => validParticipantIds.has(participantId));
  const canConfirm = Boolean(
    job &&
      includedSources.length > 0 &&
      !selectionBusy &&
      (!isConversationImport || hasValidSelfIdentity),
  );

  useEffect(() => {
    onActionStateChange?.({
      canConfirm,
      busy: action !== null || selectionBusy !== null,
    });
  }, [action, canConfirm, onActionStateChange, selectionBusy]);

  const confirmImport = useCallback(async (): Promise<boolean> => {
    if (!job || !canConfirm) {
      return false;
    }
    setAction("confirm");
    setError(null);
    try {
      applyJob(
        await historyImportsApi.confirm(job.job_id, {
          confirmPersonalWriting: job.detected_kind === "document",
          includedSourceIds: job.included_source_ids,
          selfParticipantIds,
        }),
      );
      return true;
    } catch (confirmError) {
      setError(errorReason(confirmError));
      return false;
    } finally {
      setAction(null);
    }
  }, [applyJob, canConfirm, job, selfParticipantIds]);

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

  const chooseAgain = useCallback(async (): Promise<boolean> => {
    if (!job) {
      return false;
    }
    setAction("delete");
    setError(null);
    try {
      await historyImportsApi.delete(job.job_id);
      setJob(null);
      setPreviewSource(null);
      setSourcePreview(null);
      setSelfParticipantIds([]);
      onJobUpdateRef.current(null);
      return true;
    } catch (deleteError) {
      setError(errorReason(deleteError));
      return false;
    } finally {
      setAction(null);
    }
  }, [job]);

  useImperativeHandle(
    ref,
    () => ({
      confirm: confirmImport,
      discard: chooseAgain,
    }),
    [chooseAgain, confirmImport],
  );

  const progress = job ? historyImportProgress(job) : null;
  const dayFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(i18n.resolvedLanguage ?? i18n.language, {
        year: "numeric",
        month: "short",
        day: "numeric",
      }),
    [i18n.language, i18n.resolvedLanguage],
  );
  const messageTimeFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(i18n.resolvedLanguage ?? i18n.language, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }),
    [i18n.language, i18n.resolvedLanguage],
  );
  const sourceDateRange = (
    firstEventAt: number,
    lastEventAt: number,
    confidence: string,
  ): string => {
    if (confidence === "unknown") {
      return t("firstContext.history.preview.missingTime");
    }
    if (confidence === "inferred") {
      return t("firstContext.history.preview.approximateTime");
    }
    if (confidence === "file_mtime") {
      return t("firstContext.history.preview.approximateFileTime");
    }
    if (["file_order", "file_mtime", "mixed", "source_order"].includes(confidence)) {
      return t("firstContext.history.preview.approximateOrder");
    }
    const first = dayFormatter.format(new Date(firstEventAt * 1000));
    const last = dayFormatter.format(new Date(lastEventAt * 1000));
    return first === last
      ? first
      : t("firstContext.history.preview.dateRange", { first, last });
  };
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
      <div className="space-y-5" data-testid="history-import-empty">
        <section className="overflow-hidden rounded-2xl border border-border/60 bg-card">
          <div className="flex flex-col gap-4 px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-start gap-3.5">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/9 text-primary">
                <NotebookPen className="h-5 w-5" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <h4 className="text-sm font-semibold leading-6 text-foreground">
                  {t("firstContext.history.picker.markdownTitle")}
                </h4>
                <p className="max-w-xl text-xs leading-5 text-muted-foreground">
                  {t("firstContext.history.picker.markdownBody")}
                </p>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2 sm:justify-end">
              <Button
                type="button"
                onClick={() => void chooseFiles()}
                disabled={action !== null}
              >
                {action === "preview" && previewTarget === "markdown" ? (
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
          <div className="flex items-start gap-2 border-t border-border/50 bg-muted/20 px-5 py-3 text-[11px] leading-5 text-muted-foreground">
            <BookOpenText className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {t("firstContext.history.picker.note")}
          </div>
        </section>

        <section aria-labelledby="platform-importers-title" className="space-y-2.5">
          <div className="flex items-end justify-between gap-4 px-1">
            <div>
              <h4
                id="platform-importers-title"
                className="text-sm font-semibold leading-6 text-foreground"
              >
                {t("firstContext.history.platform.title")}
              </h4>
              <p className="text-xs leading-5 text-muted-foreground">
                {t("firstContext.history.platform.body")}
              </p>
            </div>
            <span className="shrink-0 text-[11px] text-muted-foreground/75">
              {t("firstContext.history.platform.oneShot")}
            </span>
          </div>
          <div className="overflow-hidden rounded-2xl border border-border/60 bg-card">
            {importersLoading ? (
              <div
                role="status"
                className="flex min-h-20 items-center justify-center gap-2 text-xs text-muted-foreground"
              >
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                {t("firstContext.history.platform.loading")}
              </div>
            ) : importers.length === 0 && installCandidates.length === 0 && importersError ? (
              <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
                <p role="alert" className="text-xs text-muted-foreground">
                  {t("firstContext.history.platform.loadError")}
                </p>
                <Button type="button" size="sm" variant="ghost" onClick={() => void loadPlatformOptions(true)}>
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                  {t("firstContext.history.platform.retry")}
                </Button>
              </div>
            ) : importers.length === 0 && installCandidates.length === 0 ? (
              <div className="flex items-start gap-3 px-5 py-4 text-xs leading-5 text-muted-foreground">
                <MessagesSquare className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <p>{t("firstContext.history.platform.empty")}</p>
              </div>
            ) : (
              <div className="divide-y divide-border/45">
                {importers.map((importer) => (
                  <div
                    key={`${importer.plugin_id}:${importer.importer_id}`}
                    className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex min-w-0 items-start gap-3.5">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted text-foreground">
                        <MessagesSquare className="h-5 w-5" aria-hidden="true" />
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold leading-6 text-foreground">
                          {localizedPluginText(
                            importer.display_name,
                            importer.display_name_i18n,
                            i18n.resolvedLanguage ?? i18n.language,
                          )}
                        </p>
                        <p className="max-w-xl text-xs leading-5 text-muted-foreground">
                          {localizedPluginText(
                            importer.description,
                            importer.description_i18n,
                            i18n.resolvedLanguage ?? i18n.language,
                          )}
                        </p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground/80">
                          <span>
                            {t("firstContext.history.platform.formats", {
                              formats: importer.accepted_extensions
                                .map((extension) => `.${extension.replace(/^\./, "")}`)
                                .join(" / "),
                            })}
                          </span>
                          {importer.export_help_url ? (
                            <button
                              type="button"
                              className="inline-flex items-center gap-1 text-primary hover:underline"
                              onClick={() => void openExternalUrl(importer.export_help_url!)}
                            >
                              {t("firstContext.history.platform.help")}
                              <ExternalLink className="h-3 w-3" aria-hidden="true" />
                            </button>
                          ) : null}
                        </div>
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      className="shrink-0"
                      onClick={() => void choosePlatformExport(importer)}
                      disabled={action !== null}
                    >
                      {action === "preview" &&
                      previewTarget === `${importer.plugin_id}:${importer.importer_id}` ? (
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                      ) : (
                        <FileArchive className="h-4 w-4" aria-hidden="true" />
                      )}
                      {t("firstContext.history.platform.choose")}
                    </Button>
                  </div>
                ))}
                {installCandidates.map((candidate) => (
                  <div
                    key={candidate.plugin_id}
                    className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex min-w-0 items-start gap-3.5">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted text-foreground">
                        <PluginIcon iconId={candidate.icon} className="h-5 w-5" />
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold leading-6 text-foreground">
                          {localizedPluginText(
                            candidate.name,
                            candidate.name_i18n,
                            i18n.language,
                          )}
                        </p>
                        <p className="max-w-xl text-xs leading-5 text-muted-foreground">
                          {localizedPluginText(
                            candidate.description,
                            candidate.description_i18n,
                            i18n.language,
                          )}
                        </p>
                        <p className="mt-1.5 text-[11px] text-muted-foreground/80">
                          {t(
                            candidate.installed
                              ? "firstContext.history.platform.enableHint"
                              : "firstContext.history.platform.installHint",
                          )}
                        </p>
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      className="shrink-0"
                      onClick={() => installPlatformImporter(candidate)}
                      disabled={action !== null}
                    >
                      {t(
                        candidate.installed
                          ? "firstContext.history.platform.enable"
                          : "firstContext.history.platform.install",
                      )}
                    </Button>
                  </div>
                ))}
                {importersError ? (
                  <div className="flex flex-wrap items-center justify-between gap-3 bg-muted/20 px-5 py-3">
                    <p role="alert" className="text-[11px] text-muted-foreground">
                      {t("firstContext.history.platform.partialLoadError")}
                    </p>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => void loadPlatformOptions(true)}
                    >
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                      {t("firstContext.history.platform.retry")}
                    </Button>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </section>
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
    const complete = job.status === "completed" && progress?.fullyTransferred;
    const partial = job.status === "completed" && !progress?.fullyTransferred;
    const failed = job.status === "failed";
    const retryable = canRetryHistoryImport(job);
    return (
      <div className="space-y-5" data-testid="history-import-ready">
        <div className="rounded-2xl border border-primary/15 bg-primary/[0.045] p-5 sm:p-6">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <h4 className="text-[15px] font-semibold text-foreground">
                {t("firstContext.history.ready.title")}
              </h4>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                {complete
                  ? t("firstContext.history.ready.completed")
                  : partial
                    ? t("firstContext.history.ready.partial")
                  : failed
                    ? t("firstContext.history.ready.failed")
                    : t("firstContext.history.ready.background")}
              </p>
              <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-primary/10">
                <div
                  className="h-full rounded-full bg-primary transition-[width] duration-300"
                  style={{ width: `${progress?.savedPercent ?? 0}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {t("firstContext.history.ready.progress", {
                  progress: progress?.savedPercent ?? 0,
                })}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("firstContext.history.ready.memoryQueued", {
                  queued: progress?.queuedCount ?? 0,
                  saved: progress?.savedCount ?? 0,
                })}
              </p>
            </div>
          </div>
        </div>
        {retryable ? (
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
        {progressPollingFailed ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/60 bg-muted/20 px-4 py-3">
            <p role="status" className="text-xs leading-5 text-muted-foreground">
              {t("firstContext.history.ready.progressUnavailable")}
            </p>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => void refreshProgress()}
              disabled={progressRefreshBusy}
            >
              {progressRefreshBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              {t("firstContext.history.ready.refreshProgress")}
            </Button>
          </div>
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
    <>
      <div className="space-y-5" data-testid="history-import-preview">
        <section className="overflow-hidden rounded-2xl border border-border/65 bg-card">
          <div className="flex flex-col gap-3 border-b border-border/55 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <h4 className="text-sm font-semibold text-foreground">
                {t(
                  isConversationImport
                    ? "firstContext.history.preview.chooseConversations"
                    : "firstContext.history.preview.chooseContent",
                )}
              </h4>
              <p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">
                {t(
                  isConversationImport
                    ? "firstContext.history.preview.chooseConversationsBody"
                    : "firstContext.history.preview.chooseContentBody",
                )}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-1.5">
              <span className="mr-1 text-xs tabular-nums text-muted-foreground">
                {t(
                  isConversationImport
                    ? "firstContext.history.preview.selectedConversations"
                    : "firstContext.history.preview.selectedFiles",
                  {
                  selected: includedSources.length,
                  total: job.sources.length,
                  },
                )}
              </span>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => void selectAllSources()}
                disabled={
                  selectionBusy !== null ||
                  action !== null ||
                  includedSources.length === job.sources.length
                }
              >
                {selectionBusy === "__all__" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : null}
                {t("firstContext.history.preview.selectAll")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => void invertSourceSelection()}
                disabled={selectionBusy !== null || action !== null}
              >
                {selectionBusy === "__invert__" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : null}
                {t("firstContext.history.preview.invertSelection")}
              </Button>
            </div>
          </div>
          <div
            data-testid="history-import-source-list"
            className="divide-y divide-border/45"
          >
            {job.sources.map((source) => {
              const busy = selectionBusy === source.source_id;
              return (
                <div
                  key={source.source_id}
                  className={`grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-5 py-3 transition-colors duration-150 ${
                    source.included ? "bg-card" : "bg-muted/20"
                  } hover:bg-accent/30`}
                >
                  <span className="flex h-5 w-5 items-center justify-center">
                    {busy ? (
                      <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
                    ) : (
                      <input
                        type="checkbox"
                        checked={source.included}
                        onChange={() => void toggleSource(source.source_id)}
                        disabled={selectionBusy !== null || action !== null}
                        className="h-4 w-4 rounded border-border accent-primary"
                        aria-label={t(
                          isConversationImport
                            ? "firstContext.history.preview.includeConversation"
                            : "firstContext.history.preview.includeFile",
                          { name: source.source_name, file: source.source_name },
                        )}
                      />
                    )}
                  </span>
                  <div className={`min-w-0 ${source.included ? "" : "opacity-55"}`}>
                    <p className="truncate text-sm font-medium text-foreground">
                      {source.source_name}
                    </p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-[11px] text-muted-foreground">
                      <span>
                        {t(`firstContext.history.preview.kind.${source.detected_kind}`)}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span>
                        {sourceDateRange(
                          source.first_event_at,
                          source.last_event_at,
                          source.timestamp_confidence,
                        )}
                      </span>
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground hover:text-foreground"
                    onClick={() => void openSourcePreview(source)}
                    aria-label={t("firstContext.history.preview.previewFile", {
                      file: source.source_name,
                    })}
                  >
                    <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                    {t("firstContext.history.preview.preview")}
                  </Button>
                </div>
              );
            })}
          </div>
        </section>

        {isConversationImport && job.warning_summary.total_count > 0 ? (
          <div
            role="status"
            className="flex items-start gap-2 rounded-xl border border-amber-200/70 bg-amber-50/65 px-4 py-3 text-sm leading-6 text-amber-950"
          >
            <AlertCircle
              className="mt-1 h-4 w-4 shrink-0 text-amber-700"
              aria-hidden="true"
            />
            <p>{t("firstContext.history.preview.omittedContentNotice")}</p>
          </div>
        ) : null}

        {isConversationImport ? (
          <section
            aria-labelledby="history-import-identity-title"
            className="overflow-hidden rounded-2xl border border-border/65 bg-card"
          >
            <div className="flex items-start gap-3 border-b border-border/50 px-5 py-4">
              <UserRound className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
              <div>
                <h4
                  id="history-import-identity-title"
                  className="text-sm font-semibold text-foreground"
                >
                  {t("firstContext.history.identity.title")}
                </h4>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {t("firstContext.history.identity.body")}
                </p>
              </div>
            </div>
            {job.participants.length > 0 ? (
              <div
                role="group"
                aria-labelledby="history-import-identity-title"
                className="grid gap-px bg-border/45 sm:grid-cols-2"
              >
                {job.participants.map((participant) => {
                  const selected = selfParticipantIds.includes(participant.participant_id);
                  return (
                    <button
                      key={participant.participant_id}
                      type="button"
                      role="checkbox"
                      aria-checked={selected}
                      className={`flex min-w-0 items-start gap-3 bg-card px-5 py-4 text-left transition-colors hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring ${
                        selected ? "bg-primary/[0.055]" : ""
                      }`}
                      onClick={() =>
                        setSelfParticipantIds((current) =>
                          current.includes(participant.participant_id)
                            ? current.filter((id) => id !== participant.participant_id)
                            : [...current, participant.participant_id],
                        )
                      }
                    >
                      <span
                        aria-hidden="true"
                        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                          selected ? "border-primary" : "border-muted-foreground/45"
                        }`}
                      >
                        {selected ? <span className="h-2 w-2 rounded-full bg-primary" /> : null}
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-foreground">
                          {participant.display_name}
                        </span>
                        <span className="mt-0.5 block text-[11px] text-muted-foreground">
                          {t("firstContext.history.identity.messageCount", {
                            count: participant.message_count,
                          })}
                        </span>
                        {participant.sample ? (
                          <span className="mt-1 block line-clamp-1 text-xs text-muted-foreground/80">
                            {participant.sample}
                          </span>
                        ) : null}
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="px-5 py-4 text-xs text-destructive">
                {t("firstContext.history.identity.empty")}
              </p>
            )}
          </section>
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
          {confirmationPlacement === "inline" ? (
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
          ) : null}
        </div>
      </div>
      <Sheet
        open={previewSource !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPreviewSource(null);
            setSourcePreview(null);
            setSourcePreviewError(null);
          }
        }}
      >
        <SheetContent
          side="right"
          closeLabel={t("firstContext.history.sourcePreview.close")}
          className="flex w-[min(92vw,720px)] max-w-none flex-col overflow-hidden bg-background sm:max-w-none"
        >
          <SheetHeader className="border-b border-border/55 bg-background/95 pr-16">
            <SheetTitle className="truncate">
              {previewSource?.source_name ?? ""}
            </SheetTitle>
            <SheetDescription>
              {t(
                previewSource?.detected_kind === "chat"
                  ? "firstContext.history.sourcePreview.conversationDescription"
                  : "firstContext.history.sourcePreview.description",
              )}
            </SheetDescription>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto bg-muted/25 px-6 py-6 sm:px-8">
            {sourcePreviewLoading ? (
              <div
                role="status"
                className="flex min-h-40 items-center justify-center gap-2 text-sm text-muted-foreground"
              >
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                {t("firstContext.history.sourcePreview.loading")}
              </div>
            ) : sourcePreviewError ? (
              <div className="flex min-h-40 flex-col items-center justify-center gap-3 text-center">
                <p role="alert" className="text-sm text-destructive">
                  {t("firstContext.history.sourcePreview.error")}
                </p>
                {previewSource ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => void openSourcePreview(previewSource)}
                  >
                    {t("firstContext.history.sourcePreview.retry")}
                  </Button>
                ) : null}
              </div>
            ) : sourcePreview ? (
              <div className="mx-auto max-w-[640px] space-y-5">
                {sourcePreview.records.map((record) =>
                  sourcePreview.detected_kind === "document" ? (
                    <article
                      key={`${record.session_id}:${record.session_seq}`}
                      className="break-words border-b border-border/45 pb-5 last:border-b-0 last:pb-0"
                    >
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={documentPreviewMarkdownComponents}
                      >
                        {record.content}
                      </ReactMarkdown>
                    </article>
                  ) : (
                    <article
                      key={`${record.session_id}:${record.session_seq}`}
                      className="break-words rounded-xl border border-border/50 bg-background px-4 py-3"
                    >
                      <header className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-foreground">
                          {record.speaker_name}
                        </span>
                        <time className="text-[11px] text-muted-foreground">
                          {record.timestamp_confidence === "exact"
                            ? messageTimeFormatter.format(new Date(record.event_at * 1000))
                            : record.timestamp_confidence === "inferred"
                              ? t("firstContext.history.sourcePreview.timeApproximate")
                              : t("firstContext.history.sourcePreview.timeMissing")}
                        </time>
                      </header>
                      <p className="whitespace-pre-wrap text-sm leading-6 text-foreground/90">
                        {record.content}
                      </p>
                    </article>
                  ),
                )}
                {sourcePreview.truncated ? (
                  <p className="border-t border-border/55 pt-4 text-xs leading-5 text-muted-foreground">
                    {t(
                      sourcePreview.detected_kind === "chat"
                        ? "firstContext.history.sourcePreview.conversationTruncated"
                        : "firstContext.history.sourcePreview.truncated",
                    )}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
});

export default HistoryImportFlow;
