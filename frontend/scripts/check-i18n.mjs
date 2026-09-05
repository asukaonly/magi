import { readdir, readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

function flatten(value, prefix = '', output = new Map()) {
  for (const [key, entry] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (entry && typeof entry === 'object' && !Array.isArray(entry)) flatten(entry, path, output);
    else if (typeof entry === 'string') output.set(path, entry);
    else throw new Error(`Translation must be a string: ${path}`);
  }
  return output;
}
const pluralSuffix = /_(zero|one|two|few|many|other)$/;
const placeholders = (text) => [...new Set([...text.matchAll(/{{-?\s*([\w.]+)/g)].map((match) => match[1]))].sort();

function normalize(messages, locale) {
  const flat = flatten(messages);
  const result = new Map();
  for (const [key, text] of flat) {
    const match = key.match(pluralSuffix);
    if (match && !flat.has(key.replace(pluralSuffix, '_other'))) throw new Error(`Plural requires other: ${locale}:${key}`);
    const name = key.replace(pluralSuffix, '');
    const params = placeholders(text);
    // A singular English phrase may spell out "one"; count is provided by the caller.
    if (match && !params.includes('count')) params.push('count');
    const current = result.get(name) ?? new Set();
    for (const param of params) current.add(param);
    result.set(name, current);
  }
  return result;
}

export function compareTranslations(english, chinese) {
  const en = normalize(english, 'en');
  const zh = normalize(chinese, 'zh-CN');
  const errors = [];
  for (const key of new Set([...en.keys(), ...zh.keys()])) {
    if (!en.has(key) || !zh.has(key)) { errors.push(`Missing ${en.has(key) ? 'zh-CN' : 'en'} key: ${key}`); continue; }
    const left = [...en.get(key)].sort();
    const right = [...zh.get(key)].sort();
    if (left.join(',') !== right.join(',')) errors.push(`Interpolation mismatch: ${key} (${left} / ${right})`);
  }
  return errors;
}

async function main() {
  const root = new URL('../src/i18n/locales/', import.meta.url);
  const enFiles = (await readdir(new URL('en/', root))).filter((name) => name.endsWith('.json')).sort();
  const zhFiles = (await readdir(new URL('zh-CN/', root))).filter((name) => name.endsWith('.json')).sort();
  if (enFiles.join() !== zhFiles.join()) throw new Error('Translation namespaces differ');
  const errors = [];
  for (const file of enFiles) {
    const en = JSON.parse(await readFile(new URL(`en/${file}`, root), 'utf8'));
    const zh = JSON.parse(await readFile(new URL(`zh-CN/${file}`, root), 'utf8'));
    errors.push(...compareTranslations(en, zh).map((error) => `${file}: ${error}`));
  }
  if (errors.length) throw new Error(errors.join('\n'));
  console.log('Translation keys and interpolation arguments are aligned.');
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
