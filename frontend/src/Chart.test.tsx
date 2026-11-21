import {render, waitFor} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import {ResultCard} from "./ResultCard";
import type {Presentation} from "./api";

const chart = vi.hoisted(() => ({
  setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(),
}));
vi.mock("echarts/core", () => ({use: vi.fn(), init: () => chart}));
afterEach(() => vi.unstubAllGlobals());

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
