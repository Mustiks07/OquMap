import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAppState, filtersParam } from "../state/AppState";
import { api } from "./client";
import type {
  AiStatus,
  ComparisonRequest,
  ComparisonResult,
  Curriculum,
  DatasetSummary,
  DecisionOut,
  DocumentOut,
  Envelope,
  FragmentLink,
  GenerationOut,
  ItemLink,
  JobOut,
  OverviewResult,
  PlanContext,
  PlanResult,
  PlanSolveRequest,
  QualityReport,
  SearchResult,
  SourceOut,
  TopicEvidenceResult,
} from "./types";

export interface PublicConfig {
  deployment_mode: "dev" | "public_demo" | "production";
  demo_login_enabled: boolean;
  qa_personas_enabled: boolean;
  password_login_enabled: boolean;
  demo_tenant_ttl_hours: number | null;
  live_ai_configured: boolean;
  llm_config_error: string | null;
  lab_scenarios: string[];
  recommended_dataset_code: string;
}

export function useConfig() {
  return useQuery({ queryKey: ["config"], queryFn: () => api.get<PublicConfig>("/api/v1/config"), staleTime: 300_000 });
}

export interface ProjectStatus {
  dataset_id: string;
  stages: { kind: string; done: boolean; blocked_by: string[]; blocked_message: string | null }[];
  counts: Record<string, number>;
}

export function useProject(id: string | null) {
  return useQuery({ queryKey: ["project", id], enabled: !!id, queryFn: () => api.get<ProjectStatus>(`/api/v1/datasets/${id}/project`) });
}

export function useDatasets() {
  return useQuery({ queryKey: ["datasets"], queryFn: () => api.get<DatasetSummary[]>("/api/v1/datasets") });
}

export function useCurrentDataset() {
  const { datasetId } = useAppState();
  const q = useDatasets();
  return { ...q, dataset: q.data?.find((d) => d.id === datasetId) ?? null };
}

export function useCurriculum() {
  const { datasetId } = useAppState();
  return useQuery({
    queryKey: ["curriculum", datasetId],
    enabled: !!datasetId,
    queryFn: () => api.get<Curriculum>("/api/v1/curriculum", { dataset_id: datasetId! }),
  });
}

export function useQuality() {
  const { datasetId } = useAppState();
  return useQuery({
    queryKey: ["quality", datasetId],
    enabled: !!datasetId,
    queryFn: () => api.get<QualityReport>(`/api/v1/datasets/${datasetId}/quality`),
  });
}

/** Analyses are keyed by dataset version so a data change triggers a recomputation instead of reusing stale numbers. */
export function useOverview() {
  const { datasetId, filters } = useAppState();
  const { dataset } = useCurrentDataset();
  return useQuery({
    queryKey: ["overview", datasetId, dataset?.version, filtersParam(filters)],
    enabled: !!datasetId,
    queryFn: () => api.post<Envelope<OverviewResult>>(`/api/v1/datasets/${datasetId}/overview`, filters),
  });
}

export function useTopicEvidence(topicId: string | null) {
  const { datasetId, filters } = useAppState();
  const { dataset } = useCurrentDataset();
  return useQuery({
    queryKey: ["topic", datasetId, topicId, dataset?.version, filtersParam(filters)],
    enabled: !!datasetId && !!topicId,
    queryFn: () =>
      api.get<Envelope<TopicEvidenceResult>>(`/api/v1/topics/${topicId}/evidence`, { dataset_id: datasetId!, filters: filtersParam(filters) }),
  });
}

export function useComparison() {
  return useMutation({ mutationFn: (body: ComparisonRequest) => api.post<Envelope<ComparisonResult>>("/api/v1/comparisons", body) });
}

export function usePlanContext() {
  const { datasetId, filters } = useAppState();
  const { dataset } = useCurrentDataset();
  return useQuery({
    queryKey: ["plan-context", datasetId, dataset?.version, filtersParam(filters)],
    enabled: !!datasetId,
    queryFn: () => api.get<PlanContext>("/api/v1/plans/context", { dataset_id: datasetId!, filters: filtersParam(filters) }),
  });
}

export function useSolve() {
  return useMutation({ mutationFn: (body: PlanSolveRequest) => api.post<Envelope<PlanResult>>("/api/v1/plans/solve", body) });
}

export function useDocuments() {
  return useQuery({ queryKey: ["documents"], queryFn: () => api.get<DocumentOut[]>("/api/v1/documents") });
}

export function useDocument(id: string | null) {
  return useQuery({
    queryKey: ["document", id],
    enabled: !!id,
    queryFn: () =>
      api.get<{ document: DocumentOut; fragments: { id: string; anchor: string; page_physical: number | null; page_printed: string | null; heading: string | null; text: string }[]; links: FragmentLink[] }>(
        `/api/v1/documents/${id}`,
      ),
  });
}

export function useItemLinks() {
  return useQuery({ queryKey: ["item-links"], queryFn: () => api.get<{ item_links: ItemLink[]; fragment_links: FragmentLink[] }>("/api/v1/mappings") });
}

export function useReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "confirm" | "reject" }) =>
      api.post<{ link_id: string; status: string; datasets_bumped: unknown[] }>(`/api/v1/mappings/${id}/review`, { decision }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["document"] });
      qc.invalidateQueries({ queryKey: ["item-links"] });
      qc.invalidateQueries({ queryKey: ["datasets"] });
      qc.invalidateQueries({ queryKey: ["topic"] });
    },
  });
}

export function useSearch(q: string) {
  return useQuery({
    queryKey: ["search", q],
    enabled: q.trim().length > 2,
    queryFn: () => api.get<{ query: string; results: SearchResult[] }>("/api/v1/sources/search", { q }),
  });
}

export function useSource(id: string | null) {
  return useQuery({ queryKey: ["source", id], enabled: !!id, queryFn: () => api.get<SourceOut>(`/api/v1/sources/${id}`) });
}

export function useAiStatus() {
  return useQuery({ queryKey: ["ai-status"], queryFn: () => api.get<AiStatus>("/api/v1/ai/status"), staleTime: 60_000 });
}

export function useGenerate<B>(path: string) {
  return useMutation({ mutationFn: (body: B) => api.post<GenerationOut>(path, body) });
}

export function useDecision(id: string | null) {
  return useQuery({ queryKey: ["decision", id], enabled: !!id, queryFn: () => api.get<DecisionOut>(`/api/v1/decisions/${id}`) });
}

export function useDecisions() {
  const { datasetId } = useAppState();
  return useQuery({
    queryKey: ["decisions", datasetId],
    enabled: !!datasetId,
    queryFn: () =>
      api.get<{ id: string; version: number; status: string; target_group: string; problem: string; topic_code: string | null; created_at: string; outcome_status: string | null }[]>(
        "/api/v1/decisions",
        { dataset_id: datasetId! },
      ),
  });
}

export async function pollJob(id: string, onUpdate?: (j: JobOut) => void, timeoutMs = 120_000): Promise<JobOut> {
  const start = Date.now();
  for (;;) {
    const j = await api.get<JobOut>(`/api/v1/jobs/${id}`);
    onUpdate?.(j);
    if (j.status === "succeeded" || j.status === "failed" || j.status === "cancelled") return j;
    if (Date.now() - start > timeoutMs) return j;
    await new Promise((r) => setTimeout(r, 700));
  }
}
