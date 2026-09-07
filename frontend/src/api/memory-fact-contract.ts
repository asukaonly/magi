import { z } from 'zod';
import type { L2FactDisplay } from './modules/memory';

const factDisplaySchema = z.object({
  display_text: z.string().nullable().optional(),
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

const correctionRecordDisplaySchema = z.object({
  before: factDisplaySchema.nullable().optional(),
  replacement: factDisplaySchema.nullable().optional(),
}).passthrough();

const correctionCommandDisplaySchema = z.object({
  correction: correctionRecordDisplaySchema,
  current_claim: factDisplaySchema.nullable().optional(),
}).passthrough();

const correctionHistoryDisplaySchema = z.object({
  versions: z.array(factDisplaySchema),
  corrections: z.array(correctionRecordDisplaySchema),
}).passthrough();

const portraitItemCorrectionSchema = z.object({
  correction_value: z.string().nullable().optional(),
  correction_trait_name: z.string().nullable().optional(),
  correction_value_options: z.array(z.string()).nullable().optional(),
}).passthrough();

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
export function validateAssertionDisplay(value: unknown): asserts value is L2FactDisplay {
  assertionDisplaySchema.parse(value);
}

/** Pending reviews share the fact display contract through their proposal. */
export function validateReviewDisplay(value: unknown): asserts value is { proposed: L2FactDisplay } {
  reviewDisplaySchema.parse(value);
}

export function validateCorrectionCommandDisplay(value: unknown): void {
  correctionCommandDisplaySchema.parse(value);
}

export function validateCorrectionHistoryDisplay(value: unknown): void {
  correctionHistoryDisplaySchema.parse(value);
}

export function validatePortraitCorrectionDisplay(value: unknown): void {
  portraitCorrectionDisplaySchema.parse(value);
}
