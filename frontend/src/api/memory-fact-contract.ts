import { z } from 'zod';
import type { L2FactDisplay, MemoryCorrectionTargetKind } from './modules/memory';

const factDisplaySchema = z.object({
  display_text: z.string().trim().min(1),
  display_status: z.enum(['complete', 'partial', 'unavailable']),
  entity_name: z.string().nullable().optional(),
  target_entity_name: z.string().nullable().optional(),
  natural_summary: z.string().nullable().optional(),
  value_options: z.array(z.string()).nullable().optional(),
}).passthrough();

const assertionDisplaySchema = factDisplaySchema.extend({
  conflict_context: z.object({
    previous_display_text: z.string().nullable().optional(),
    current_display_text: z.string().nullable().optional(),
  }).passthrough().nullable().optional(),
});

const reviewDisplaySchema = z.object({
  proposed: factDisplaySchema,
}).passthrough();

const relationshipValueSchema = z.object({}).passthrough();

const correctionRecordDisplaySchema = (kind: MemoryCorrectionTargetKind) => {
  const content = kind === 'assertion' ? factDisplaySchema : relationshipValueSchema;
  return z.object({ before: content.nullable().optional(), replacement: content.nullable().optional() }).passthrough();
};

const portraitItemCorrectionSchema = z.object({
  assertion_id: z.string().nullable().optional(),
  correction_value: z.string().nullable().optional(),
  correction_trait_name: z.string().nullable().optional(),
  correction_value_options: z.array(z.string()).nullable().optional(),
}).passthrough().superRefine((item, ctx) => {
  if (!item.assertion_id) return;
  const required = z.object({
    display_status: z.enum(['complete', 'partial', 'unavailable']),
    correction_value: z.string(),
    correction_trait_name: z.string().min(1),
    correction_value_options: z.array(z.string()).nullable(),
  }).safeParse(item);
  if (!required.success) {
    for (const issue of required.error.issues) {
      ctx.addIssue({ code: 'custom', path: issue.path, message: issue.message });
    }
  }
});

const portraitItemListSchema = z.object({
  items: z.array(portraitItemCorrectionSchema),
}).passthrough();

const portraitCorrectionDisplaySchema = z.object({
  self_view: z.object({
    world: z.object({ groups: z.array(portraitItemListSchema) }).passthrough(),
    review: portraitItemListSchema,
    recent: portraitItemListSchema,
  }).passthrough(),
}).passthrough();

/** Validate the host-owned presentation fields without reshaping semantic data. */
export function parseFactDisplay(value: unknown): L2FactDisplay {
  return factDisplaySchema.parse(value);
}

export function validateAssertionDisplay(value: unknown): asserts value is L2FactDisplay {
  assertionDisplaySchema.parse(value);
}

/** Pending reviews share the fact display contract through their proposal. */
export function validateReviewDisplay(value: unknown): asserts value is { proposed: L2FactDisplay } {
  reviewDisplaySchema.parse(value);
}

export function validateCorrectionCommandDisplay(value: unknown, kind: MemoryCorrectionTargetKind): void {
  z.object({
    correction: correctionRecordDisplaySchema(kind),
    current_claim: (kind === 'assertion' ? factDisplaySchema : relationshipValueSchema).nullable().optional(),
  }).passthrough().parse(value);
}

export function validateCorrectionHistoryDisplay(value: unknown, kind: MemoryCorrectionTargetKind): void {
  z.object({
    versions: z.array(kind === 'assertion' ? factDisplaySchema : relationshipValueSchema),
    corrections: z.array(correctionRecordDisplaySchema(kind)),
  }).passthrough().parse(value);
}

export function validateMemorySearchDisplay(value: unknown): void {
  const result = z.object({ l2_assertions: z.array(assertionDisplaySchema).optional() }).passthrough().parse(value);
  for (const items of Object.values(result)) {
    if (!Array.isArray(items)) continue;
    const rows: unknown[] = items;
    for (const item of rows) {
      if (typeof item === 'object' && item !== null && 'assertion_id' in item) {
        validateAssertionDisplay(item);
      }
    }
  }
}

export function validatePortraitCorrectionDisplay(value: unknown): void {
  portraitCorrectionDisplaySchema.parse(value);
}
