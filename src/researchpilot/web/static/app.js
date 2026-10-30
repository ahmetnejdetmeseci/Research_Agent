const byId = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (_) {
      // Preserve the HTTP fallback when a response is not JSON.
    }
    throw new Error(detail);
  }
  return response.json();
}

function setText(id, value) {
  byId(id).textContent = String(value);
}

function showNotice(message, error = false) {
  const notice = byId("notice");
  notice.textContent = message;
  notice.classList.toggle("error", error);
  notice.hidden = !message;
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function textElement(tag, text, className = "") {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function renderResearchItems(targetId, items, kind) {
  const target = byId(targetId);
  target.replaceChildren();
  if (!items.length) {
    target.append(textElement("p", `No stored ${kind} yet.`, "empty"));
    return;
  }

  items.slice(0, 8).forEach((ranked) => {
    const data = kind === "papers" ? ranked.paper : ranked.repository;
    const article = document.createElement("article");
    article.className = `research-item${ranked.selected ? "" : " rejected"}`;

    const body = document.createElement("div");
    const heading = document.createElement("h3");
    const link = document.createElement("a");
    link.href = data.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = kind === "papers" ? data.title : data.full_name;
    heading.append(link);
    body.append(heading);

    const description = kind === "papers" ? data.abstract : (data.description || "No description available.");
    body.append(textElement("p", description));

    const meta = document.createElement("div");
    meta.className = "item-meta";
    const matches = ranked.matches.map((match) => match.keyword).join(", ") || "No profile match";
    meta.append(textElement("span", matches));
    if (kind === "papers") {
      meta.append(textElement("span", formatDate(data.published_at)));
    } else {
      meta.append(textElement("span", `${data.stars} stars`));
      if (data.primary_language) meta.append(textElement("span", data.primary_language));
    }
    body.append(meta);

    const score = textElement("div", ranked.score.toFixed(2), "score");
    score.append(textElement("small", ranked.selected ? "selected" : "skipped"));
    article.append(body, score);
    target.append(article);
  });
}

function renderRuns(runs) {
  const target = byId("runs-list");
  target.replaceChildren();
  if (!runs.length) {
    target.append(textElement("p", "No pipeline runs recorded yet.", "empty"));
    return;
  }

  runs.slice(0, 8).forEach((entry) => {
    const item = document.createElement("article");
    item.className = "run-item";
    const row = document.createElement("div");
    row.className = "run-row";
    row.append(textElement("strong", `Run #${entry.run.id}`));
    row.append(textElement("span", entry.run.status, `run-status status-${entry.run.status}`));
    const completed = entry.steps.filter((step) => ["succeeded", "skipped"].includes(step.status)).length;
    item.append(row, textElement("div", `${completed}/${entry.steps.length} steps · ${formatDate(entry.run.started_at)}`, "run-detail"));
    target.append(item);
  });
}

function renderStatus(status) {
  setText("profile-name", status.profile);
  setText("run-count", status.database.runs);
  setText("analysis-count", status.database.analysis_attempts + status.database.repository_analysis_attempts);
  setText("schema-status", `Schema ${status.database.current_version}/${status.database.latest_version}`);
  setText("model-name", status.ollama_model);
  setText("api-version", status.version);
  setText("database-path", status.database.path);
  setText("obsidian-state", status.obsidian_export ? "Configured" : "Not configured");

  [["arxiv-state", status.sources.arxiv], ["github-state", status.sources.github]].forEach(([id, enabled]) => {
    const element = byId(id);
    element.textContent = enabled ? "Enabled" : "Disabled";
    element.classList.toggle("enabled", enabled);
  });
}

async function refresh() {
  byId("refresh-button").disabled = true;
  try {
    const [status, papers, repositories, runs] = await Promise.all([
      api("/api/v1/status"),
      api("/api/v1/papers"),
      api("/api/v1/repositories"),
      api("/api/v1/runs?limit=8"),
    ]);
    renderStatus(status);
    setText("paper-count", papers.selected_count);
    setText("paper-total", `${papers.count} stored`);
    setText("repository-count", repositories.selected_count);
    setText("repository-total", `${repositories.count} stored`);
    renderResearchItems("papers-list", papers.items, "papers");
    renderResearchItems("repositories-list", repositories.items, "repositories");
    renderRuns(runs.items);
    setText("last-updated", `Rankings refreshed ${formatDate(papers.as_of)}`);
    showNotice("");
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    byId("refresh-button").disabled = false;
  }
}

async function runPipeline() {
  const button = byId("run-button");
  button.disabled = true;
  button.textContent = "Pipeline running…";
  showNotice("Discovery, analysis, digest, and configured exports are running locally.");
  try {
    const result = await api("/api/v1/runs", { method: "POST" });
    const message = result.run.status === "succeeded"
      ? `Pipeline run #${result.run.id} completed.`
      : `Pipeline run #${result.run.id} failed at ${result.failed_step || "an unknown step"}.`;
    await refresh();
    showNotice(message, result.run.status !== "succeeded");
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Run pipeline";
  }
}

byId("refresh-button").addEventListener("click", refresh);
byId("run-button").addEventListener("click", runPipeline);
refresh();
