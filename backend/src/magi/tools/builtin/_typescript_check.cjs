'use strict';

// Use the project's compiler without executing package scripts or emitting files.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
const workspace = path.resolve(request.workspace);
const hash = (value) => crypto.createHash('sha256').update(value).digest('hex');
const within = (file) => {
  const relative = path.relative(workspace, file);
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
};
const contents = new Map();
const existence = new Map();
const directories = new Map();
const listings = new Map();

function readBytes(file) {
  try { return fs.readFileSync(file); } catch { return null; }
}

function readFile(file) {
  file = path.resolve(file);
  if (!contents.has(file)) contents.set(file, readBytes(file));
  const value = contents.get(file);
  if (value === null) return undefined;
  if (value[0] === 0xff && value[1] === 0xfe) return value.subarray(2).toString('utf16le');
  if (value[0] === 0xfe && value[1] === 0xff) return Buffer.from(value.subarray(2)).swap16().toString('utf16le');
  return value.toString('utf8').replace(/^\uFEFF/, '');
}

function ancestors(file) {
  const result = [];
  for (let dir = path.dirname(file); within(dir); dir = path.dirname(dir)) {
    result.push(dir);
    if (dir === path.dirname(dir)) break;
  }
  return result;
}

function configsIn(dir) {
  let names;
  try { names = fs.readdirSync(dir).sort(); } catch { return []; }
  const configs = names.filter((name) => /^(tsconfig|jsconfig)(\.[^.]+)*\.json$/.test(name));
  listings.set(dir, configs);
  return configs.sort((a, b) => Number(b === 'tsconfig.json') - Number(a === 'tsconfig.json')).map((name) => path.join(dir, name));
}

const compilers = new Map();
function compilerFor(file) {
  for (const dir of ancestors(file)) {
    const packageDir = path.join(dir, 'node_modules', 'typescript');
    if (!fs.existsSync(path.join(packageDir, 'package.json'))) continue;
    if (!compilers.has(packageDir)) compilers.set(packageDir, require(packageDir));
    return compilers.get(packageDir);
  }
  return null;
}

function trackedSystem(ts) {
  return {
    ...ts.sys,
    readFile,
    writeFile() { throw new Error('Verification must not emit files'); },
    fileExists(file) {
      const found = ts.sys.fileExists(file);
      if (!existence.has(file)) existence.set(file, found);
      return existence.get(file);
    },
    readDirectory(...args) {
      const key = JSON.stringify(args);
      if (!directories.has(key)) directories.set(key, { ts, args, files: ts.sys.readDirectory(...args).sort() });
      return directories.get(key).files;
    },
  };
}

const parsedProjects = new Map();
function parseProject(ts, config) {
  if (parsedProjects.has(config)) return parsedProjects.get(config);
  const system = trackedSystem(ts);
  const source = ts.readConfigFile(config, readFile);
  const parsed = ts.parseJsonConfigFileContent(source.config || {}, system, path.dirname(config), undefined, config);
  if (source.error) parsed.errors.unshift(source.error);
  parsedProjects.set(config, parsed);
  return parsed;
}

function expandReferences(ts, config, seen = new Set()) {
  if (seen.has(config)) return [];
  seen.add(config);
  const parsed = parseProject(ts, config);
  return [config, ...(parsed.projectReferences || []).flatMap((reference) =>
    expandReferences(ts, ts.resolveProjectReferencePath(reference), seen))];
}

const projects = new Map();
function checkProject(ts, config) {
  if (projects.has(config)) return projects.get(config);
  const parsed = parseProject(ts, config);
  const diagnostics = [...parsed.errors];
  let program;
  const host = ts.createWatchCompilerHost(
    config, { noEmit: true }, trackedSystem(ts),
    ts.createSemanticDiagnosticsBuilderProgram,
    (diagnostic) => diagnostics.push(diagnostic),
    () => {},
  );
  // Source redirects let unbuilt referenced projects be checked without writing declarations.
  host.useSourceOfProjectReferenceRedirect = () => true;
  host.watchFile = host.watchDirectory = () => ({ close() {} });
  host.afterProgramCreate = (builder) => {
    program = builder.getProgram();
    diagnostics.push(...ts.getPreEmitDiagnostics(program));
  };
  const watch = ts.createWatchProgram(host);
  watch.close();
  const errors = ts.sortAndDeduplicateDiagnostics(diagnostics).filter((item) => item.category === ts.DiagnosticCategory.Error);
  const result = {
    program,
    parsed,
    diagnostics: ts.formatDiagnostics(errors, {
      getCanonicalFileName: (file) => file,
      getCurrentDirectory: () => workspace,
      getNewLine: () => '\n',
    }),
    failed: errors.length > 0,
  };
  projects.set(config, result);
  for (const reference of parsed.projectReferences || []) {
    const dependency = checkProject(ts, ts.resolveProjectReferencePath(reference));
    result.failed = result.failed || dependency.failed;
    result.diagnostics += dependency.diagnostics;
  }
  return result;
}

const results = request.paths.map((target) => {
  const base = { path: target, verifier: '(none)', status: 'skipped', reason: null, stdout: '', stderr: '', exit_code: -1 };
  const ts = compilerFor(target);
  if (!ts) return { ...base, reason: 'Project-local TypeScript dependency is not installed' };
  const configs = [...new Set(ancestors(target).flatMap(configsIn).flatMap((config) => expandReferences(ts, config)))];
  let configFailure;
  for (const config of configs) {
    const result = checkProject(ts, config);
    const source = result.program && result.program.getSourceFile(target);
    if (!source) {
      if (result.parsed.errors.length && !configFailure) {
        configFailure = { ...base, verifier: 'typescript-project:' + config, status: 'fail', exit_code: 1, stderr: result.diagnostics, project_path: config };
      }
      continue;
    }
    return {
      ...base,
      verifier: 'typescript-project:' + config,
      status: result.failed ? 'fail' : 'pass',
      exit_code: result.failed ? 1 : 0,
      stderr: result.diagnostics,
      project_path: config,
      check_kind: source.scriptKind === ts.ScriptKind.JS || source.scriptKind === ts.ScriptKind.JSX
        ? (result.parsed.options.checkJs ? 'typecheck' : 'syntax') : 'typecheck',
      content_sha256: contents.get(path.resolve(target)) ? hash(contents.get(path.resolve(target))) : null,
    };
  }
  return configFailure || { ...base, reason: 'No project configuration includes this file' };
});

let stable = true;
for (const [file, before] of contents) {
  const after = readBytes(file);
  if (before === null ? after !== null : after === null || !before.equals(after)) stable = false;
}
for (const [file, before] of existence) {
  let after;
  try { after = fs.statSync(file).isFile(); } catch { after = false; }
  if (before !== after) stable = false;
}
for (const { ts, args, files } of directories.values()) {
  if (JSON.stringify(ts.sys.readDirectory(...args).sort()) !== JSON.stringify(files)) stable = false;
}
for (const [dir, before] of listings) {
  let after;
  try { after = fs.readdirSync(dir).filter((name) => /^(tsconfig|jsconfig)(\.[^.]+)*\.json$/.test(name)).sort(); }
  catch { after = []; }
  if (JSON.stringify([...before].sort()) !== JSON.stringify(after)) stable = false;
}
const inputDigest = hash(JSON.stringify([...contents].sort(([a], [b]) => a.localeCompare(b))
  .map(([file, bytes]) => [file, bytes === null ? null : hash(bytes)])));
for (const result of results) {
  result.input_digest = inputDigest;
  if (!stable && result.status === 'pass') {
    result.status = 'skipped';
    result.reason = 'Project inputs changed during verification';
    result.content_sha256 = null;
  }
}
process.stdout.write(JSON.stringify({ results, checked_project_count: projects.size }));
