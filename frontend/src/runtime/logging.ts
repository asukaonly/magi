import { isTauri } from '@tauri-apps/api/core';
import { debug, error, info, warn } from '@tauri-apps/plugin-log';

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
  if (initialized || !isTauri()) return;
  initialized = true;

  const original = {
    debug: console.debug.bind(console),
    error: console.error.bind(console),
    info: console.info.bind(console),
    log: console.log.bind(console),
    warn: console.warn.bind(console),
  };

  console.debug = (...args: unknown[]) => {
    original.debug(...args);
    void debug(formatConsoleArgs(args)).catch(() => undefined);
  };
  console.error = (...args: unknown[]) => {
    original.error(...args);
    void error(formatConsoleArgs(args)).catch(() => undefined);
  };
  console.info = (...args: unknown[]) => {
    original.info(...args);
    void info(formatConsoleArgs(args)).catch(() => undefined);
  };
  console.log = (...args: unknown[]) => {
    original.log(...args);
    void info(formatConsoleArgs(args)).catch(() => undefined);
  };
  console.warn = (...args: unknown[]) => {
    original.warn(...args);
    void warn(formatConsoleArgs(args)).catch(() => undefined);
  };

  void info('[desktop] frontend logging bridge initialized').catch(() => undefined);
}