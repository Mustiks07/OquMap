import { render, screen } from "@testing-library/react";
import { I18nProvider } from "../i18n/I18n";
import { ErrorState, ModeBadge, StaleBanner, QueryView } from "../ui";
import { ApiError } from "../api/client";

const wrap = (n: React.ReactNode) => render(<I18nProvider initial="ru">{n}</I18nProvider>);

test("stale banner is shown only for stale analyses", () => {
  const { rerender } = wrap(<StaleBanner ctx={{ is_stale: false, dataset_version: 1, current_dataset_version: 1 }} />);
  expect(screen.queryByText("Анализ устарел")).toBeNull();
  rerender(<I18nProvider initial="ru"><StaleBanner ctx={{ is_stale: true, dataset_version: 1, current_dataset_version: 2 }} /></I18nProvider>);
  expect(screen.getByText("Анализ устарел")).toBeInTheDocument();
});

test("AI mode is always visible to the user", () => {
  wrap(<ModeBadge mode="template" fallback="model_not_configured" />);
  expect(screen.getByText("Шаблон без модели")).toBeInTheDocument();
  expect(screen.getByText("model_not_configured")).toBeInTheDocument();
});

test("error state shows the request id and a retry button", () => {
  wrap(<ErrorState error={new ApiError(404, "not_found", "dataset not found", {}, "abc123")} onRetry={() => {}} />);
  expect(screen.getByText("abc123")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument();
});

test("query view renders loading and empty states", () => {
  const base = { isError: false, error: null, refetch: () => {} };
  const { rerender } = wrap(<QueryView q={{ ...base, isLoading: true, data: undefined }}>{() => <span>data</span>}</QueryView>);
  expect(screen.getByRole("status")).toBeInTheDocument();
  rerender(<I18nProvider initial="ru"><QueryView q={{ ...base, isLoading: false, data: [] as number[] }} empty={(d) => d.length === 0}>{() => <span>data</span>}</QueryView></I18nProvider>);
  expect(screen.getByText("Нет данных")).toBeInTheDocument();
});
