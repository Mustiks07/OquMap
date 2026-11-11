/** Data access for the measurement & learning-loop screens. Types are aliases over the generated OpenAPI schema. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, request } from "../../api/client";
import type { components } from "../../api/schema";

type S = components["schemas"];
export type Message = S["Message"];
export type Label = S["Label"];
export type AssessmentQualityList = S["AssessmentQualityList"];
export type AssessmentQualitySummary = S["AssessmentQualitySummary"];
export type AssessmentQualityOut = S["AssessmentQualityOut"];
export type ItemQuality = S["ItemQuality"];
export type ItemQualityDetail = S["ItemQualityDetail"];
export type InterventionListItem = S["InterventionListItem"];
export type InterventionOut = S["InterventionOut"];
export type InterventionVersionOut = S["InterventionVersionOut"];
export type SuggestionsOut = S["SuggestionsOut"];
export type PilotOut = S["PilotOut"];
export type PilotListItem = S["PilotListItem"];
export type FidelityOut = S["FidelityOut"];
export type FidelityMetrics = S["FidelityMetrics"];
export type FidelityLogOut = S["FidelityLogOut"];
export type PilotOutcomeOut = S["PilotOutcomeOut"];
export type ConclusionOut = S["ConclusionOut"];
export type PortfolioOut = S["PortfolioOut"];
export type LearningSummary = S["LearningSummary"];
export type InterventionCreate = S["InterventionCreate"];
export type PilotCreate = S["PilotCreate"];
export type FidelityLogCreate = S["FidelityLogCreate"];
export type ConclusionCreate = S["ConclusionCreate"];

export interface QualityRules {
  attempt_rule: "first" | "last";
  omitted_policy: "as_incorrect" | "exclude";
}

export function useQualityList(datasetId: string | null, rules: QualityRules) {
  return useQuery({
    queryKey: ["m-quality-list", datasetId, rules],
    queryFn: () => api.get<AssessmentQualityList>("/api/v1/quality/assessments", { dataset_id: datasetId ?? undefined, ...rules }),
  });
}

export function useAssessmentQuality(id: string | undefined, rules: QualityRules) {
  return useQuery({
    queryKey: ["m-quality", id, rules],
    enabled: !!id,
    queryFn: () => api.get<AssessmentQualityOut>(`/api/v1/quality/assessments/${id}`, { ...rules }),
  });
}

export function useItemQuality(id: string | null) {
  return useQuery({ queryKey: ["m-item", id], enabled: !!id, queryFn: () => api.get<ItemQualityDetail>(`/api/v1/quality/items/${id}`) });
}

export interface InterventionFilters {
  status?: string;
  evidence_level?: string;
  topic_id?: string;
  misconception?: string;
  q?: string;
}

export function useInterventions(f: InterventionFilters) {
  return useQuery({
    queryKey: ["m-interventions", f],
    queryFn: () => api.get<InterventionListItem[]>("/api/v1/interventions", { ...f } as Record<string, string | undefined>),
  });
}

export function useIntervention(id: string | undefined) {
  return useQuery({ queryKey: ["m-intervention", id], enabled: !!id, queryFn: () => api.get<InterventionOut>(`/api/v1/interventions/${id}`) });
}

export function useSuggestions(params: Record<string, string | undefined> | null) {
  return useQuery({
    queryKey: ["m-suggest", params],
    enabled: !!params,
    queryFn: () => api.get<SuggestionsOut>("/api/v1/interventions/suggest", params ?? {}),
  });
}

export function usePilots(datasetId: string | null) {
  return useQuery({
    queryKey: ["m-pilots", datasetId],
    queryFn: () => api.get<PilotListItem[]>("/api/v1/pilots", { dataset_id: datasetId ?? undefined }),
  });
}

export function usePilot(id: string | undefined) {
  return useQuery({ queryKey: ["m-pilot", id], enabled: !!id, queryFn: () => api.get<PilotOut>(`/api/v1/pilots/${id}`) });
}

export function useFidelity(id: string | undefined) {
  return useQuery({ queryKey: ["m-fidelity", id], enabled: !!id, queryFn: () => api.get<FidelityOut>(`/api/v1/pilots/${id}/fidelity`) });
}

export function useOutcomes(id: string | undefined) {
  return useQuery({ queryKey: ["m-outcomes", id], enabled: !!id, queryFn: () => api.get<PilotOutcomeOut[]>(`/api/v1/pilots/${id}/outcomes`) });
}

export function useConclusions(id: string | undefined) {
  return useQuery({ queryKey: ["m-conclusions", id], enabled: !!id, queryFn: () => api.get<ConclusionOut[]>(`/api/v1/pilots/${id}/conclusions`) });
}

export function usePortfolio(datasetId: string | null) {
  return useQuery({
    queryKey: ["m-portfolio", datasetId],
    queryFn: () => api.get<PortfolioOut>("/api/v1/portfolio/interventions", { dataset_id: datasetId ?? undefined }),
  });
}

export function useLearning(datasetId: string | null) {
  return useQuery({
    queryKey: ["m-learning", datasetId],
    queryFn: () => api.get<LearningSummary>("/api/v1/learning/summary", { dataset_id: datasetId ?? undefined }),
  });
}

/** Generic mutation that refreshes every measurement query afterwards. */
export function useMAction<B, R>(method: "POST" | "PATCH" | "DELETE", path: (vars: B) => string, body?: (vars: B) => unknown) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: B) => request<R>(method, path(vars), method === "DELETE" ? undefined : (body ? body(vars) : vars) ?? {}),
    onSuccess: () => {
      for (const k of ["m-interventions", "m-intervention", "m-suggest", "m-pilots", "m-pilot", "m-fidelity", "m-outcomes", "m-conclusions",
        "m-portfolio", "m-learning", "decisions"]) {
        qc.invalidateQueries({ queryKey: [k] });
      }
    },
  });
}
