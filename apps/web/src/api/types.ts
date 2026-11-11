/** Type aliases over the generated OpenAPI schema (src/api/schema.d.ts — regenerate with `npm run gen:types`). */
import type { components } from "./schema";

type S = components["schemas"];

export type UserOut = S["UserOut"];
export type LoginResponse = S["LoginResponse"];
export type DatasetSummary = S["DatasetSummary"];
export type AnalysisContext = S["AnalysisContext"];
export type MeanSummary = S["MeanSummary"];
export type OverviewResult = S["OverviewResult"];
export type TopicOverviewRow = S["TopicOverviewRow"];
export type TopicEvidenceResult = S["TopicEvidenceResult"];
export type ItemEvidence = S["ItemEvidence"];
export type ObjectiveEvidence = S["ObjectiveEvidence"];
export type Misconception = S["Misconception"];
export type SourceRef = S["SourceRef"];
export type ComparisonResult = S["ComparisonResult"];
export type Reason = S["Reason"];
export type PlanResult = S["PlanResult"];
export type PlanScenario = S["PlanScenario"];
export type PlanChange = S["PlanChange"];
export type JobOut = S["JobOut"];
export type ImportBatchOut = S["ImportBatchOut"];
export type GenerationOut = S["GenerationOut"];
export type AssistantAnswer = S["AssistantAnswer"];
export type DecisionOut = S["DecisionOut"];
export type FollowUpResponse = S["FollowUpResponse"];
export type SourceOut = S["SourceOut"];
export type Filters = S["Filters"];

export interface Envelope<T> {
  context: AnalysisContext;
  result: T;
}

export interface Curriculum {
  program: { id: string; title: string; subject: string; grade: number; version: string; source: string; is_demo_codes: boolean };
  topics: { id: string; code: string; title_ru: string; title_kz: string; kz_verified: boolean; order: number }[];
  objectives: { id: string; code: string; topic_id: string; text_ru: string; text_kz: string; kz_verified: boolean }[];
  relations: { source: string; target: string; type: string; confirmed: boolean }[];
  editions: { id: string; code: string; title: string; edition_label: string; year: number; language: string; is_demo: boolean; document_id: string | null }[];
  schools: { id: string; code: string; name: string }[];
  cohorts: { id: string; code: string; school_id: string; language: string; academic_year: string }[];
  assessments: { id: string; code: string; stage: string; form: string; scale: string }[];
  strata_schemes: string[];
  weight_modes: string[];
}

export interface PlanContextTopic {
  topic_id: string;
  code: string;
  title_ru: string;
  title_kz: string;
  current_hours: number;
  elapsed_hours: number;
  min_hours: number | null;
  max_hours: number | null;
  actual_hours: number | null;
  priority: number;
  priority_basis: string;
  topic_status: string | null;
  score: number | null;
  recommend_diagnostic: boolean;
}

export interface PlanContext {
  plan: { id: string; name: string; scope: string; horizon: string; version: number; status: string } | null;
  topics: PlanContextTopic[];
  budget: number;
  priority_rule: string;
  weights_version: string;
  source_analysis_id: string;
  is_calendar: boolean;
  illustration_20h: { budget: number; topics: { code: string; title: string; current_hours: number; min_hours?: number; max_hours?: number; priority: number }[] };
}

export interface QualityReport {
  dataset: DatasetSummary;
  counts: Record<string, number>;
  assessments: {
    assessment_id: string; code: string; stage: string; form: string; scale: string; linking_method: string;
    administered_on: string | null; n_responses: number; omitted: number; retake_rows: number; present: number; absent: number; n_items: number;
  }[];
  imports: ImportBatchOut[];
  data_level: string;
  capabilities: { possible: string[]; missing: string[] };
  editions_in_use: string[];
  versions: { version: number; reason: string; at: string; import_batch_id: string | null }[];
}

export interface DocumentOut {
  id: string; filename: string; media_type: string; sha256: string; version: number; status: string;
  page_count: number | null; ocr_status: string; edition_id: string | null; is_demo: boolean;
  extraction_report: Record<string, unknown>; created_at: string;
}

export interface FragmentLink {
  link_id: string; kind: "fragment"; fragment_id: string; anchor: string; page_physical: number | null; page_printed: string | null;
  objective_id: string; objective_code: string; objective_text_ru: string; status: string; origin: string; rationale: string;
  generation_id: string | null; reviewed_at: string | null;
}

export interface ItemLink {
  link_id: string; kind: "item"; item_id: string; item_code: string; stem_ru: string; objective_id: string;
  objective_code: string; objective_text_ru: string; weight: number; status: string; origin: string;
}

export interface SearchResult {
  source_id: string; document_id: string; document_filename: string; document_version: number; edition_code: string | null;
  anchor: string; page_physical: number | null; page_printed: string | null; excerpt: string; score: number;
  relevance: { matched_terms: string[]; query_terms: string[] };
}

export interface AiCapabilities {
  structured_output: boolean; tool_calling: boolean; parallel_tools: boolean; vision_pdf: boolean; streaming: boolean;
  max_context_tokens: number | null; max_output_tokens: number | null; probed: boolean; notes: string[];
}

export interface AiStatus {
  provider: string; model: string | null; mode: "live_model" | "recorded_demo" | "template"; live_available: boolean;
  config_error: string | null; live_blocked_reason: string | null; probe_error: string | null;
  capabilities: AiCapabilities; data_policy: string; data_policy_note_ru: string | null; real_data_allowed: boolean;
  fallback_chain: string[]; fallback_modes: string[]; ocr_engine: string; ocr_available: boolean; note_ru: string | null;
}

export type ComparisonRequest = S["ComparisonRequest"];
export type PlanSolveRequest = S["PlanSolveRequest"];
export type TopicInput = S["TopicInput"];
export type DecisionCreate = S["DecisionCreate"];
