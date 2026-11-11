/** Types and hooks for the evidence graph, agent council, decision sandbox, diagnostic quizzes and the tour. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { useAppState, filtersParam } from "../state/AppState";
import { useCurrentDataset } from "./hooks";
import type { GenerationOut } from "./types";

export type NodeKind = "topic" | "prerequisite" | "objective" | "item" | "misconception" | "source" | "hours" | "decision" | "followup" | "gap";

export interface GraphNode {
  id: string; kind: NodeKind; label_ru: string; label_kz: string; status: string; code?: string;
  metrics: Record<string, number | string | null | undefined>; excerpt?: string; check_ru?: string;
  open: null | { type: "calculation" | "item" | "source" | "plan" | "decision"; analysis_id?: string; path?: string; source_id?: string;
    plan_id?: string; decision_id?: string; rules?: Record<string, string> };
}
export interface GraphEdge { from: string; to: string; kind: string }
export interface GraphResult {
  topic: { topic_id: string; code: string; title_ru: string; title_kz: string };
  status: string; nodes: GraphNode[]; edges: GraphEdge[]; path: string[]; gaps: GraphNode[]; note_ru: string;
}
export interface Envelope<T> { context: { analysis_id: string; dataset_version: number; current_dataset_version: number; method_version: string; is_stale: boolean }; result: T }

export function useGraph(topicId: string | null) {
  const { datasetId, filters } = useAppState();
  const { dataset } = useCurrentDataset();
  return useQuery({
    queryKey: ["graph", datasetId, topicId, dataset?.version, filtersParam(filters)],
    enabled: !!datasetId && !!topicId,
    queryFn: () => api.get<Envelope<GraphResult>>(`/api/v1/topics/${topicId}/graph`, { dataset_id: datasetId!, filters: filtersParam(filters) }),
  });
}

export function useAnalysis(id: string | null | undefined) {
  return useQuery({ queryKey: ["analysis", id], enabled: !!id, queryFn: () => api.get<Envelope<Record<string, unknown>>>(`/api/v1/analyses/${id}`) });
}

// ---- council ------------------------------------------------------------------------------------
export interface CouncilClaim { id: string; role: string; kind: string; text: string; evidence_ids: string[] }
export interface CouncilVerdict { claim_id: string; role: string; kind: string; verdict: "accepted" | "weakened" | "blocked"; reasons: string[]; reasons_ru: string[] }
export interface CouncilStep {
  n: number; role: string; role_label: string; action: "plan" | "tool" | "statement" | "critique" | "final";
  tool?: string; input?: Record<string, unknown>; output_ref?: Record<string, unknown>; facts?: string[]; blocked?: string;
  claim?: CouncilClaim; verdict?: string; reasons_ru?: string[]; claim_id?: string; note_ru?: string; mode?: string;
}
export interface CouncilOutput {
  topic: { code: string; title_ru: string }; dataset_version: number; roles: Record<string, string>;
  role_modes: Record<string, { mode: string; provider?: string; model?: string | null; fallback_reason?: string | null }>;
  steps: CouncilStep[]; facts: { id: string; label_ru: string; value: unknown; provenance: Record<string, unknown> }[];
  claims: CouncilClaim[]; verdicts: CouncilVerdict[]; agreements: { claims: string[]; text_ru: string }[];
  disagreements: { claim_id: string; verdict: string; text_ru: string }[]; highlight: CouncilVerdict | null;
  final: { claim: string; evidence_ids: string[]; limitations: string[]; recommended_action: string; verification_plan: string };
  note_ru: string;
}
export function useCouncil() {
  return useMutation({ mutationFn: (b: { dataset_id: string; topic_id: string; lang: string }) => api.post<GenerationOut>("/api/v1/ai/council", b) });
}

// ---- sandbox ------------------------------------------------------------------------------------
export interface Op { op: string; topic?: string | null; value?: number | null }
export interface DiffRow { topic: string | null; field: string; before: unknown; after: unknown }
export interface IntentPreview { ops: Op[]; all_ops: Op[]; diff: DiffRow[]; not_understood: string[]; mode: string; note_ru: string }
export interface SandboxMetrics {
  objective_coverage: { covered: number; total: number }; weak_topics: string[]; hours_on_weak_topics: number; total_hours: number;
  risks: { code: string; topic: string; text_ru: string }[]; prerequisite_risks: { code: string; topic: string; for: string[]; text_ru: string }[];
}
export interface SandboxScenario {
  name: string; ops: Op[]; diff: DiffRow[]; status: string; status_message_ru: string; plan_analysis_id: string; budget: number;
  hours?: Record<string, number>; metrics?: SandboxMetrics; validation?: { valid: boolean } | null;
  conflict?: { constraints: { message_ru?: string; label_ru?: string; code?: string }[]; message_ru?: string } | null;
}
export interface SandboxResult {
  before: { hours: Record<string, number>; metrics: SandboxMetrics; budget: number }; scenarios: SandboxScenario[];
  topics: { code: string; title_ru: string; title_kz: string; status: string | null; score: number | null }[]; note_ru: string;
}

// ---- quizzes ------------------------------------------------------------------------------------
export interface QuizOption { key: string; text: string; correct: boolean; misconception: string | null; rationale_ru: string; rationale_kz: string }
export interface QuizItem {
  code: string; family?: string; params?: Record<string, number>; objective_id: string; objective_code: string; stem_ru: string; stem_kz: string;
  options: QuizOption[]; answer_key: string; rubric_ru: string; rubric_kz: string; difficulty: string; target_misconception?: string;
  evidence_ids: string[]; evidence_note_ru?: string; teacher_key_verified?: boolean;
}
export interface QuizCheck { code: string; passed: boolean; blocking: boolean; detail: string }
export interface Quiz {
  id: string | null; title: string; status: string; current_version?: number; counts_toward_grade: false; items: QuizItem[];
  checks: { items: Record<string, QuizCheck[]>; quiz: QuizCheck[]; blocking_failed: string[]; approvable: boolean };
  versions?: { version: number; author_kind: string; created_at: string; note: string | null; approvable: boolean }[];
  response_sets?: { id: string; n_learners: number; summary: { items: Record<string, { n: number; p_correct: number | null }>; hypotheses: Record<string, { n_learners: number; share: number | null }>; n_rejected: number } }[];
  note_ru?: string;
}
export function useQuizzes() {
  const { datasetId } = useAppState();
  return useQuery({ queryKey: ["quizzes", datasetId], enabled: !!datasetId,
    queryFn: () => api.get<{ id: string; title: string; status: string; current_version: number; topic_id: string }[]>("/api/v1/quizzes", { dataset_id: datasetId! }) });
}
export function useQuiz(id: string | null) {
  return useQuery({ queryKey: ["quiz", id], enabled: !!id, queryFn: () => api.get<Quiz>(`/api/v1/quizzes/${id}`) });
}
export function useQuizMutation<B>(fn: (b: B) => Promise<Quiz>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: (q) => { if (q.id) qc.setQueryData(["quiz", q.id], q); qc.invalidateQueries({ queryKey: ["quizzes"] }); } });
}

// ---- tour ---------------------------------------------------------------------------------------
export interface Preflight {
  ready: boolean; checks: { code: string; ok: boolean; detail: unknown; ms: number }[]; topic_id: string | null; topic_code?: string;
  edition_ids?: string[]; dataset_version?: number; total_ms?: number;
}
export function usePreflight() {
  const { datasetId } = useAppState();
  return useQuery({ queryKey: ["preflight", datasetId], enabled: !!datasetId, staleTime: 0,
    queryFn: () => api.get<Preflight>("/api/v1/demo/tour/preflight", { dataset_id: datasetId! }) });
}
