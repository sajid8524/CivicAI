const state = {
  complaints: [],
  dashboard: null,
  latestTicket: null,
};

const titles = {
  complaint: "Citizen Complaint Portal",
  track: "Track Complaint",
  officer: "Officer Dashboard",
  transparency: "Transparency Dashboard",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function statusClass(value) {
  return String(value || "").replace(/\s+/g, "");
}

function safe(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function titleCase(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\w\S*/g, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());
}

function percent(value) {
  const numeric = Number(value || 0);
  return `${Math.round(numeric * 100)}%`;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.add("hidden"), 4200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

function switchView(view) {
  $$(".nav-button").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$(".view").forEach((panel) => panel.classList.toggle("active", panel.id === `view-${view}`));
  $("#view-title").textContent = titles[view];
  if (view === "officer") loadComplaints();
  if (view === "transparency") loadDashboard();
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    if (!file) {
      resolve(null);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function decisionRows(rows) {
  return rows
    .filter((row) => row[1] !== undefined && row[1] !== null && row[1] !== "")
    .map(([label, value]) => `
      <div class="decision-row">
        <span>${safe(label)}</span>
        <strong>${safe(value)}</strong>
      </div>
    `).join("");
}

function priorityFactors(factors = {}) {
  const rows = [
    ["Affected Citizens", factors.affected_citizens],
    ["High Risk Issue", factors.high_risk_issue ? "Yes" : "No"],
    ["Critical Location", factors.critical_location ? "Yes" : "No"],
    ["Evidence Image", Number(factors.image_confidence || 0) > 0 ? "Available" : "Not uploaded"],
  ];
  return `<div class="factor-list">${decisionRows(rows)}</div>`;
}

function readableDecision(agent, output) {
  switch (agent) {
    case "Complaint Understanding Agent":
      return decisionRows([
        ["Issue", titleCase(output.issue_type)],
        ["Severity", titleCase(output.severity)],
        ["Location", output.location],
        ["Confidence", percent(output.understanding_confidence)],
      ]);
    case "Vision Verification Agent":
      return decisionRows([
        ["Detected", output.image_detected_issue ? titleCase(output.image_detected_issue) : "No image uploaded"],
        ["Confidence", percent(output.image_confidence)],
        ["Evidence", output.image_signal],
      ]);
    case "Classification Agent":
      return decisionRows([
        ["Category", output.category],
        ["Department Hint", output.suggested_department],
        ["Confidence", percent(output.classification_confidence)],
        ["Vision/Text Conflict", output.vision_text_disagreement ? "Yes" : "No"],
      ]);
    case "Duplicate Detection Agent":
      return decisionRows([
        ["Decision", output.duplicate_of ? `Linked to ${output.duplicate_of}` : "No duplicate found"],
        ["Similarity Score", percent(output.duplicate_confidence)],
        ["Reason", output.duplicate_reason],
      ]);
    case "Priority Scoring Agent":
      return `
        ${decisionRows([
          ["Priority", output.priority_band],
          ["Score", `${output.priority_score}/100`],
        ])}
        ${priorityFactors(output.priority_factors)}
      `;
    case "Routing Agent":
      return decisionRows([
        ["Assigned Department", output.assigned_department],
        ["Officer Queue", output.assigned_officer],
        ["SLA", `${output.expected_resolution_hours} hours`],
        ["Reason", output.routing_reason],
      ]);
    case "Resolution Monitoring Agent":
      return decisionRows([
        ["Ticket", output.ticket_id],
        ["Elapsed Hours", output.elapsed_hours],
        ["SLA", `${output.sla} hours`],
        ["SLA Breach", output.sla_breach ? "Yes" : "No"],
        ["Autonomous Action", titleCase(output.action)],
      ]);
    case "Escalation Agent":
      return decisionRows([
        ["Current Level", output.current_level],
        ["Next Level", output.next_level || "None"],
        ["Reason", output.reason],
        ["Status", output.escalation_status],
      ]);
    case "Citizen Sentiment Agent":
      return decisionRows([
        ["Rating", `${output.rating}/5`],
        ["Sentiment", output.sentiment],
        ["Confidence", percent(output.confidence)],
        ["Feedback", output.feedback],
      ]);
    case "Citizen Communication Agent":
      return decisionRows([["Message", output.citizen_message]]);
    default:
      return decisionRows([["Decision", "Agent completed"], ["Output", "See raw JSON"]]);
  }
}

function renderTrace(trace) {
  return `<div class="trace">${trace.map((item) => `
    <article class="decision-card">
      <div class="decision-card-head">
        <strong>${safe(item.agent)}</strong>
        <span>Autonomous decision</span>
      </div>
      <div class="decision-rows">${readableDecision(item.agent, item.output)}</div>
      <details class="raw-json">
        <summary>Show Raw JSON</summary>
        <pre>${safe(JSON.stringify(item.output, null, 2))}</pre>
      </details>
    </article>
  `).join("")}</div>`;
}

function renderComplaintSummary(complaint, trace = null) {
  const duplicate = complaint.duplicate_of
    ? `<p><strong>Linked duplicate:</strong> ${safe(complaint.duplicate_of)} (${Math.round((complaint.duplicate_confidence || 0) * 100)}%)</p>`
    : "";
  const traceHtml = trace ? renderTrace(trace) : "";
  return `
    <div class="ticket">
      <div class="ticket-header">
        <div>
          <div class="ticket-id">${safe(complaint.id)}</div>
          <p>${safe(complaint.citizen_message || complaint.description)}</p>
        </div>
        <span class="badge ${statusClass(complaint.status)}">${safe(complaint.status)}</span>
      </div>
      <div class="meta-grid">
        <div><span>Issue</span><strong>${safe(titleCase(complaint.issue_type))}</strong></div>
        <div><span>Department</span><strong>${safe(complaint.assigned_department)}</strong></div>
        <div><span>Priority</span><strong>${safe(complaint.priority_band)} ${safe(complaint.priority_score)}/100</strong></div>
        <div><span>Expected resolution</span><strong>${safe(complaint.expected_resolution_hours)} hours</strong></div>
        <div><span>Location</span><strong>${safe(complaint.location)}</strong></div>
        <div><span>Officer queue</span><strong>${safe(complaint.assigned_officer)}</strong></div>
      </div>
      ${duplicate}
      ${traceHtml}
    </div>
  `;
}

function renderFeedbackPanel(complaint) {
  const feedbackRows = (complaint.feedback || []).map((item) => `
    <div class="trace-item">
      <strong>${safe(item.sentiment)} sentiment (${safe(item.rating)}/5)</strong>
      <p>${safe(item.feedback)}</p>
      <small>Confidence ${percent(item.confidence)} · ${new Date(item.created_at).toLocaleString()}</small>
    </div>
  `).join("");
  const feedbackForm = complaint.status === "Resolved" || complaint.status === "Closed"
    ? `
      <form class="feedback-form" data-id="${safe(complaint.id)}">
        <label>
          Rating
          <select name="rating">
            <option value="5">5 - Excellent</option>
            <option value="4">4 - Good</option>
            <option value="3">3 - Okay</option>
            <option value="2">2 - Poor</option>
            <option value="1">1 - Bad</option>
          </select>
        </label>
        <label>
          Feedback
          <textarea name="feedback" rows="3" placeholder="Issue reopened after 2 days"></textarea>
        </label>
        <button class="primary" type="submit">Run Sentiment Agent</button>
      </form>
    `
    : `<div class="empty-state">Citizen feedback opens after the complaint is resolved.</div>`;
  return `
    <div class="panel">
      <div class="section-heading"><h2>Citizen Sentiment</h2><span>Post-resolution agent</span></div>
      ${feedbackForm}
      <div class="trace feedback-list">${feedbackRows}</div>
    </div>
  `;
}

function renderTrack(complaint) {
  const history = (complaint.history || []).map((item) => `
    <div class="trace-item">
      <strong>${safe(item.status)}</strong>
      <p>${safe(item.note)}</p>
      <small>${new Date(item.created_at).toLocaleString()}</small>
    </div>
  `).join("");
  const escalations = (complaint.escalations || []).map((item) => `
    <div class="trace-item">
      <strong>Level ${safe(item.level)}: ${safe(item.to_role)}</strong>
      <p>${safe(item.reason)}</p>
    </div>
  `).join("");
  const persistedTrace = (complaint.agent_runs || []).map((item) => ({
    agent: item.agent_name,
    output: JSON.parse(item.output_json || "{}"),
  }));
  return `
    ${renderComplaintSummary(complaint)}
    <div class="grid two" style="margin-top: 16px;">
      <div class="panel">
        <div class="section-heading"><h2>Status History</h2><span>${complaint.history.length} updates</span></div>
        <div class="trace">${history || "<p>No history yet.</p>"}</div>
      </div>
      <div class="panel">
        <div class="section-heading"><h2>Escalations</h2><span>Agent actions</span></div>
        <div class="trace">${escalations || "<p>No escalation required.</p>"}</div>
      </div>
      <div class="panel">
        <div class="section-heading"><h2>Persisted Agent Runs</h2><span>${persistedTrace.length} records</span></div>
        ${persistedTrace.length ? renderTrace(persistedTrace) : "<p>No agent runs yet.</p>"}
      </div>
      ${renderFeedbackPanel(complaint)}
    </div>
  `;
}

async function submitComplaint(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  button.textContent = "Running Agents";
  try {
    const data = Object.fromEntries(new FormData(form).entries());
    const imageFile = form.elements.image.files[0];
    data.image_data = await fileToDataUrl(imageFile);
    data.image_name = imageFile ? imageFile.name : "";
    const result = await api("/api/complaints", {
      method: "POST",
      body: JSON.stringify(data),
    });
    state.latestTicket = result.complaint.id;
    $("#trace-status").textContent = result.complaint.id;
    $("#submission-result").classList.remove("empty-state");
    $("#submission-result").innerHTML = renderComplaintSummary(result.complaint, result.agent_trace);
    form.reset();
    $("#image-preview").classList.add("hidden");
    showToast(`Complaint ${result.complaint.id} created`);
    await loadDashboard();
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Submit Complaint";
  }
}

async function trackComplaint() {
  const id = $("#track-id").value.trim().toUpperCase();
  if (!id) {
    showToast("Enter a complaint ID");
    return;
  }
  try {
    const result = await api(`/api/complaints/${encodeURIComponent(id)}`);
    $("#track-result").classList.remove("empty-state");
    $("#track-result").innerHTML = renderTrack(result.complaint);
  } catch (error) {
    $("#track-result").classList.add("empty-state");
    $("#track-result").textContent = error.message;
  }
}

async function loadComplaints() {
  const result = await api("/api/complaints");
  state.complaints = result.complaints;
  renderOfficerList();
}

function renderOfficerList() {
  const filter = $("#status-filter").value;
  const complaints = state.complaints.filter((item) => !filter || item.status === filter);
  $("#officer-list").innerHTML = complaints.map((item) => `
    <article class="ticket">
      <div class="ticket-header">
        <div>
          <div class="ticket-id">${safe(item.id)}</div>
          <p>${safe(item.description)}</p>
        </div>
        <span class="badge ${statusClass(item.status)}">${safe(item.status)}</span>
      </div>
      <div class="meta-grid">
        <div><span>Issue</span><strong>${safe(titleCase(item.issue_type))}</strong></div>
        <div><span>Priority</span><strong>${safe(item.priority_score)}/100</strong></div>
        <div><span>Department</span><strong>${safe(item.assigned_department)}</strong></div>
        <div><span>Ward</span><strong>${safe(item.ward || "Central")}</strong></div>
      </div>
      <div class="ticket-actions">
        <button data-status="In Progress" data-id="${safe(item.id)}">In Progress</button>
        <button data-status="Resolved" data-id="${safe(item.id)}">Resolve</button>
        <button data-track="${safe(item.id)}">Track</button>
      </div>
    </article>
  `).join("") || `<div class="empty-state">No complaints match this filter.</div>`;
}

async function updateStatus(id, status) {
  await api(`/api/complaints/${encodeURIComponent(id)}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status, note: `Officer marked complaint as ${status}` }),
  });
  showToast(`${id} updated to ${status}`);
  await loadComplaints();
  await loadDashboard();
}

function renderMonitoringOutput(result) {
  const decisionTrace = [
    ...(result.decisions || []).map((output) => ({ agent: "Resolution Monitoring Agent", output })),
    ...(result.escalations || []).map((output) => ({ agent: "Escalation Agent", output })),
  ];
  $("#monitoring-result").classList.remove("hidden");
  $("#monitoring-result").innerHTML = `
    <div class="section-heading">
      <h2>Autonomous Monitoring Run</h2>
      <span>${safe(result.checked_open_complaints)} tickets checked</span>
    </div>
    ${decisionTrace.length ? renderTrace(decisionTrace) : "<p>No open tickets found.</p>"}
  `;
}

async function runMonitor() {
  const result = await api("/api/monitor/run", { method: "POST", body: "{}" });
  renderMonitoringOutput(result);
  const count = result.escalations.length;
  showToast(count ? `${count} SLA breach escalation(s) triggered` : "Monitoring completed; no SLA breach found");
  await loadComplaints();
  await loadDashboard();
}

function renderKpis(kpis, feedback = {}) {
  const satisfaction = feedback.citizen_satisfaction === null || feedback.citizen_satisfaction === undefined
    ? "--"
    : `${feedback.citizen_satisfaction}%`;
  const items = [
    ["Total complaints", kpis.total],
    ["Open", kpis.open],
    ["Escalated", kpis.escalated],
    ["Critical", kpis.critical],
    ["Citizen satisfaction", satisfaction],
  ];
  $("#kpi-grid").innerHTML = items.map(([label, value]) => `
    <div class="kpi"><span>${safe(label)}</span><strong>${safe(value)}</strong></div>
  `).join("");
}

function renderBars(selector, rows) {
  const max = Math.max(1, ...rows.map((row) => Number(row.value || 0)));
  $(selector).innerHTML = rows.map((row, index) => {
    const width = Math.max(8, (Number(row.value || 0) / max) * 100);
    const colors = ["var(--teal)", "var(--amber)", "var(--indigo)", "var(--red)", "var(--green)"];
    return `
      <div class="bar-row">
        <div class="bar-label"><span>${safe(row.label)}</span><strong>${safe(row.value)}</strong></div>
        <div class="bar-track"><div class="bar-fill" style="width: ${width}%; background: ${colors[index % colors.length]}"></div></div>
      </div>
    `;
  }).join("") || "<p>No complaint data yet.</p>";
}

function renderMap(points) {
  $("#city-map").innerHTML = `
    <div class="map-road r1"></div>
    <div class="map-road r2"></div>
    <div class="map-road r3"></div>
    ${points.map((point) => `
      <button
        class="map-point ${point.priority_score >= 70 ? "high" : point.priority_score >= 40 ? "medium" : ""}"
        style="left: ${point.x}%; top: ${point.y}%"
        title="${safe(point.id)}: ${safe(point.issue_type)} at ${safe(point.location)}"
        data-track="${safe(point.id)}">
      </button>
    `).join("")}
  `;
}

function renderRankings(rows) {
  $("#ranking-table").innerHTML = rows.map((row) => `
    <tr>
      <td>${safe(row.department)}</td>
      <td>${safe(row.total)}</td>
      <td>${safe(row.resolved)}</td>
      <td>${safe(row.escalated)}</td>
      <td>${safe(row.avg_priority || 0)}</td>
    </tr>
  `).join("") || `<tr><td colspan="5">No department data yet.</td></tr>`;
}

function renderRisk(riskOutput) {
  const risks = riskOutput.risks || [];
  $("#risk-list").innerHTML = risks.map((risk) => {
    const countKey = Object.keys(risk).find((key) => key.endsWith("_reports"));
    return `
      <article class="insight-card ${String(risk.risk_level).toLowerCase()}">
        <div class="insight-head">
          <strong>${safe(risk.ward)} Ward</strong>
          <span>${safe(risk.risk_level)} Risk</span>
        </div>
        <div class="decision-rows">
          ${decisionRows([
            ["Issue", titleCase(risk.issue_type)],
            ["Reports", risk[countKey]],
            ["Trend", titleCase(risk.trend)],
            ["Prediction", risk.prediction],
          ])}
        </div>
      </article>
    `;
  }).join("") || `<div class="empty-state">No risk clusters yet. File repeated ward complaints to activate prediction.</div>`;
}

function renderAllocation(allocationOutput) {
  const rows = allocationOutput.allocations || [];
  $("#allocation-list").innerHTML = rows.map((item) => `
    <article class="insight-card">
      <div class="insight-head">
        <strong>${safe(item.department)}</strong>
        <span>${safe(item.active_complaints)} active</span>
      </div>
      <div class="decision-rows">
        ${decisionRows([
          ["Available Staff", item.available_staff],
          ["Recommended Staff", item.recommended_staff],
          ["Recommendation", item.recommendation],
        ])}
      </div>
    </article>
  `).join("") || `<div class="empty-state">No active workload requiring allocation.</div>`;
}

function renderSatisfaction(feedback) {
  const satisfaction = feedback.citizen_satisfaction === null || feedback.citizen_satisfaction === undefined
    ? "No feedback yet"
    : `${feedback.citizen_satisfaction}%`;
  $("#satisfaction-panel").innerHTML = `
    <div class="satisfaction-score">${safe(satisfaction)}</div>
    <div class="meta-grid">
      <div><span>Responses</span><strong>${safe(feedback.responses || 0)}</strong></div>
      <div><span>Average rating</span><strong>${safe(feedback.average_rating || "--")}</strong></div>
      <div><span>Positive</span><strong>${safe(feedback.positive || 0)}</strong></div>
      <div><span>Negative</span><strong>${safe(feedback.negative || 0)}</strong></div>
    </div>
  `;
}

async function loadDashboard() {
  const data = await api("/api/dashboard");
  state.dashboard = data;
  renderKpis(data.kpis, data.feedback);
  renderBars("#dept-bars", data.by_department);
  renderBars("#status-bars", data.by_status);
  renderRankings(data.department_rankings);
  renderMap(data.map_points);
  renderRisk(data.predictive_risk);
  renderAllocation(data.resource_allocation);
  renderSatisfaction(data.feedback);
  $("#agent-flow-mini").innerHTML = data.agent_flow.map((agent) => `<div class="agent-node">${safe(agent)}</div>`).join("");
}

async function submitFeedback(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.dataset.id;
  const data = Object.fromEntries(new FormData(form).entries());
  const result = await api(`/api/complaints/${encodeURIComponent(id)}/feedback`, {
    method: "POST",
    body: JSON.stringify(data),
  });
  showToast(`Sentiment Agent classified feedback as ${result.sentiment.sentiment}`);
  $("#track-result").innerHTML = renderTrack(result.complaint);
  await loadDashboard();
}

async function checkHealth() {
  try {
    await api("/api/health");
    $("#health-pill").textContent = "Service online";
    $("#health-pill").classList.add("ok");
  } catch {
    $("#health-pill").textContent = "Service unavailable";
  }
}

function bindEvents() {
  $$(".nav-button").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  $("#complaint-form").addEventListener("submit", submitComplaint);
  $("#track-button").addEventListener("click", trackComplaint);
  $("#track-id").addEventListener("keydown", (event) => {
    if (event.key === "Enter") trackComplaint();
  });
  $("#refresh-complaints").addEventListener("click", loadComplaints);
  $("#run-monitor").addEventListener("click", runMonitor);
  $("#status-filter").addEventListener("change", renderOfficerList);
  $("#officer-list").addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    if (target.dataset.status) updateStatus(target.dataset.id, target.dataset.status);
    if (target.dataset.track) {
      $("#track-id").value = target.dataset.track;
      switchView("track");
      trackComplaint();
    }
  });
  $("#track-result").addEventListener("submit", (event) => {
    if (event.target.matches(".feedback-form")) submitFeedback(event);
  });
  $("#city-map").addEventListener("click", (event) => {
    const target = event.target.closest("[data-track]");
    if (!target) return;
    $("#track-id").value = target.dataset.track;
    switchView("track");
    trackComplaint();
  });
  $("#complaint-form").elements.image.addEventListener("change", (event) => {
    const file = event.target.files[0];
    const preview = $("#image-preview");
    if (!file) {
      preview.classList.add("hidden");
      return;
    }
    preview.src = URL.createObjectURL(file);
    preview.classList.remove("hidden");
  });
}

bindEvents();
checkHealth();
loadDashboard().catch(() => {});
