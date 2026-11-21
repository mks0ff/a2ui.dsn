import {useEffect, useState, type FormEvent} from "react";
import {z} from "zod";
import {
  api, answerSchema, healthSchema, promptSchema, resolvePrompt, visualizationLabels,
  type Answer, type SuggestedPrompt, type Visualization,
} from "./api";
import {ResultCard} from "./ResultCard";

type Message = {id: number; question: string; answer?: Answer; error?: string};

export default function App() {
  const [prompts, setPrompts] = useState<SuggestedPrompt[]>([]);
  const [selected, setSelected] = useState<SuggestedPrompt | null>(null);
  const [parameters, setParameters] = useState<Record<string, string>>({});
  const [question, setQuestion] = useState("");
  const [visualization, setVisualization] = useState<Visualization>("auto");
  const [messages, setMessages] = useState<Message[]>([]);
  const [health, setHealth] = useState<z.infer<typeof healthSchema> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    Promise.all([api("/prompts"), api("/health"), api("/session", {method: "POST"})])
      .then(([catalog, status]) => {
        setPrompts(z.array(promptSchema).parse(catalog));
        setHealth(healthSchema.parse(status));
        setReady(true);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Serveur indisponible."));
  }, []);

  function choose(prompt: SuggestedPrompt) {
    const values = Object.fromEntries(prompt.parameters.map(parameter =>
      [parameter.id, parameter.default]));
    setSelected(prompt);
    setParameters(values);
    setQuestion(resolvePrompt(prompt, values));
    setVisualization(prompt.visualization);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy) return;
    const id = Date.now();
    const text = question.trim();
    setBusy(true);
    setError("");
    setMessages(previous => [...previous, {id, question: text}]);
    try {
      const answer = answerSchema.parse(await api("/analyze", {
        method: "POST", body: JSON.stringify({question: text, visualization}),
      }));
      setMessages(previous => previous.map(item => item.id === id ? {...item, answer} : item));
      setQuestion("");
      setSelected(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Analyse impossible.";
      setMessages(previous => previous.map(item => item.id === id ? {...item, error: message} : item));
    } finally { setBusy(false); }
  }

  async function clear() {
    setBusy(true);
    setError("");
    try {
      await api("/session", {method: "DELETE"});
      await api("/session", {method: "POST"});
      setMessages([]);
      setSelected(null);
      setQuestion("");
      setVisualization("auto");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Effacement impossible.");
    } finally { setBusy(false); }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="DSN Atelier analytique"><span>D.</span> DSN atelier</a>
      <p className="sidebar-label">EXPLORER LES DONNEES</p>
      <div className="nav-active"><span aria-hidden="true">/</span> Conversation analytique</div>
      <button className="new-conversation" disabled={busy || !ready} onClick={() => void clear()}>
        + Nouvelle conversation
      </button>
      <div className="dataset-note">
        <span className="status-dot" /> ENVIRONNEMENT DE DEMONSTRATION
        <h3>Un terrain d'exploration, pas des donnees reelles.</h3>
        <p>1 employeur fictif<br />3 etablissements<br />24 mois de declarations</p>
        <small>Analyses descriptives uniquement. Aucun avis de conformite.</small>
      </div>
      <footer>Python ADK + BigQuery<br />Interface declarative A2UI</footer>
    </aside>
    <main>
      <header className="topbar">
        <span>Atelier analytique <span className="muted">/ DSN</span></span>
        <span className="badge">Donnees synthetiques</span>
      </header>
      <div className="workspace">
        <section className="intro">
          <p className="eyebrow">DE LA QUESTION A LA COMPREHENSION</p>
          <h1>Vos donnees sociales,<br /><em>en conversation.</em></h1>
          <p>Explorez les effectifs, la masse salariale et les cotisations.<br />
            Chaque resultat est accompagne de son SQL et de ses sources.</p>
        </section>
        {error && <p className="error" role="alert">{error}</p>}
        {health && health.missing.length > 0 && <div className="notice" role="status">
          Le serveur est pret pour la configuration. Renseignez {health.missing.join(", ")} dans .env.
          Aucune requete cloud ne peut encore etre executee.
        </div>}
        <section aria-label="Questions suggerees" className="suggestions">
          {prompts.map((prompt, index) => <button key={prompt.id}
            className={selected?.id === prompt.id ? "suggestion selected" : "suggestion"}
            disabled={busy} onClick={() => choose(prompt)}>
            <span className="prompt-number">0{index + 1} <span>{prompt.category}</span></span>
            <strong>{prompt.label}</strong><span className="prompt-action">Preparer la question &rarr;</span>
          </button>)}
        </section>
        <form className="composer" onSubmit={event => void submit(event)}>
          <div className="composer-heading">
            <label htmlFor="question">{selected ? "Apercu editable" : "Votre question"}</label>
            {selected && <span>Aucune requete avant Analyser</span>}
          </div>
          {selected && <div className="parameters">
            {selected.parameters.map(parameter => <label key={parameter.id}>
              {parameter.label}<input value={parameters[parameter.id] ?? ""}
                disabled={busy} onChange={event => {
                  const next = {...parameters, [parameter.id]: event.target.value};
                  setParameters(next);
                  setQuestion(resolvePrompt(selected, next));
                }} />
            </label>)}
          </div>}
          <textarea id="question" value={question} maxLength={4000} disabled={busy}
            placeholder="Ex. Comment evolue la masse salariale sur les 12 derniers mois ?"
            onChange={event => setQuestion(event.target.value)} rows={3} />
          <div className="composer-bottom">
            <label>Visualisation
              <select value={visualization} disabled={busy}
                onChange={event => setVisualization(event.target.value as Visualization)}>
                {Object.entries(visualizationLabels).map(([kind, label]) =>
                  <option key={kind} value={kind}>{label}</option>)}
              </select>
            </label>
            <button type="submit" className="primary"
              disabled={busy || !ready || !question.trim() || !!health?.missing.length}>
              {busy ? "Analyse en cours..." : "Analyser"} <span aria-hidden="true">&rarr;</span>
            </button>
          </div>
        </form>
        <p className="limits">
          Lecture seule &middot; {health?.limits.rows.toLocaleString("fr-FR") ?? "10 000"} lignes
          &middot; {health?.limits.chart_points.toLocaleString("fr-FR") ?? "5 000"} points par graphique
          &middot; {health ? Math.round(health.limits.bytes_billed / 1024 / 1024) : 100} MiB par requete
        </p>
        <section aria-label="Conversation" aria-live="polite" className="conversation">
          {messages.map(item => <article key={item.id} className="turn">
            <div className="user-question"><span>VOUS</span><p>{item.question}</p></div>
            {item.error && <p role="alert" className="error">{item.error}</p>}
            {item.answer && <>
              <p className="answer-text">{item.answer.text}</p>
              {item.answer.warnings.map((warning, index) =>
                <p className="notice" key={index}>Tentative precedente : {warning.message}</p>)}
              {item.answer.presentation && <ResultCard initial={item.answer.presentation} />}
            </>}
            {!item.answer && !item.error && <p role="status" className="pending">
              L'agent examine la question et verifie les limites BigQuery...
            </p>}
          </article>)}
        </section>
        <p className="privacy">Conversation et resultats conserves en memoire du serveur local uniquement.
          Effacer la conversation ne supprime pas l'historique Google Cloud.</p>
      </div>
    </main>
  </div>;
}
