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
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Eye,
  ExternalLink,
  FileArchive,
  FileText,
  FolderOpen,
  Loader2,
  MessagesSquare,
  NotebookPen,
  RotateCcw,
  Plus,
  Trash2,
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
  historyImportStages,
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
  primaryAction: "confirm" | "resume" | null;
}

const documentPreviewMarkdownComponents = createMarkdownComponents("comfortable");
const SOURCE_PAGE_SIZE = 50;

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
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const [importers, setImporters] = useState<HistoryImporterSpec[]>([]);
  const [installCandidates, setInstallCandidates] = useState<PluginRegistryEntry[]>([]);
  const [importersLoading, setImportersLoading] = useState(true);
  const [importersError, setImportersError] = useState(false);
  const [selfParticipantIds, setSelfParticipantIds] = useState<string[]>([]);
  const [action, setAction] = useState<
    "preview" | "append" | "confirm" | "resume" | "delete" | null
  >(null);
  const [previewTarget, setPreviewTarget] = useState<string | null>(null);
  const [selectionBusy, setSelectionBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [appendNotice, setAppendNotice] = useState<{
    added: number;
    duplicates: number;
  } | null>(null);
  const [previewSource, setPreviewSource] =
    useState<HistoryImportSourceSummary | null>(null);
  const [sourcePreview, setSourcePreview] =
    useState<HistoryImportSourcePreview | null>(null);
  const [sourcePreviewLoading, setSourcePreviewLoading] = useState(false);
  const [sourcePreviewError, setSourcePreviewError] = useState<string | null>(null);
  const [sourcePage, setSourcePage] = useState(0);
  const [progressPollingFailed, setProgressPollingFailed] = useState(false);
  const [progressRefreshBusy, setProgressRefreshBusy] = useState(false);
  const onJobUpdateRef = useRef(onJobUpdate);
  const mountedRef = useRef(true);
  const actionRef = useRef<typeof action>(null);
  const selectionBusyRef = useRef<string | null>(null);
  const sourcePreviewAbortRef = useRef<AbortController | null>(null);
  const sourcePreviewRequestRef = useRef(0);
  const platformOptionsRequestRef = useRef(0);
  const jobMutationVersionRef = useRef(0);
  const sourcePageJobIdRef = useRef<string | null>(null);
  const statusHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const focusedStageRef = useRef<string | null>(null);
  onJobUpdateRef.current = onJobUpdate;
  const openPluginInstallPanel = usePluginInstallPanelStore((state) => state.openPanel);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      platformOptionsRequestRef.current += 1;
      sourcePreviewRequestRef.current += 1;
      sourcePreviewAbortRef.current?.abort();
    };
  }, []);

  const setCurrentAction = useCallback((nextAction: typeof action): void => {
    actionRef.current = nextAction;
    if (mountedRef.current) {
      setAction(nextAction);
    }
  }, []);

  const setCurrentSelectionBusy = useCallback((busyKey: string | null): void => {
    selectionBusyRef.current = busyKey;
    if (mountedRef.current) {
      setSelectionBusy(busyKey);
    }
  }, []);

  const applyJob = useCallback(
    (nextJob: HistoryImportJob): void => {
      if (!mountedRef.current) {
        return;
      }
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
    if (!mountedRef.current) {
      return;
    }
    const requestId = platformOptionsRequestRef.current + 1;
    platformOptionsRequestRef.current = requestId;
    setImportersLoading(true);
    const [availableResult, registryResult] = await Promise.allSettled([
      historyImportsApi.listImporters(),
      pluginsApi.getRegistry(forceRegistry ? { force: true } : undefined),
    ]);
    if (!mountedRef.current || platformOptionsRequestRef.current !== requestId) {
      return;
    }
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
  }, [applyJob, initialJobId, job?.job_id, restoreAttempt]);

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
    if (!job || progressRefreshBusy || actionRef.current !== null) {
      return;
    }
    setProgressRefreshBusy(true);
    try {
      const nextJob = await historyImportsApi.get(job.job_id);
      if (mountedRef.current) {
        applyJob(nextJob);
        setProgressPollingFailed(false);
      }
    } catch {
      if (mountedRef.current) {
        setProgressPollingFailed(true);
      }
    } finally {
      if (mountedRef.current) {
        setProgressRefreshBusy(false);
      }
    }
  };

  const previewPaths = async (paths: string[], target: string): Promise<void> => {
    if (!mountedRef.current || paths.length === 0 || actionRef.current !== null) {
      return;
    }
    setCurrentAction("preview");
    if (mountedRef.current) {
      setPreviewTarget(target);
    }
    setError(null);
    try {
      applyJob(await historyImportsApi.previewMarkdown(paths));
    } catch (previewError) {
      if (mountedRef.current) {
        setError(errorReason(previewError));
      }
    } finally {
      setCurrentAction(null);
      if (mountedRef.current) {
        setPreviewTarget(null);
      }
    }
  };

  const chooseFiles = async (): Promise<void> => {
    if (actionRef.current !== null) {
      return;
    }
    setCurrentAction("preview");
    setPreviewTarget("markdown");
    setError(null);
    try {
      const paths = await pickMarkdownFiles();
      setCurrentAction(null);
      if (!mountedRef.current) {
        return;
      }
      if (mountedRef.current) {
        setPreviewTarget(null);
      }
      await previewPaths(paths, "markdown");
    } catch {
      if (mountedRef.current) {
        setError("history_import_file_picker_failed");
      }
      setCurrentAction(null);
      if (mountedRef.current) {
        setPreviewTarget(null);
      }
    }
  };

  const chooseFolder = async (): Promise<void> => {
    if (actionRef.current !== null) {
      return;
    }
    setCurrentAction("preview");
    setPreviewTarget("markdown");
    setError(null);
    try {
      const folder = await pickDirectory();
      setCurrentAction(null);
      if (!mountedRef.current) {
        return;
      }
      if (mountedRef.current) {
        setPreviewTarget(null);
      }
      if (folder) {
        await previewPaths([folder], "markdown");
      }
    } catch {
      if (mountedRef.current) {
        setError("history_import_directory_picker_failed");
      }
      setCurrentAction(null);
      if (mountedRef.current) {
        setPreviewTarget(null);
      }
    }
  };

  const appendMarkdownSelection = async (
    picker: "files" | "folder",
  ): Promise<void> => {
    if (
      !job ||
      job.source_type !== "markdown" ||
      actionRef.current !== null ||
      selectionBusyRef.current !== null
    ) {
      return;
    }
    setCurrentAction("append");
    setError(null);
    setAppendNotice(null);
    let paths: string[];
    try {
      paths = picker === "files"
        ? await pickMarkdownFiles()
        : await pickDirectory().then((folder) => (folder ? [folder] : []));
    } catch {
      if (mountedRef.current) {
        setError(
          picker === "folder"
            ? "history_import_directory_picker_failed"
            : "history_import_file_picker_failed",
        );
      }
      setCurrentAction(null);
      return;
    }
    if (!mountedRef.current || paths.length === 0) {
      setCurrentAction(null);
      return;
    }
    try {
      const result = await historyImportsApi.appendMarkdown(job.job_id, paths);
      if (!mountedRef.current) {
        return;
      }
      applyJob(result.job);
      setAppendNotice({
        added: result.added_source_count,
        duplicates: result.duplicate_source_count,
      });
    } catch (appendError) {
      if (mountedRef.current) {
        setError(errorReason(appendError));
      }
    } finally {
      setCurrentAction(null);
    }
  };

  const choosePlatformExport = async (
    importer: HistoryImporterSpec,
  ): Promise<void> => {
    if (actionRef.current !== null) {
      return;
    }
    const importerKey = `${importer.plugin_id}:${importer.connection_id}:${importer.importer_id}`;
    setCurrentAction("preview");
    setPreviewTarget(importerKey);
    setError(null);
    let paths: string[];
    try {
      paths = await pickHistoryImportFiles(
        importer.accepted_extensions,
        t("firstContext.history.platform.fileFilter"),
      );
    } catch {
      if (mountedRef.current) {
        setError("history_import_file_picker_failed");
      }
      setCurrentAction(null);
      if (mountedRef.current) {
        setPreviewTarget(null);
      }
      return;
    }
    if (paths.length === 0) {
      setCurrentAction(null);
      if (mountedRef.current) {
        setPreviewTarget(null);
      }
      return;
    }
    if (!mountedRef.current) {
      setCurrentAction(null);
      return;
    }
    try {
      applyJob(
        await historyImportsApi.previewWithImporter({
          pluginId: importer.plugin_id,
          connectionId: importer.connection_id,
          importerId: importer.importer_id,
          paths,
        }),
      );
    } catch (previewError) {
      if (mountedRef.current) {
        setError(errorReason(previewError));
      }
    } finally {
      setCurrentAction(null);
      if (mountedRef.current) {
        setPreviewTarget(null);
      }
    }
  };

  const openExportHelp = async (url: string): Promise<void> => {
    setError(null);
    try {
      await openExternalUrl(url);
    } catch {
      if (mountedRef.current) {
        setError("history_import_export_help_failed");
      }
    }
  };

  const updateIncludedSources = async (
    nextIncluded: string[],
    busyKey: string,
  ): Promise<void> => {
    if (!job || selectionBusyRef.current || actionRef.current !== null) {
      return;
    }
    if (
      nextIncluded.length === job.included_source_ids.length &&
      nextIncluded.every((sourceId) => job.included_source_ids.includes(sourceId))
    ) {
      return;
    }
    const previous = job;
    const mutationVersion = jobMutationVersionRef.current + 1;
    jobMutationVersionRef.current = mutationVersion;
    setError(null);
    setCurrentSelectionBusy(busyKey);
    setJob({
      ...job,
      included_source_ids: nextIncluded,
      sources: job.sources.map((source) =>
        ({ ...source, included: nextIncluded.includes(source.source_id) }),
      ),
    });
    try {
      const nextJob = await historyImportsApi.updateSelection(
        job.job_id,
        nextIncluded,
      );
      if (
        mountedRef.current &&
        jobMutationVersionRef.current === mutationVersion
      ) {
        applyJob(nextJob);
      }
    } catch (selectionError) {
      if (
        mountedRef.current &&
        jobMutationVersionRef.current === mutationVersion
      ) {
        applyJob(previous);
        setError(errorReason(selectionError));
      }
    } finally {
      if (jobMutationVersionRef.current === mutationVersion) {
        setCurrentSelectionBusy(null);
      }
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
    sourcePreviewAbortRef.current?.abort();
    const controller = new AbortController();
    sourcePreviewAbortRef.current = controller;
    const requestId = sourcePreviewRequestRef.current + 1;
    sourcePreviewRequestRef.current = requestId;
    const jobId = job.job_id;
    setPreviewSource(source);
    setSourcePreview(null);
    setSourcePreviewError(null);
    setSourcePreviewLoading(true);
    try {
      const preview = await historyImportsApi.getSourcePreview(
        jobId,
        source.source_id,
        controller.signal,
      );
      if (
        mountedRef.current &&
        sourcePreviewRequestRef.current === requestId &&
        !controller.signal.aborted
      ) {
        setSourcePreview(preview);
      }
    } catch (previewError) {
      if (
        mountedRef.current &&
        sourcePreviewRequestRef.current === requestId &&
        !controller.signal.aborted
      ) {
        setSourcePreviewError(errorReason(previewError));
      }
    } finally {
      if (
        mountedRef.current &&
        sourcePreviewRequestRef.current === requestId
      ) {
        setSourcePreviewLoading(false);
      }
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
  const canConfirmSelection = Boolean(
    job &&
      job.status === "preview_ready" &&
      includedSources.length > 0 &&
      !selectionBusyRef.current &&
      (!isConversationImport || hasValidSelfIdentity),
  );
  const failedBeforeQuickReady = Boolean(
    job?.status === "failed" && !job.quick_ready,
  );
  const primaryAction = failedBeforeQuickReady
    ? "resume"
    : job?.status === "preview_ready"
      ? "confirm"
      : null;
  const canConfirm = primaryAction === "resume" || canConfirmSelection;

  useEffect(() => {
    onActionStateChange?.({
      canConfirm,
      busy: action !== null || selectionBusy !== null,
      primaryAction,
    });
  }, [action, canConfirm, onActionStateChange, primaryAction, selectionBusy]);

  const confirmImport = useCallback(async (): Promise<boolean> => {
    if (
      !job ||
      !canConfirmSelection ||
      actionRef.current !== null ||
      selectionBusyRef.current !== null
    ) {
      return false;
    }
    const mutationVersion = jobMutationVersionRef.current + 1;
    jobMutationVersionRef.current = mutationVersion;
    setCurrentAction("confirm");
    setError(null);
    try {
      const nextJob = await historyImportsApi.confirm(job.job_id, {
          confirmPersonalWriting: job.detected_kind === "document",
          includedSourceIds: job.included_source_ids,
          selfParticipantIds,
        });
      if (
        !mountedRef.current ||
        jobMutationVersionRef.current !== mutationVersion
      ) {
        return false;
      }
      applyJob(nextJob);
      return true;
    } catch (confirmError) {
      if (
        mountedRef.current &&
        jobMutationVersionRef.current === mutationVersion
      ) {
        setError(errorReason(confirmError));
      }
      return false;
    } finally {
      if (jobMutationVersionRef.current === mutationVersion) {
        setCurrentAction(null);
      }
    }
  }, [applyJob, canConfirmSelection, job, selfParticipantIds, setCurrentAction]);

  const resumeImport = useCallback(async (): Promise<boolean> => {
    if (
      !job ||
      actionRef.current !== null ||
      selectionBusyRef.current !== null
    ) {
      return false;
    }
    const mutationVersion = jobMutationVersionRef.current + 1;
    jobMutationVersionRef.current = mutationVersion;
    setCurrentAction("resume");
    setError(null);
    try {
      const nextJob = await historyImportsApi.resume(job.job_id);
      if (
        !mountedRef.current ||
        jobMutationVersionRef.current !== mutationVersion
      ) {
        return false;
      }
      applyJob(nextJob);
      return true;
    } catch (resumeError) {
      if (
        mountedRef.current &&
        jobMutationVersionRef.current === mutationVersion
      ) {
        setError(errorReason(resumeError));
      }
      return false;
    } finally {
      if (jobMutationVersionRef.current === mutationVersion) {
        setCurrentAction(null);
      }
    }
  }, [applyJob, job, setCurrentAction]);

  const chooseAgain = useCallback(async (): Promise<boolean> => {
    if (
      !job ||
      actionRef.current !== null ||
      selectionBusyRef.current !== null
    ) {
      return false;
    }
    const mutationVersion = jobMutationVersionRef.current + 1;
    jobMutationVersionRef.current = mutationVersion;
    sourcePreviewRequestRef.current += 1;
    sourcePreviewAbortRef.current?.abort();
    setCurrentAction("delete");
    setError(null);
    try {
      await historyImportsApi.delete(job.job_id);
      if (
        !mountedRef.current ||
        jobMutationVersionRef.current !== mutationVersion
      ) {
        return false;
      }
      setJob(null);
      setPreviewSource(null);
      setSourcePreview(null);
      setSelfParticipantIds([]);
      setAppendNotice(null);
      onJobUpdateRef.current(null);
      return true;
    } catch (deleteError) {
      if (
        mountedRef.current &&
        jobMutationVersionRef.current === mutationVersion
      ) {
        setError(errorReason(deleteError));
      }
      return false;
    } finally {
      if (jobMutationVersionRef.current === mutationVersion) {
        setCurrentAction(null);
      }
    }
  }, [job, setCurrentAction]);

  useImperativeHandle(
    ref,
    () => ({
      confirm: primaryAction === "resume" ? resumeImport : confirmImport,
      discard: chooseAgain,
    }),
    [chooseAgain, confirmImport, primaryAction, resumeImport],
  );

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
  const totalSourcePages = Math.max(
    1,
    Math.ceil((job?.sources.length ?? 0) / SOURCE_PAGE_SIZE),
  );
  const currentSourcePage = Math.min(sourcePage, totalSourcePages - 1);
  const visibleSources = job?.sources.slice(
    currentSourcePage * SOURCE_PAGE_SIZE,
    (currentSourcePage + 1) * SOURCE_PAGE_SIZE,
  ) ?? [];

  useEffect(() => {
    if (sourcePageJobIdRef.current !== (job?.job_id ?? null)) {
      sourcePageJobIdRef.current = job?.job_id ?? null;
      setSourcePage(0);
      return;
    }
    setSourcePage((current) => Math.min(current, totalSourcePages - 1));
  }, [job?.job_id, totalSourcePages]);

  const visualStage = !job
    ? "empty"
    : job.status === "failed" && !job.quick_ready
      ? "failed"
      : ["ready", "running"].includes(job.status) && !job.quick_ready
        ? "preparing"
      : job.quick_ready
        ? "ready"
        : "preview";
  const visualJobId = job?.job_id ?? null;

  useEffect(() => {
    if (!visualJobId || visualStage === "empty") {
      focusedStageRef.current = null;
      return;
    }
    const focusKey = `${visualJobId}:${visualStage}`;
    if (focusedStageRef.current === focusKey) {
      return;
    }
    focusedStageRef.current = focusKey;
    const frame = window.requestAnimationFrame(() => {
      statusHeadingRef.current?.focus();
    });
    return () => {
      window.cancelAnimationFrame(frame);
      if (focusedStageRef.current === focusKey) {
        focusedStageRef.current = null;
      }
    };
  }, [visualJobId, visualStage]);

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
                    key={`${importer.plugin_id}:${importer.connection_id}:${importer.importer_id}`}
                    data-connection-id={importer.connection_id}
                    className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex min-w-0 items-start gap-3.5">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted text-foreground">
                        <MessagesSquare className="h-5 w-5" aria-hidden="true" />
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold leading-6 text-foreground">
                          {importer.connection_display_name || localizedPluginText(
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
                              onClick={() => void openExportHelp(importer.export_help_url!)}
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
                      previewTarget === `${importer.plugin_id}:${importer.connection_id}:${importer.importer_id}` ? (
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
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {translatedError}
            </p>
            {initialJobId ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setError(null);
                  setRestoreAttempt((current) => current + 1);
                }}
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                {t("firstContext.history.restoreRetry")}
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  }

  if (["ready", "running"].includes(job.status) && !job.quick_ready) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-48 flex-col items-center justify-center gap-3 rounded-2xl border border-border/60 bg-card px-6 text-center"
        data-testid="history-import-preparing"
      >
        <Loader2 className="h-5 w-5 animate-spin text-primary" aria-hidden="true" />
        <h4
          ref={statusHeadingRef}
          tabIndex={-1}
          className="text-sm font-semibold text-foreground outline-none"
        >
          {t("firstContext.history.preparing.title")}
        </h4>
        <p className="max-w-lg text-xs leading-5 text-muted-foreground">
          {t("firstContext.history.preparing.body")}
        </p>
      </div>
    );
  }

  if (job.status === "failed" && !job.quick_ready) {
    const jobErrorCode = job.error_code ?? "unknown";
    const jobErrorMessage = t(`firstContext.history.errors.${jobErrorCode}`, {
      defaultValue: t("firstContext.history.errors.unknown"),
    });
    return (
      <div className="space-y-5" data-testid="history-import-failed">
        <div
          role="alert"
          className="rounded-2xl border border-destructive/25 bg-destructive/[0.045] p-5 sm:p-6"
        >
          <div className="flex items-start gap-3">
            <AlertCircle
              className="mt-0.5 h-5 w-5 shrink-0 text-destructive"
              aria-hidden="true"
            />
            <div className="min-w-0 flex-1">
              <h4
                ref={statusHeadingRef}
                tabIndex={-1}
                className="text-[15px] font-semibold text-foreground outline-none"
              >
                {t("firstContext.history.failed.title")}
              </h4>
              <p className="mt-1 text-sm leading-6 text-foreground/85">
                {jobErrorMessage}
              </p>
              <p className="mt-3 text-xs text-muted-foreground">
                {t("firstContext.history.failed.errorCode", {
                  code: jobErrorCode,
                })}
              </p>
            </div>
          </div>
        </div>
        {translatedError ? (
          <p role="alert" className="text-sm text-destructive">
            {translatedError}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button
            type="button"
            variant="ghost"
            onClick={() => void chooseAgain()}
            disabled={action !== null || selectionBusy !== null}
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
              onClick={() => void resumeImport()}
              disabled={action !== null || selectionBusy !== null}
            >
              {action === "resume" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <RotateCcw className="h-4 w-4" aria-hidden="true" />
              )}
              {t("firstContext.history.failed.retry")}
            </Button>
          ) : null}
        </div>
      </div>
    );
  }

  if (job.quick_ready) {
    const readyProgress = historyImportProgress(job);
    const stages = historyImportStages(job);
    const complete = job.status === "completed" && readyProgress.fullyTransferred;
    const partial = job.status === "completed" && !readyProgress.fullyTransferred;
    const failed = job.status === "failed";
    const retryable = canRetryHistoryImport(job);
    return (
      <div className="space-y-5" data-testid="history-import-ready">
        <div className="rounded-2xl border border-primary/15 bg-primary/[0.045] p-5 sm:p-6">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <h4
                ref={statusHeadingRef}
                tabIndex={-1}
                className="text-[15px] font-semibold text-foreground outline-none"
              >
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
              <div
                aria-live="polite"
                className="mt-4 space-y-2 rounded-xl border border-primary/10 bg-background/55 px-3.5 py-3 text-xs text-muted-foreground"
              >
                <div className="flex items-center gap-2">
                  {stages.source === "saved" ? (
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
                  ) : stages.source === "paused" ? (
                    <AlertCircle className="h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden="true" />
                  ) : (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" aria-hidden="true" />
                  )}
                  <span>
                    {t(`firstContext.history.ready.stages.source.${stages.source}`, {
                      saved: readyProgress.savedCount,
                      total: readyProgress.totalCount,
                    })}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {stages.memoryHandoff === "sent" ? (
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
                  ) : stages.memoryHandoff === "sending" ? (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" aria-hidden="true" />
                  ) : stages.memoryHandoff === "paused" ? (
                    <AlertCircle className="h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden="true" />
                  ) : (
                    <span className="h-2 w-2 shrink-0 rounded-full border border-current opacity-45" aria-hidden="true" />
                  )}
                  <span>
                    {t(`firstContext.history.ready.stages.memoryHandoff.${stages.memoryHandoff}`, {
                      queued: readyProgress.queuedCount,
                      total: readyProgress.totalCount,
                    })}
                  </span>
                </div>
              </div>
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
        <p className="text-xs leading-5 text-muted-foreground">
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
              <h4
                ref={statusHeadingRef}
                tabIndex={-1}
                className="text-sm font-semibold text-foreground outline-none"
              >
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
            aria-busy={selectionBusy !== null}
            className="divide-y divide-border/45"
          >
            {visibleSources.map((source) => {
              const busy = selectionBusy === source.source_id;
              return (
                <div
                  key={source.source_id}
                  className={`grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-5 py-3 transition-colors duration-150 ${
                    source.included ? "bg-card" : "bg-muted/20"
                  } hover:bg-accent/30`}
                >
                  <label
                    className={`relative flex h-10 w-10 items-center justify-center rounded-lg ${
                      selectionBusy !== null || action !== null
                        ? "cursor-not-allowed"
                        : "cursor-pointer hover:bg-accent/50"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={source.included}
                      onChange={() => void toggleSource(source.source_id)}
                      disabled={selectionBusy !== null || action !== null}
                      className={`h-4 w-4 rounded border-border accent-primary ${
                        busy ? "opacity-0" : ""
                      }`}
                      aria-label={t(
                        isConversationImport
                          ? "firstContext.history.preview.includeConversation"
                          : "firstContext.history.preview.includeFile",
                        { name: source.source_name, file: source.source_name },
                      )}
                    />
                    {busy ? (
                      <Loader2
                        className="absolute h-4 w-4 animate-spin text-primary"
                        aria-hidden="true"
                      />
                    ) : null}
                  </label>
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
          {totalSourcePages > 1 ? (
            <nav
              aria-label={t("firstContext.history.preview.paginationLabel")}
              className="flex items-center justify-between gap-3 border-t border-border/55 px-5 py-3"
            >
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setSourcePage((current) => Math.max(0, current - 1))}
                disabled={currentSourcePage === 0 || action !== null || selectionBusy !== null}
              >
                <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
                {t("firstContext.history.preview.previousPage")}
              </Button>
              <span aria-live="polite" className="text-xs tabular-nums text-muted-foreground">
                {t("firstContext.history.preview.page", {
                  current: currentSourcePage + 1,
                  total: totalSourcePages,
                })}
              </span>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setSourcePage((current) => Math.min(totalSourcePages - 1, current + 1))}
                disabled={
                  currentSourcePage >= totalSourcePages - 1 ||
                  action !== null ||
                  selectionBusy !== null
                }
              >
                {t("firstContext.history.preview.nextPage")}
                <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Button>
            </nav>
          ) : null}
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
                      disabled={action !== null || selectionBusy !== null}
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

        {appendNotice ? (
          <p
            role="status"
            className="flex items-center gap-2 text-xs text-muted-foreground"
          >
            <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
            {appendNotice.added > 0 && appendNotice.duplicates > 0
              ? t("firstContext.history.preview.appendedWithDuplicates", {
                  added: appendNotice.added,
                  duplicates: appendNotice.duplicates,
                })
              : appendNotice.added > 0
                ? t("firstContext.history.preview.appended", {
                    count: appendNotice.added,
                  })
                : t("firstContext.history.preview.allDuplicates")}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            {job.source_type === "markdown" ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={action !== null || selectionBusy !== null}
                  >
                    {action === "append" ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Plus className="h-4 w-4" aria-hidden="true" />
                    )}
                    {t("firstContext.history.preview.continueAdding")}
                    <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="min-w-44">
                  <DropdownMenuItem
                    onSelect={() => void appendMarkdownSelection("files")}
                  >
                    <FileText className="h-4 w-4" aria-hidden="true" />
                    {t("firstContext.history.preview.addFiles")}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() => void appendMarkdownSelection("folder")}
                  >
                    <FolderOpen className="h-4 w-4" aria-hidden="true" />
                    {t("firstContext.history.preview.addFolder")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              onClick={() => void chooseAgain()}
              disabled={action !== null || selectionBusy !== null}
            >
              {action === "delete" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              )}
              {t("firstContext.history.preview.chooseAgain")}
            </Button>
          </div>
          {confirmationPlacement === "inline" ? (
            <Button
              type="button"
              size="lg"
              onClick={() => void confirmImport()}
              disabled={!canConfirmSelection || action !== null || selectionBusy !== null}
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
            sourcePreviewRequestRef.current += 1;
            sourcePreviewAbortRef.current?.abort();
            setPreviewSource(null);
            setSourcePreview(null);
            setSourcePreviewError(null);
            setSourcePreviewLoading(false);
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
