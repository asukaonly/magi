import { test } from 'node:test';
import assert from 'node:assert/strict';
import { compareTranslations } from './check-i18n.mjs';
test('accepts locale-specific plural forms', () => {
  assert.deepEqual(compareTranslations({ items_one: 'One item', items_other: '{{count}} items' }, { items: '{{count}} 项' }), []);
});
test('rejects missing keys, wrong arguments and incomplete plurals', () => {
  assert.equal(compareTranslations({ text: '{{path}}' }, {}).length, 1);
  assert.equal(compareTranslations({ text: '{{path}}' }, { text: '{{name}}' }).length, 1);
  assert.throws(() => compareTranslations({ items_one: 'One' }, { items: '{{count}} 项' }), /requires other/);
});
