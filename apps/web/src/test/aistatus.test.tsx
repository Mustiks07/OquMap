import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "../i18n/I18n";
import { AiStatusCard } from "../features/AiStatusCard";
import type { AiStatus } from "../api/types";

const caps = { structured_output: true, tool_calling: true, parallel_tools: false, vision_pdf: false, streaming: false,
  max_context_tokens: 1048576, max_output_tokens: 65536, probed: false, notes: [] };

function show(status: AiStatus) {
  const qc = new QueryClient();
  qc.setQueryData(["ai-status"], status);
  render(<QueryClientProvider client={qc}><I18nProvider initial="ru"><AiStatusCard /></I18nProvider></QueryClientProvider>);
}

test("free-tier Gemini shows the actual provider, model, mode and a data-policy warning", () => {
  show({ provider: "gemini", model: "gemini-2.5-flash", mode: "template", live_available: false, config_error: null,
    live_blocked_reason: "live_disabled_for_public_demo", probe_error: null, capabilities: caps, data_policy: "may_train",
    data_policy_note_ru: "Бесплатный тариф: запросы могут использоваться для обучения. Только синтетические данные.",
    real_data_allowed: false, fallback_chain: [], fallback_modes: ["recorded_demo", "template"], ocr_engine: "none",
    ocr_available: false, note_ru: null });
  expect(screen.getByText("gemini · gemini-2.5-flash")).toBeInTheDocument();
  expect(screen.getByText("Шаблон без модели")).toBeInTheDocument();
  expect(screen.getByTestId("ai-policy-warning")).toHaveTextContent("обучения");
  expect(screen.getByText(/в публичном демо живая модель отключена/)).toBeInTheDocument();
});
