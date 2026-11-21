import {render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {afterEach, describe, expect, it, vi} from "vitest";
import App from "./App";
import {ResultCard} from "./ResultCard";
import type {Card, Presentation} from "./api";

afterEach(() => vi.unstubAllGlobals());

const prompt = {
  id: "payroll", label: "Evolution de la masse salariale", category: "Remuneration",
  template: "Paie pour {periode}", visualization: "line", order: 1, enabled: true,
  parameters: [{id: "periode", label: "Periode", default: "les 12 derniers mois complets"}],
};

function respond(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), {
    status: 200, headers: {"Content-Type": "application/json"},
  }));
}

describe("suggested prompts", () => {
  it("previews editable parameters and submits only after Analyser", async () => {
    const fetch = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/prompts") return respond([prompt]);
      if (url === "/api/health") return respond({
        status: "configured", missing: [],
        limits: {rows: 10000, chart_points: 5000, bytes_billed: 104857600, sql_attempts: 2},
      });
      if (url === "/api/analyze") return respond({
        text: "Precisez le mois.", status: "clarification", warnings: [], presentation: null,
      });
      return respond({status: "ready"});
    });
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", {name: /Evolution de la masse salariale/}));
    expect(fetch.mock.calls.some(([url]) => url === "/api/analyze")).toBe(false);
    const parameter = screen.getByLabelText("Periode");
    await user.clear(parameter);
    await user.type(parameter, "octobre 2026");
    expect((screen.getByLabelText("Apercu editable") as HTMLTextAreaElement).value)
      .toBe("Paie pour octobre 2026");
    await user.selectOptions(screen.getByLabelText("Visualisation"), "table");
    await user.click(screen.getByRole("button", {name: /Analyser/}));
    await screen.findByText("Precisez le mois.");
    const request = fetch.mock.calls.find(([url]) => url === "/api/analyze");
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      question: "Paie pour octobre 2026", visualization: "table",
    });
  });

  it("supports multiline questions, Enter submission, and reset from the header menu", async () => {
    const fetch = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/prompts") return respond([prompt]);
      if (url === "/api/health") return respond({
        status: "configured", missing: [],
        limits: {rows: 10000, chart_points: 5000, bytes_billed: 104857600, sql_attempts: 2},
      });
      if (url === "/api/analyze") return respond({
        text: "Precisez le mois.", status: "clarification", warnings: [], presentation: null,
      });
      return respond({status: "ready"});
    });
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", {name: /Evolution de la masse salariale/});
    const question = screen.getByLabelText("Votre question");
    await user.type(question, "Effectif");
    await user.keyboard("{Shift>}{Enter}{/Shift}octobre");
    expect((question as HTMLTextAreaElement).value).toBe("Effectif\noctobre");
    expect(fetch.mock.calls.some(([url]) => url === "/api/analyze")).toBe(false);
    await user.keyboard("{Enter}");
    await screen.findByText("Precisez le mois.");
    expect(screen.queryByRole("heading", {level: 1})).toBeNull();
    expect(JSON.parse(String(fetch.mock.calls.find(([url]) => url === "/api/analyze")?.[1]?.body)))
      .toEqual({question: "Effectif\noctobre", visualization: "auto"});
    await user.click(screen.getByLabelText("Menu de l'application"));
    await user.click(screen.getByRole("button", {name: /Nouvelle conversation/}));
    await screen.findByRole("heading", {level: 1});
    expect(screen.queryByText("Precisez le mois.")).toBeNull();
    expect(fetch.mock.calls.some(([url, init]) => url === "/api/session" && init?.method === "DELETE"))
      .toBe(true);
  });
});

function presentation(visualization: Card["visualization"]): Presentation {
  return {
    card: {
      result_id: "result-1", title: "Masse salariale", visualization,
      options: {line: "Pas de dimension temporelle.", bar: null, table: null, kpi: null},
      notice: null, x: null, series: ["brut"], row_count: 1,
      columns: [{name: "brut", type: "NUMERIC"}], rows: [{brut: "123.45"}],
      evidence: {
        sql: "SELECT SUM(gross) AS brut FROM reporting_payroll", sources: ["reporting_payroll"],
        job_id: "job-1", bytes_processed: 500,
        scope: {metric: "payroll", start_month: "2026-10-01", end_month: "2026-10-01",
          establishment_ids: []},
      },
    },
    messages: [{
      version: "1.0", createSurface: {
        surfaceId: "surface-1", catalogId: "urn:dsn:catalog:v1",
        components: [{id: "root", component: "DSNResult", resultId: {"@path": "/resultId"}}],
        dataModel: {resultId: "result-1"},
      },
    }],
  };
}

function establishmentPresentation(): Presentation {
  const result = presentation("table");
  result.card.x = "etablissement";
  result.card.columns.unshift({name: "etablissement", type: "STRING"});
  result.card.rows = [{etablissement: "SYN-EST-01", brut: "123.45"}];
  result.card.evidence.scope.end_month = "2025-03-01";
  result.card.evidence.scope.start_month = "2025-03-01";
  return result;
}

it("prepares an editable scoped follow-up and adds a second card only after confirmation", async () => {
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    if (url === "/api/prompts") return respond([prompt]);
    if (url === "/api/health") return respond({
      status: "configured", missing: [],
      limits: {rows: 10000, chart_points: 5000, bytes_billed: 104857600, sql_attempts: 2},
    });
    if (url === "/api/analyze") return respond({
      text: "Resultat disponible.", status: "result", warnings: [],
      presentation: establishmentPresentation(),
    });
    return respond({status: "ready"});
  });
  vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole("button", {name: /Evolution de la masse salariale/});
  await user.type(screen.getByLabelText("Votre question"), "Compare la masse salariale.");
  await user.click(screen.getByRole("button", {name: "Analyser"}));
  await user.click(await screen.findByRole("button", {name: "Explorer SYN-EST-01"}));
  const draft = screen.getByLabelText("Apercu editable") as HTMLTextAreaElement;
  expect(draft.value).toBe("Montre l'evolution mensuelle de la masse salariale brute " +
    "pour SYN-EST-01 uniquement, sur les 12 mois se terminant au mois 2025-03, " +
    "dans la limite des mois disponibles.");
  expect(document.activeElement).toBe(draft);
  expect((screen.getByLabelText("Visualisation") as HTMLSelectElement).value).toBe("line");
  expect(fetch.mock.calls.filter(([url]) => url === "/api/analyze")).toHaveLength(1);
  await user.type(draft, " Affiche les montants en euros.");
  await user.click(screen.getByRole("button", {name: "Analyser"}));
  await waitFor(() => expect(screen.getAllByRole("table")).toHaveLength(2));
  const requests = fetch.mock.calls.filter(([url]) => url === "/api/analyze");
  expect(requests).toHaveLength(2);
  expect(JSON.parse(String(requests[1][1]?.body))).toEqual({
    question: expect.stringContaining("2025-03, dans la limite des mois disponibles. Affiche les montants en euros."),
    visualization: "line",
  });
});

describe("real A2UI React rendering", () => {
  it("uses the current paginated row for exploration and ignores unknown establishment IDs", async () => {
    const result = establishmentPresentation();
    result.card.row_count = 51;
    result.card.rows.push({etablissement: "SYN-EST-99", brut: "100"});
    vi.stubGlobal("fetch", vi.fn(() => respond({
      rows: [{etablissement: "SYN-EST-03", brut: "300"}],
    })));
    const explore = vi.fn();
    const user = userEvent.setup();
    render(<ResultCard initial={result} onExplore={explore} />);
    expect(screen.queryByRole("button", {name: "Explorer SYN-EST-99"})).toBeNull();
    await user.click(screen.getByRole("button", {name: "Suivant"}));
    await user.click(await screen.findByRole("button", {name: "Explorer SYN-EST-03"}));
    expect(explore).toHaveBeenCalledWith(result.card, "SYN-EST-03");
  });

  it("does not allow exploration while an analysis is running", () => {
    const explore = vi.fn();
    render(<ResultCard initial={establishmentPresentation()} onExplore={explore} disabled />);
    expect(screen.queryByRole("button", {name: "Explorer SYN-EST-01"})).toBeNull();
    expect(explore).not.toHaveBeenCalled();
  });

  it("renders query-bound tables and switches presentation without an agent turn", async () => {
    const fetch = vi.fn(() => respond(presentation("kpi")));
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    render(<ResultCard initial={presentation("table")} />);
    await screen.findByRole("table");
    await user.selectOptions(screen.getByLabelText("Afficher en"), "kpi");
    await waitFor(() => expect(screen.queryByRole("table")).toBeNull());
    expect(await screen.findByText(/123,45/)).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]).toEqual([
      "/api/results/result-1?visualization=kpi",
      expect.objectContaining({credentials: "same-origin"}),
    ]);
    await user.click(screen.getByText("SQL execute et sources"));
    expect(screen.getByText("job-1")).toBeTruthy();
  });

  it("rejects unknown components instead of rendering untrusted layout", () => {
    const invalid = presentation("table");
    invalid.messages = [{
      version: "1.0", createSurface: {
        surfaceId: "invalid", catalogId: "urn:dsn:catalog:v1",
        components: [{id: "root", component: "UnknownExecutableWidget"}],
      },
    }];
    render(<ResultCard initial={invalid} />);
    expect(screen.getByRole("alert").textContent).toContain("refusee");
  });
});
