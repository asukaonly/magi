import type { HistoryImportJob } from "@/api/modules/historyImports";

export interface HistoryImportProgress {
  totalCount: number;
  savedCount: number;
  queuedCount: number;
  savedPercent: number;
  hasSaveGap: boolean;
  hasMemoryQueueGap: boolean;
  fullyTransferred: boolean;
}

export function historyImportProgress(job: HistoryImportJob): HistoryImportProgress {
  const totalCount = Math.max(0, job.total_records);
  const savedCount = Math.max(0, Math.min(job.imported_count, totalCount));
  const queuedCount = Math.max(0, Math.min(job.projected_count, savedCount));
  const hasSaveGap = savedCount < totalCount;
  const hasMemoryQueueGap = queuedCount < savedCount;

  return {
    totalCount,
    savedCount,
    queuedCount,
    savedPercent: Math.min(
      100,
      Math.round((savedCount / Math.max(totalCount, 1)) * 100),
    ),
    hasSaveGap,
    hasMemoryQueueGap,
    fullyTransferred: !hasSaveGap && !hasMemoryQueueGap,
  };
}

export function historyImportStatusKey(job: HistoryImportJob): string {
  const progress = historyImportProgress(job);
  if (job.status === "completed" && !progress.fullyTransferred) {
    return "partial";
  }
  return job.status;
}

export function canRetryHistoryImport(job: HistoryImportJob): boolean {
  const progress = historyImportProgress(job);
  return job.status === "failed" || (
    job.status === "completed" && progress.hasMemoryQueueGap
  );
}
