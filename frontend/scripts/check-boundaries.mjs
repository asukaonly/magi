import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const SOURCE_EXTENSIONS = ['.ts', '.tsx', '.js', '.jsx'];
const INDEX_FILES = SOURCE_EXTENSIONS.map((extension) => `index${extension}`);
const SKIPPED_DIRS = new Set(['__tests__', '__ui_preview__', '__visual__', 'test']);
const DEFAULT_SRC_ROOT = path.resolve(process.cwd(), 'src');

const FORBIDDEN_LAYER_IMPORTS = {
  api: new Set(['pages', 'router']),
  constants: new Set(['pages', 'router']),
  domain: new Set(['pages', 'router']),
  hooks: new Set(['pages', 'router']),
  lib: new Set(['pages', 'router']),
  realtime: new Set(['pages', 'router']),
  runtime: new Set(['pages', 'router']),
  stores: new Set(['pages', 'router']),
  types: new Set(['pages', 'router']),
  utils: new Set(['pages', 'router']),
  components: new Set(['pages', 'router']),
};

const STATIC_IMPORT_PATTERN =
  /\b(?:import|export)\s+(?:type\s+)?(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const DYNAMIC_IMPORT_PATTERN = /\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g;

const normalizePath = (value) => value.replaceAll(path.sep, '/');

const isSourceFile = (filePath) => SOURCE_EXTENSIONS.includes(path.extname(filePath));

const shouldSkipPath = (filePath) => normalizePath(filePath)
  .split('/')
  .some((part) => SKIPPED_DIRS.has(part));

const walkSourceFiles = (directory) => {
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      if (!SKIPPED_DIRS.has(entry.name)) {
        files.push(...walkSourceFiles(entryPath));
      }
      continue;
    }
    if (entry.isFile() && isSourceFile(entryPath)) {
      files.push(entryPath);
    }
  }
  return files;
};

const resolveExistingSourcePath = (candidatePath) => {
  const candidates = [
    candidatePath,
    ...SOURCE_EXTENSIONS.map((extension) => `${candidatePath}${extension}`),
    ...INDEX_FILES.map((fileName) => path.join(candidatePath, fileName)),
  ];

  return candidates.find((candidate) => fs.existsSync(candidate)) ?? candidatePath;
};

const resolveImportPath = (importerPath, importSource, srcRoot) => {
  if (importSource.startsWith('@/')) {
    return resolveExistingSourcePath(path.join(srcRoot, importSource.slice(2)));
  }
  if (importSource.startsWith('.')) {
    return resolveExistingSourcePath(path.resolve(path.dirname(importerPath), importSource));
  }
  return null;
};

const layerForPath = (filePath, srcRoot) => {
  const relativePath = normalizePath(path.relative(srcRoot, filePath));
  if (relativePath.startsWith('..')) {
    return null;
  }
  const [firstPart] = relativePath.split('/');
  if (firstPart === 'App.tsx' || firstPart === 'main.tsx') {
    return 'app';
  }
  return firstPart.replace(/\.[^.]+$/, '');
};

const findLineNumber = (source, index) => source.slice(0, index).split(/\r?\n/).length;

const extractImportSources = (source) => {
  const imports = [];
  for (const pattern of [STATIC_IMPORT_PATTERN, DYNAMIC_IMPORT_PATTERN]) {
    pattern.lastIndex = 0;
    let match;
    while ((match = pattern.exec(source)) !== null) {
      imports.push({
        source: match[1],
        line: findLineNumber(source, match.index),
      });
    }
  }
  return imports.sort((left, right) => left.line - right.line);
};

export function findBoundaryViolations(files, options = {}) {
  const srcRoot = path.resolve(options.srcRoot ?? DEFAULT_SRC_ROOT);
  const violations = [];

  for (const file of files) {
    const filePath = path.resolve(file.filePath);
    if (shouldSkipPath(filePath)) {
      continue;
    }

    const importerLayer = layerForPath(filePath, srcRoot);
    const forbiddenImports = importerLayer ? FORBIDDEN_LAYER_IMPORTS[importerLayer] : null;
    if (!forbiddenImports) {
      continue;
    }

    const source = file.source;
    for (const importEntry of extractImportSources(source)) {
      const importedPath = resolveImportPath(filePath, importEntry.source, srcRoot);
      if (!importedPath) {
        continue;
      }

      const relativeImportedPath = normalizePath(path.relative(srcRoot, importedPath));
      if (relativeImportedPath.startsWith('..')) {
        continue;
      }

      const importedLayer = layerForPath(importedPath, srcRoot);
      if (importedLayer && forbiddenImports.has(importedLayer)) {
        violations.push({
          filePath,
          line: importEntry.line,
          importSource: importEntry.source,
          importerLayer,
          importedLayer,
        });
      }
    }
  }

  return violations;
}

const readProjectFiles = (srcRoot) => walkSourceFiles(srcRoot)
  .filter((filePath) => !shouldSkipPath(filePath))
  .map((filePath) => ({
    filePath,
    source: fs.readFileSync(filePath, 'utf8'),
  }));

const formatViolation = (violation, srcRoot) => {
  const relativePath = normalizePath(path.relative(srcRoot, violation.filePath));
  return [
    `${relativePath}:${violation.line}`,
    `${violation.importerLayer} must not import ${violation.importedLayer}`,
    `via ${violation.importSource}`,
  ].join(' - ');
};

const runCli = () => {
  const srcRoot = path.resolve(process.argv[2] ?? DEFAULT_SRC_ROOT);
  const violations = findBoundaryViolations(readProjectFiles(srcRoot), { srcRoot });

  if (violations.length === 0) {
    console.log('Frontend import boundaries are clean.');
    return;
  }

  console.error('Frontend import boundary violations found:');
  for (const violation of violations) {
    console.error(`- ${formatViolation(violation, srcRoot)}`);
  }
  process.exitCode = 1;
};

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runCli();
}
