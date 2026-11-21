import {act, render, screen, waitFor} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import {ResultCard} from "./ResultCard";
import type {Presentation} from "./api";

const chart = vi.hoisted(() => ({
  setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), on: vi.fn(),
}));
vi.mock("echarts/core", () => ({use: vi.fn(), init: () => chart}));
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("passes all 5000 points to the chart without sampling or aggregation", async () => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    disconnect() {}
  });
  const rows = Array.from({length: 5000}, (_, i) => ({
    month: new Date(Date.UTC(2010, 0, i + 1)).toISOString().slice(0, 10),
    brut: String(i + 0.25),
  }));
  const presentation: Presentation = {
    card: {
      result_id: "large-result", title: "Paie detaillee", visualization: "line",
      options: {line: null, bar: null, table: null, kpi: "Plusieurs valeurs."},
      notice: null, x: "month", series: ["brut"], row_count: 5000,
      columns: [{name: "month", type: "DATE"}, {name: "brut", type: "NUMERIC"}],
      rows,
      evidence: {
        sql: "SELECT month, gross AS brut FROM reporting_payroll", sources: ["reporting_payroll"],
        job_id: "job-large", bytes_processed: 500,
        scope: {metric: "payroll", start_month: "2010-01-01", end_month: "2023-09-01",
          establishment_ids: []},
      },
    },
    messages: [{
      version: "1.0", createSurface: {
        surfaceId: "surface-large", catalogId: "urn:dsn:catalog:v1",
        components: [{id: "root", component: "DSNResult", resultId: {"@path": "/resultId"}}],
        dataModel: {resultId: "large-result"},
      },
    }],
  };
  const {unmount} = render(<ResultCard initial={presentation} />);
  await waitFor(() => expect(chart.setOption).toHaveBeenCalled());
  const option = chart.setOption.mock.calls[0][0];
  expect(option.xAxis.data).toHaveLength(5000);
  expect(option.series[0].data).toEqual(rows.map(row => Number(row.brut)));
  expect(option.series[0].sampling).toBeUndefined();
  unmount();
  expect(chart.dispose).toHaveBeenCalled();
});

it("maps a chart series click to its retained establishment row without making a request", async () => {
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const explore = vi.fn();
  const presentation: Presentation = {
    card: {
      result_id: "comparison", title: "Effectifs", visualization: "bar",
      options: {line: "Pas de temps", bar: null, table: null, kpi: "Plusieurs valeurs"},
      notice: null, x: "site", series: ["effectif"], row_count: 2,
      columns: [{name: "site", type: "STRING"}, {name: "effectif", type: "INTEGER"}],
      rows: [{site: "SYN-EST-01", effectif: 50}, {site: "SYN-EST-03", effectif: 60}],
      evidence: {
        sql: "SELECT establishment_id AS site, COUNT(DISTINCT employee_id) AS effectif FROM reporting_employment GROUP BY site",
        sources: ["reporting_employment"], job_id: "comparison-job", bytes_processed: 500,
        scope: {metric: "headcount", start_month: "2026-10-01", end_month: "2026-10-01",
          establishment_ids: []},
      },
    },
    messages: [{
      version: "1.0", createSurface: {
        surfaceId: "comparison-surface", catalogId: "urn:dsn:catalog:v1",
        components: [{id: "root", component: "DSNResult", resultId: {"@path": "/resultId"}}],
        dataModel: {resultId: "comparison"},
      },
    }],
  };
  render(<ResultCard initial={presentation} onExplore={explore} />);
  await waitFor(() => expect(chart.on).toHaveBeenCalled());
  const click = chart.on.mock.calls.find(([event]) => event === "click")?.[1];
  expect(click).toBeTypeOf("function");
  act(() => click({componentType: "series", dataIndex: 1}));
  expect(explore).toHaveBeenCalledWith(presentation.card, "SYN-EST-03");
  expect(screen.getByRole("button", {name: "Explorer SYN-EST-03"})).toBeTruthy();
  act(() => click({componentType: "legend", dataIndex: 0}));
  act(() => click({componentType: "series", dataIndex: 99}));
  expect(explore).toHaveBeenCalledTimes(1);
  expect(fetch).not.toHaveBeenCalled();
});
