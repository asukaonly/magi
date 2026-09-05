import { readFile, writeFile, mkdir } from 'node:fs/promises';
import openapiTS, { astToString } from 'openapi-typescript';
import Ajv from 'ajv/dist/2020.js';
import standaloneCode from 'ajv/dist/standalone/index.js';

const contractUrl = new URL('../../contracts/api/frontend-config.json', import.meta.url);
const outputDir = new URL('../src/api/generated/', import.meta.url);
const schema = JSON.parse(await readFile(contractUrl, 'utf8'));
const header = '// Generated from production response schemas. Run npm run contracts:generate.\n';
const types = header + astToString(await openapiTS(schema, { defaultNonNullable: false }));
// Timestamps remain strings in the UI; semantic datetime rules stay with their owner.
const ajv = new Ajv({ strict: false, inlineRefs: false, allErrors: false, formats: { 'date-time': true }, code: { source: true, esm: true, lines: true } });
// Compile ahead of time: desktop WebViews never need eval or a runtime schema compiler.
ajv.addSchema({ $id: 'magi-config', components: schema.components });
const names = ['ConfigResponse', 'OnboardingStatusResponse', 'OnboardingTemplateResponse'];
const validators = header + standaloneCode(ajv, Object.fromEntries(names.map((name) =>
  ['validate' + name, 'magi-config#/components/schemas/' + name])));
if (/\brequire\s*\(|\beval\s*\(|\bnew Function\b/.test(validators)) {
  throw new Error('Generated validators must run without Node imports or dynamic evaluation');
}
const declarations = header +
  "import type { components } from './config-types';\n" +
  names.map((name) => 'export declare function validate' + name +
    "(value: unknown): value is components['schemas']['" + name + "'];").join('\n') + '\n';
const outputs = { 'config-types.ts': types, 'config-validators.js': validators, 'config-validators.d.ts': declarations };
if (!process.argv.includes('--check')) await mkdir(outputDir, { recursive: true });
for (const [name, content] of Object.entries(outputs)) {
  const target = new URL(name, outputDir);
  if (process.argv.includes('--check')) {
    const current = await readFile(target, 'utf8').catch(() => '');
    if (current !== content) throw new Error(name + ' is stale; run npm run contracts:generate');
  } else {
    await writeFile(target, content);
  }
}
