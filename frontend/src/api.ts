import {z} from "zod";

export const visualizationSchema = z.enum(["auto", "line", "bar", "table", "kpi"]);
export type Visualization = z.infer<typeof visualizationSchema>;
export const visualizationLabels: Record<Visualization, string> = {
  auto: "Automatique", line: "Courbe", bar: "Barres", table: "Tableau", kpi: "KPI",
};
export const promptSchema = z.object({
  id: z.string(), label: z.string(), template: z.string(), category: z.string(),
  visualization: visualizationSchema, order: z.number(), enabled: z.boolean(),
  parameters: z.array(z.object({id: z.string(), label: z.string(), default: z.string()})),
});
export type SuggestedPrompt = z.infer<typeof promptSchema>;
export const rowSchema = z.record(z.unknown());
export const cardSchema = z.object({
  result_id: z.string(), title: z.string(),
  visualization: visualizationSchema.exclude(["auto"]),
  options: z.object({
    line: z.string().nullable(), bar: z.string().nullable(),
    table: z.string().nullable(), kpi: z.string().nullable(),
  }),
  notice: z.string().nullable(), x: z.string().nullable(), series: z.array(z.string()),
  row_count: z.number(), columns: z.array(z.object({name: z.string(), type: z.string()})),
  rows: z.array(rowSchema),
  evidence: z.object({
    sql: z.string(), sources: z.array(z.string()), job_id: z.string(),
    bytes_processed: z.number(),
    scope: z.object({
      metric: z.string(), start_month: z.string(), end_month: z.string(),
      establishment_ids: z.array(z.string()),
    }),
  }),
});
export type Card = z.infer<typeof cardSchema>;
export const presentationSchema = z.object({
  card: cardSchema,
  messages: z.array(z.record(z.unknown())),
});
export type Presentation = z.infer<typeof presentationSchema>;
export const answerSchema = z.object({
  text: z.string(), status: z.enum(["result", "clarification"]),
  warnings: z.array(z.object({message: z.string()})),
  presentation: presentationSchema.nullable(),
});
export type Answer = z.infer<typeof answerSchema>;
export const healthSchema = z.object({
  status: z.string(), missing: z.array(z.string()),
  limits: z.object({
    chart_points: z.number(), rows: z.number(), bytes_billed: z.number(),
    sql_attempts: z.number(),
  }),
});

export async function api(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {"Content-Type": "application/json", ...init?.headers},
    credentials: "same-origin",
  });
  const data: unknown = await response.json();
  if (!response.ok) {
    const error = z.object({message: z.string()}).safeParse(data);
    throw new Error(error.success ? error.data.message : `Erreur HTTP ${response.status}`);
  }
  return data;
}

export function resolvePrompt(prompt: SuggestedPrompt, values: Record<string, string>): string {
  return prompt.template.replace(/\{([^{}]+)\}/g, (_, key: string) => values[key] ?? "");
}

export function formatCell(value: unknown, type: string, money = false): string {
  if (value === null || value === undefined) return "\u2014";
  if (typeof value === "object") return JSON.stringify(value);
  if (["DATE", "TIMESTAMP", "DATETIME"].includes(type)) {
    const parsed = new Date(String(value).length === 10 ? `${value}T00:00:00Z` : String(value));
    if (!Number.isNaN(parsed.getTime())) {
      return new Intl.DateTimeFormat("fr-FR", {timeZone: "UTC"}).format(parsed);
    }
  }
  if (["INTEGER", "INT64", "NUMERIC", "BIGNUMERIC", "FLOAT", "FLOAT64"].includes(type)) {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
      return new Intl.NumberFormat("fr-FR", money
        ? {style: "currency", currency: "EUR", maximumFractionDigits: 2}
        : {maximumFractionDigits: 6}).format(numeric);
    }
  }
  return String(value);
}
