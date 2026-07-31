import { isTauri } from '@tauri-apps/api/core';
import { debug, error, info, warn } from '@tauri-apps/plugin-log';

import { redactConsoleArgs } from './log-redaction';

let initialized = false;

function stringifyConsoleArg(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value instanceof Error) return `${value.name}: ${value.message}\n${value.stack ?? ''}`.trim();
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function formatConsoleArgs(args: unknown[]): string {
  return args.map(stringifyConsoleArg).join(' ');
}

export function initializeDesktopLogging(): void {
  if (initialized) return;
  initialized = true;
  const desktop = isTauri();

  const original = {
    debug: console.debug.bind(console),
    error: console.error.bind(console),
    info: console.info.bind(console),
    log: console.log.bind(console),
    warn: console.warn.bind(console),
  };

  console.debug = (...args: unknown[]) => {
    const safeArgs = redactConsoleArgs(args);
    original.debug(...safeArgs);
    if (desktop) void debug(formatConsoleArgs(safeArgs)).catch(() => undefined);
  };
  console.error = (...args: unknown[]) => {
    const safeArgs = redactConsoleArgs(args);
    original.error(...safeArgs);
    if (desktop) void error(formatConsoleArgs(safeArgs)).catch(() => undefined);
  };
  console.info = (...args: unknown[]) => {
    const safeArgs = redactConsoleArgs(args);
    original.info(...safeArgs);
    if (desktop) void info(formatConsoleArgs(safeArgs)).catch(() => undefined);
  };
  console.log = (...args: unknown[]) => {
    const safeArgs = redactConsoleArgs(args);
    original.log(...safeArgs);
    if (desktop) void info(formatConsoleArgs(safeArgs)).catch(() => undefined);
  };
  console.warn = (...args: unknown[]) => {
    const safeArgs = redactConsoleArgs(args);
    original.warn(...safeArgs);
    if (desktop) void warn(formatConsoleArgs(safeArgs)).catch(() => undefined);
  };

  if (desktop) {
    void info('[desktop] frontend logging bridge initialized').catch(() => undefined);
  }
}
