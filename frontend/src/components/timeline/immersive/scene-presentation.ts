import type { TimelineClusterBlock } from '@/api/modules/timeline';

export function cleanText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

export function readableText(value: unknown): string {
  const text = cleanText(value);
  if (/^(?:activity|event|memory|user|coding_assistant)$/i.test(text)) return '';
  if (/(?:^|[ ,、])(?:entity|site|user|episode|cluster):|^[a-f0-9]{16,}$/i.test(text)) return '';
  if (/^(?:codex|claude.code)[ _-]agent[ _-]history$/i.test(text)) return '';
  if (/^(?:(?:Codex|Claude Code) conversed\s*)?<(?:environment_context|skills_instructions|external_codex_apps_|INSTRUCTIONS)/i.test(text)) return '';
  return text;
}

export function sceneTitle(cluster: TimelineClusterBlock, fallback: string): string {
  return cleanText(cluster.user_label) || readableText(cluster.label) || fallback;
}

export function sceneBody(cluster: TimelineClusterBlock, title: string): string {
  return [readableText(cluster.slice_narrative), readableText(cluster.summary), cleanText(cluster.user_note)]
    .find(text => text && text !== title) || '';
}

export function formatClock(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function httpUrl(value: unknown): string | null {
  try {
    const url = new URL(cleanText(value));
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}
