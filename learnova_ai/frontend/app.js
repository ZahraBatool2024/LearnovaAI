const API = (window.STUDYHUB_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const state = {
  token: localStorage.getItem("studyhub_token") || "",
  email: localStorage.getItem("studyhub_email") || "",
  username: localStorage.getItem("studyhub_username") || "",
  view: "dashboard",
  courseId: null,
  courseTab: "overview",
  courses: [],
  dashboard: [],
  notifications: [],
  allNotifications: [],
  me: null,
  loading: false,
  modal: null,
};

function saveNavigation() {
  if (!state.token) return;
  localStorage.setItem("studyhub_navigation", JSON.stringify({
    view: state.view,
    courseId: state.courseId,
    courseTab: state.courseTab,
  }));
}

function restoreNavigation() {
  try {
    const saved = JSON.parse(localStorage.getItem("studyhub_navigation") || "null");
    if (!saved) return;
    state.view = saved.view || "dashboard";
    state.courseId = saved.courseId || null;
    state.courseTab = saved.courseTab || "overview";
    if (state.view === "course" && !state.courses.some(c => c.id === state.courseId)) {
      state.view = "courses";
      state.courseId = null;
      state.courseTab = "overview";
    }
  } catch {
    localStorage.removeItem("studyhub_navigation");
  }
}

const $ = (sel) => document.querySelector(sel);
const esc = (value = "") => String(value).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[c]));
const fmtDate = (s) => new Date(`${s}T00:00:00`).toLocaleDateString(undefined, {month:"short", day:"numeric", year:"numeric"});
const daysLabel = (n) => n < 0 ? `${Math.abs(n)}d overdue` : n === 0 ? "Due today" : n === 1 ? "Due tomorrow" : `${n} days`;
const initials = (name) => (name || "S").slice(0,1).toUpperCase();
function brandLogo() { return `<svg viewBox="0 0 40 40" aria-hidden="true" focusable="false"><defs><linearGradient id="learnovaGradient" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#14b8a6"/><stop offset="1" stop-color="#6366f1"/></linearGradient></defs><rect x="1" y="1" width="38" height="38" rx="12" fill="url(#learnovaGradient)"/><path d="M10 12.5c4.1-.9 7.5.1 10 2.4v14c-2.5-2.3-5.9-3.3-10-2.4z" fill="#fff" opacity=".98"/><path d="M30 12.5c-4.1-.9-7.5.1-10 2.4v14c2.5-2.3 5.9-3.3 10-2.4z" fill="#e0e7ff"/><path d="M20 15v14" stroke="#0f766e" stroke-width="1.5" stroke-linecap="round"/></svg>`; }
function profileAvatar(sizeClass = "") { return state.me?.profile_photo_url ? `<img class="profile-photo ${sizeClass}" src="${state.me.profile_photo_url}" alt="Profile photo">` : `<span class="avatar-fallback ${sizeClass}">${esc(initials(state.username || "Student"))}</span>`; }

function toast(message) {
  let stack = document.querySelector(".toast-stack");
  if (!stack) { stack = document.createElement("div"); stack.className = "toast-stack"; document.body.appendChild(stack); }
  const item = document.createElement("div"); item.className = "toast"; item.textContent = message; stack.appendChild(item);
  setTimeout(() => item.remove(), 3200);
}

function apiHeaders(extra = {}) {
  const h = {...extra};
  if (state.token) h.Authorization = `Bearer ${state.token}`;
  return h;
}

async function api(path, options = {}) {
  const opts = {...options, headers: apiHeaders(options.headers || {})};
  if (opts.body && !(opts.body instanceof FormData) && typeof opts.body !== "string") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  let response;
  try { response = await fetch(`${API}${path}`, opts); }
  catch (err) { throw new Error(`Cannot reach Learnova AI backend at ${API}. Start FastAPI with: uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000`); }
  if (response.status === 401) {
    logout(false);
    throw new Error("Your session has expired. Please sign in again.");
  }
  const text = await response.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = {detail: text || "Unexpected server response."}; }
  if (!response.ok) {
    let detail = data.detail || `Request failed (${response.status})`;
    if (Array.isArray(detail)) detail = detail.map(x => x.msg || JSON.stringify(x)).join("; ");
    throw new Error(detail);
  }
  return data;
}

function setAuth(data) {
  state.token = data.access_token;
  state.email = data.email;
  state.username = data.username || data.email?.split("@")[0] || "Student";
  localStorage.setItem("studyhub_token", state.token);
  localStorage.setItem("studyhub_email", state.email);
  localStorage.setItem("studyhub_username", state.username);
}
function logout(render = true) {
  state.token = ""; state.email = ""; state.username = ""; state.me = null; state.courses = [];
  localStorage.removeItem("studyhub_token"); localStorage.removeItem("studyhub_email"); localStorage.removeItem("studyhub_username");
  if (render) renderApp();
}

function authScreen() {
  return `<div class="auth"><div class="auth-box">
    <div class="auth-brand"><span class="brand-mark">${brandLogo()}</span> Learnova AI</div>
    <div class="auth-sub">Your personal academic workspace for courses, deadlines, documents and AI study tools.</div>
    <div class="auth-tabs"><button id="loginTab" class="active">Sign in</button><button id="signupTab">Create account</button></div>
    <div id="authForm"></div>
  </div></div>`;
}

function renderAuthForm(mode = "login") {
  const el = $("#authForm");
  el.innerHTML = mode === "login" ? `<form id="loginForm" class="grid" style="gap:13px">
      <div class="field"><label>Username or email</label><input class="input" id="loginEmail" required placeholder="your username"></div>
      <div class="field"><label>Password</label><input class="input" id="loginPassword" type="password" required placeholder="••••••••"></div>
      <button class="btn primary" type="submit">Sign in</button>
      <div id="authError"></div>
    </form>` : `<form id="signupForm" class="grid" style="gap:13px">
      <div class="field"><label>Username</label><input class="input" id="signupUsername" minlength="3" maxlength="30" required placeholder="e.g. zahra_01"></div>
      <div class="field"><label>Email</label><input class="input" id="signupEmail" type="email" required placeholder="you@example.com"><div class="muted" style="font-size:10px;margin-top:4px">Used privately for your account.</div></div>
      <div class="field"><label>Password</label><input class="input" id="signupPassword" type="password" minlength="8" required placeholder="At least 8 characters"></div>
      <button class="btn primary" type="submit">Create account</button>
      <div id="authError"></div>
    </form>`;
  if (mode === "login") $("#loginForm").onsubmit = async (e) => { e.preventDefault(); await doLogin(); };
  else $("#signupForm").onsubmit = async (e) => { e.preventDefault(); await doSignup(); };
}
async function doLogin() {
  const error = $("#authError"); error.innerHTML = "";
  try {
    const body = new URLSearchParams({username: $("#loginEmail").value, password: $("#loginPassword").value});
    const data = await api("/auth/login", {method:"POST", body, headers:{"Content-Type":"application/x-www-form-urlencoded"}});
    setAuth(data); await bootstrap(); renderApp();
  } catch (e) { error.innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
}
async function doSignup() {
  const error = $("#authError"); error.innerHTML = "";
  try {
    const data = await api("/auth/signup", {method:"POST", body:{username:$("#signupUsername").value, email:$("#signupEmail").value, password:$("#signupPassword").value}});
    setAuth(data); await bootstrap(); renderApp();
  } catch (e) { error.innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
}

async function bootstrap() {
  if (!state.token) return;
  state.me = await api("/auth/me");
  state.username = state.me.username || state.username || state.me.email?.split("@")[0] || "Student";
  state.email = state.me.email || state.email;
  localStorage.setItem("studyhub_username", state.username);
  state.courses = await api("/courses");
  state.dashboard = await api("/dashboard");
  state.notifications = await api("/notifications?unread_only=true");
}

function sidebar() {
  const unread = state.notifications.length;
  return `<aside class="sidebar" id="sidebar">
    <div class="brand"><span class="brand-mark">${brandLogo()}</span> Learnova AI</div>
    <div class="user-mini"><strong>${esc(state.username || "Student")}</strong><span>Student workspace</span></div>
    <nav class="nav">
      ${navButton("dashboard","▦","Dashboard")}
      ${navButton("courses","◫","Courses")}
      ${navButton("notifications","♢",`Notifications${unread ? ` <span style="margin-left:auto;background:#ef4444;color:#fff;padding:2px 6px;border-radius:999px;font-size:9px">${unread}</span>` : ""}`)}
      ${navButton("settings","⚙","Settings")}
    </nav>
    <div class="course-nav">
      <div class="course-nav-title">My courses</div>
      ${state.courses.length ? state.courses.map(c => `<button class="course-pill ${state.courseId===c.id ? "active":""}" data-course="${c.id}"><span class="course-dot"></span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.name)}</span></button>`).join("") : `<div style="padding:8px 10px;color:#71819b;font-size:11px">No courses yet</div>`}
    </div>
    <div class="sidebar-footer"><button class="btn" style="background:rgba(255,255,255,.05);border-color:rgba(255,255,255,.08);color:#dbe3f0" id="logoutBtn">↪ Sign out</button></div>
  </aside>`;
}
function navButton(view, icon, label) { return `<button class="${state.view===view ? "active":""}" data-view="${view}"><span class="nav-icon">${icon}</span>${label}</button>`; }

function shell(content, title) {
  return `<div class="app-shell">${sidebar()}<main class="main">
    <header class="topbar"><div class="top-actions"><button class="icon-btn mobile-menu" id="mobileMenu">☰</button><div class="topbar-title">${esc(title)}</div></div>
      <div class="top-actions"><button class="icon-btn" id="quickAdd" title="Add course">＋</button><button class="icon-btn" id="notifyBtn" title="Notifications">🔔${state.notifications.length ? `<span class="badge-count">${state.notifications.length}</span>` : ""}</button><button class="icon-btn account-btn" id="accountBtn" title="Profile and account">${profileAvatar("top-profile-photo")}</button></div>
    </header><section class="content">${content}</section></main></div>`;
}

function statCard(label, value, hint, icon) { return `<div class="card stat"><div class="accent"></div><div class="label">${icon} ${esc(label)}</div><div class="value">${value}</div><div class="hint">${esc(hint)}</div></div>`; }

function dashboardView() {
  const deadlines = [...state.dashboard].sort((a,b)=>a.days_until-b.days_until);
  const upcoming = deadlines.filter(d=>d.days_until>=0).length;
  const overdue = deadlines.filter(d=>d.days_until<0).length;
  const pending = deadlines.filter(d=>d.status!=="confirmed").length;
  const next = deadlines.filter(d=>d.days_until>=0).slice(0,5);
  const completed = Math.max(0, deadlines.length - upcoming - overdue);
  return shell(`<div class="page-head"><div><h1>Good ${new Date().getHours()<12?"morning":new Date().getHours()<18?"afternoon":"evening"} 👋</h1><p>Stay on top of your semester without juggling multiple tools.</p></div><div class="actions"><button class="btn primary" id="addCourseBtn">＋ Add course</button></div></div>
    <div class="grid grid-4" style="margin-bottom:18px">
      ${statCard("Courses", state.courses.length, "Active study spaces", "◫")}
      ${statCard("Upcoming", upcoming, "Deadlines still ahead", "◷")}
      ${statCard("Overdue", overdue, "Need your attention", "⚠")}
      ${statCard("Review queue", pending, "Auto-extracted items", "✓")}
    </div>
    <div class="grid grid-3">
      <div class="card" style="grid-column:span 2"><div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px"><h3>Next deadlines</h3></div>
        ${next.length ? `<div class="deadline-list">${next.map(deadlineRow).join("")}</div>` : `<div class="empty">No upcoming deadlines. Add a course and upload a syllabus to get started.</div>`}
      </div>
      <div class="card"><h3>Study overview</h3><div class="muted" style="font-size:12px;margin-bottom:10px">Coursework captured in Learnova AI</div>
        <div style="display:grid;gap:14px"><div><div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:6px"><span>Deadline coverage</span><strong>${deadlines.length ? Math.round((upcoming/deadlines.length)*100):0}%</strong></div><div class="progress"><span style="width:${deadlines.length ? Math.round((upcoming/deadlines.length)*100):0}%"></span></div></div>
        <div class="grid grid-2"><div><div class="muted" style="font-size:10px">Documents</div><strong style="font-size:20px">${state.courses.reduce((n,c)=>n+c.document_count,0)}</strong></div><div><div class="muted" style="font-size:10px">Due soon</div><strong style="font-size:20px">${deadlines.filter(d=>d.days_until>=0&&d.days_until<=7).length}</strong></div></div>
        <button class="btn" id="studyFromDashboard">Open a course</button></div>
      </div>
    </div>
    <div class="card" style="margin-top:18px"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:13px"><h3>My courses</h3><button class="btn small" id="coursesBtn">${state.courses.length ? "Manage courses" : "＋ Add course"}</button></div>${state.courses.length ? `<div class="grid grid-3">${state.courses.map(courseCard).join("")}</div>` : `<div class="empty">Create your first course to begin.</div>`}</div>
  `, "Dashboard");
}
function courseCard(c) { return `<div class="card course-card" data-course="${c.id}"><div class="course-title">${esc(c.name)}</div><div class="meta">${esc(c.subject_hint || "No subject hint")}</div><div class="metrics"><span class="metric">📄 ${c.document_count} docs</span><span class="metric">◷ ${c.upcoming_deadlines} upcoming</span></div></div>`; }
function deadlineRow(d, withCourse=true) { return `<div class="deadline-row"><div class="date-box"><strong>${new Date(`${d.due_date}T00:00:00`).getDate()}</strong><span>${new Date(`${d.due_date}T00:00:00`).toLocaleDateString(undefined,{month:"short"})}</span></div><div><div class="deadline-title">${esc(d.title)}</div><div class="deadline-course">${withCourse ? esc(d.course_name || "")+" · ":""}${esc(d.item_type)} · ${fmtDate(d.due_date)}</div></div><div class="actions"><span class="status ${d.days_until<0?"red":d.days_until<=2?"orange":"blue"}">${daysLabel(d.days_until)}</span></div></div>`; }

function coursesView() { return shell(`<div class="page-head"><div><h1>Courses</h1><p>Each course has its own documents, deadlines, AI memory and study tools.</p></div><button class="btn primary" id="addCourseBtn">＋ Add course</button></div><div class="grid grid-3">${state.courses.length ? state.courses.map(courseCard).join("") : `<div class="card empty" style="grid-column:1/-1">No courses yet. Create one to start.</div>`}</div>`, "Courses"); }


function courseView() {
  const c = state.courses.find(x=>x.id===state.courseId);
  if (!c) { state.view="courses"; return coursesView(); }
  const content = `<div class="page-head"><div><div class="muted" style="font-size:12px;cursor:pointer" id="backCourses">← All courses</div><h1 style="margin-top:5px">${esc(c.name)}</h1><p>${esc(c.subject_hint || "Course workspace")}</p></div><div class="actions"><button class="btn" id="editCourseBtn">Edit</button><button class="btn danger" id="deleteCourseBtn">Delete course</button></div></div>
    <div class="tabs">${["overview","documents","deadlines","assistant","study"].map(t=>`<button class="tab ${state.courseTab===t?"active":""}" data-course-tab="${t}">${({overview:"Overview",documents:"Documents",deadlines:"Deadlines",assistant:"AI Assistant",study:"Study Tools"})[t]}</button>`).join("")}</div><div id="courseTabBody"><div class="loading"><div class="spinner"></div></div></div>`;
  const page = shell(content, c.name);
  setTimeout(()=>loadCourseTab(c),0);
  return page;
}
async function loadCourseTab(c) {
  const body = $("#courseTabBody"); if(!body)return;
  try {
    if(state.courseTab==="overview") body.innerHTML = await overviewTab(c);
    if(state.courseTab==="documents") body.innerHTML = await documentsTab(c);
    if(state.courseTab==="deadlines") body.innerHTML = await deadlinesTab(c);
    if(state.courseTab==="assistant") body.innerHTML = await assistantTab(c);
    if(state.courseTab==="study") body.innerHTML = await studyTab(c);
    bindCourseTab(c);
  } catch(e) { body.innerHTML=`<div class="alert error">${esc(e.message)}</div>`; }
}
async function overviewTab(c) {
  const [docs, deadlines] = await Promise.all([api(`/courses/${c.id}/documents`), api(`/courses/${c.id}/deadlines`)]);
  const upcoming=deadlines.filter(d=>d.days_until>=0).sort((a,b)=>a.days_until-b.days_until).slice(0,4);
  return `<div class="grid grid-3"><div class="card">${statCard("Documents",docs.length,"Course materials","📄")}</div><div class="card">${statCard("Deadlines",deadlines.length,"Total tracked","◷")}</div><div class="card">${statCard("Due this week",deadlines.filter(d=>d.days_until>=0&&d.days_until<=7).length,"Focus items","⚡")}</div></div><div class="grid grid-2" style="margin-top:18px"><div class="card"><h3>Upcoming</h3>${upcoming.length?`<div class="deadline-list">${upcoming.map(d=>deadlineRow({...d,course_name:c.name},true)).join("")}</div>`:`<div class="empty">No upcoming deadlines.</div>`}</div><div class="card"><h3>Recommended next steps</h3><div class="grid" style="gap:10px"><button class="btn" data-course-tab="documents">📄 Upload lecture material</button><button class="btn" data-course-tab="assistant">💬 Ask the course assistant</button><button class="btn" data-course-tab="study">✨ Generate study material</button></div></div></div>`;
}
async function documentsTab(c) {
  const docs=await api(`/courses/${c.id}/documents`);
  return `<div class="grid grid-2"><div class="card"><h3>Upload course material</h3><p class="muted" style="font-size:12px">PDF, DOCX, PPTX and TXT are supported. Files are indexed for course-specific retrieval and may be scanned for deadlines.</p><div class="dropzone" id="dropzone"><div style="font-size:28px">☁</div><strong>Drop a file here</strong><div class="muted" style="font-size:11px;margin:6px 0 12px">or choose from your computer · max 25 MB</div><input id="fileInput" type="file" accept=".pdf,.docx,.pptx,.txt" hidden><button class="btn primary" id="chooseFile">Choose file</button><div id="uploadStatus" style="margin-top:10px"></div></div></div><div class="card"><h3>Course files <span class="muted" style="font-size:11px">(${docs.length})</span></h3><div class="file-list">${docs.length?docs.map(d=>`<div class="file-row"><div class="file-main"><div class="file-icon">📄</div><div style="min-width:0"><button class="file-name document-open-link" type="button" data-open-document="${d.id}" title="Open ${esc(d.filename)}">${esc(d.filename)}</button><div class="file-meta">${esc(d.source_type.toUpperCase())} · ${new Date(d.uploaded_at).toLocaleDateString()}</div></div></div><button class="btn small danger" data-delete-doc="${d.id}">Delete</button></div>`).join(""):`<div class="empty">No documents uploaded yet.</div>`}</div></div></div>`;
}
async function deadlinesTab(c) {
  const items=await api(`/courses/${c.id}/deadlines`);
  const pending=items.filter(x=>x.status!=="confirmed");
  return `<div class="grid grid-3"><div class="card" style="grid-column:span 2"><div style="display:flex;justify-content:space-between;align-items:center"><h3>Deadlines</h3><button class="btn primary small" id="addDeadlineBtn">＋ Add deadline</button></div>${items.length?`<div class="deadline-list" style="margin-top:12px">${items.map(d=>deadlineEditableRow(d)).join("")}</div>`:`<div class="empty">No deadlines for this course.</div>`}</div><div class="card"><h3>Review queue</h3><p class="muted" style="font-size:11px">Automatically extracted items with lower confidence should be confirmed before you rely on them.</p>${pending.length?pending.map(d=>`<div class="alert info"><strong>${esc(d.title)}</strong><br>${fmtDate(d.due_date)} · ${esc(d.confidence)} confidence<br><small>${esc(d.source_line||"")}</small><div class="actions" style="margin-top:8px"><button class="btn small success" data-confirm-deadline="${d.id}">Confirm</button><button class="btn small danger" data-delete-deadline="${d.id}">Dismiss</button></div></div>`).join(""):`<div class="empty">Review queue is clear.</div>`}</div></div>`;
}
function deadlineEditableRow(d) { return `<div class="deadline-row"><div class="date-box"><strong>${new Date(`${d.due_date}T00:00:00`).getDate()}</strong><span>${new Date(`${d.due_date}T00:00:00`).toLocaleDateString(undefined,{month:"short"})}</span></div><div><div class="deadline-title">${esc(d.title)}</div><div class="deadline-course">${esc(d.item_type)} · ${fmtDate(d.due_date)} · ${esc(d.source)}</div></div><div class="actions"><span class="status ${d.days_until<0?"red":d.days_until<=2?"orange":"blue"}">${daysLabel(d.days_until)}</span><button class="btn small" data-edit-deadline='${esc(JSON.stringify(d))}'>Edit</button><button class="btn small danger" data-delete-deadline="${d.id}">Delete</button></div></div>`; }

async function assistantTab(c) {
  const history=await api(`/courses/${c.id}/assistant/history`);
  return `<div class="card chat"><div class="chat-list" id="chatList">${history.length?history.map(m=>`<div class="bubble ${m.role==='user'?"user":"ai"}">${esc(m.content)}</div>`).join(""):`<div class="empty">Ask anything about ${esc(c.name)}. Uploaded course material is used as primary context when available.</div>`}</div><form class="chat-compose" id="chatForm"><textarea id="chatInput" placeholder="Ask a question about this course…" required></textarea><button class="btn primary" type="submit">Send ↗</button></form></div>`;
}
async function studyTab(c) {
  const docs=await api(`/courses/${c.id}/documents`), history=await api(`/courses/${c.id}/study/history`);
  return `<div class="grid grid-3"><div class="card" style="grid-column:span 2"><h3>Generate study material</h3><p class="muted" style="font-size:12px">Choose a document or paste text. Generated results are saved to this course.</p><div class="form-grid"><div class="field"><label>Source document</label><select class="select" id="studyDoc"><option value="">Select a document</option>${docs.map(d=>`<option value="${d.id}">${esc(d.filename)}</option>`).join("")}</select></div><div class="field"><label>Quick mode</label><select class="select" id="studyMode"><option value="summary">Summary</option><option value="flashcards">Flashcards</option><option value="quiz">Quiz</option></select></div><div class="field full"><label>Or paste text</label><textarea id="studyText" placeholder="Paste lecture notes here (optional)…"></textarea></div></div><button class="btn primary" id="generateStudy">Generate</button><div id="studyResult" style="margin-top:18px"></div></div><div class="card"><h3>Recent study artifacts</h3>${history.length?history.slice(0,12).map(a=>`<button type="button" class="artifact-item" data-open-artifact="${a.id}"><strong>${esc(({summary:"Summary",flashcards:"Flashcards",quiz:"Quiz"})[a.kind]||a.kind)}</strong><span class="muted">${new Date(a.created_at).toLocaleString()}</span><span class="artifact-open-hint">Click to open ↗</span></button>`).join(""):`<div class="empty">Nothing generated yet.</div>`}</div></div>`;
}

function notificationsView() { const notes=state.allNotifications; return shell(`<div class="page-head"><div><h1>Notifications</h1><p>Overdue alerts are marked seen when you open this page. Upcoming deadlines stay unread until you mark them seen.</p></div><span class="status blue">${state.notifications.length} unread</span></div><div class="card"><div class="deadline-list">${notes.length?notes.map(n=>`<div class="file-row notification-row ${n.is_read?"notification-seen":"notification-unread"}"><div class="notification-symbol ${n.kind === "deadline" ? "deadline-symbol" : ""}">${n.kind === "deadline" ? "◷" : "♢"}</div><div style="flex:1;min-width:0"><strong style="font-size:13px">${esc(n.message)}</strong><div class="muted" style="font-size:10px;margin-top:4px">${n.kind === "deadline" ? (n.days_until < 0 ? `${Math.abs(n.days_until)} day(s) overdue` : n.days_until === 0 ? "Due today" : `Due ${fmtDate(n.due_date)}`) : new Date(n.created_at).toLocaleString()} · In-app</div></div><span class="status ${n.is_read?"blue":n.days_until<0?"red":n.days_until<=2?"orange":"blue"}">${n.is_read?"Seen":n.kind==="deadline"?(n.days_until<0?"Overdue":n.days_until===0?"Today":n.days_until===1?"Tomorrow":"Upcoming"):"Unread"}</span>${!n.is_read?`<button class="btn small" data-read-note="${n.id}">Mark seen</button>`:""}</div>`).join(""):`<div class="empty">No notifications. Deadlines due within the next 7 days will appear here.</div>`}</div></div>`, "Notifications"); }

function settingsView() { return shell(`<div class="page-head"><div><h1>Settings</h1><p>Manage your profile and application preferences.</p></div></div><div class="grid grid-2"><div class="card profile-settings-card"><h3>Profile settings</h3><div class="profile-edit-preview">${profileAvatar("settings-profile-photo")}<div><strong>${esc(state.username || "Student")}</strong><div class="muted" style="font-size:11px">Your profile photo appears in the top-right corner.</div></div></div><form id="photoForm" class="grid" style="gap:10px;margin:12px 0"><div class="field"><label>Profile photo (PNG, JPG, WEBP or GIF; max 2 MB)</label><input class="input" id="profilePhoto" type="file" accept="image/png,image/jpeg,image/webp,image/gif"></div><div class="actions"><button class="btn" type="submit">Upload photo</button>${state.me?.profile_photo_url ? `<button class="btn danger" type="button" id="removePhotoBtn">Remove photo</button>` : ""}</div></form><div class="username-setting"><div class="field"><label>Username</label><div id="usernameDisplayRow" class="username-display-row"><strong id="currentUsername">${esc(state.username)}</strong><button class="btn small" type="button" id="editUsernameBtn">Edit</button></div><form id="profileForm" class="grid" style="gap:10px;display:none"><input class="input" id="profileUsername" value="${esc(state.username)}" minlength="3" maxlength="30" required><div class="actions"><button class="btn primary" type="submit">Save username</button><button class="btn" type="button" id="cancelUsernameBtn">Cancel</button></div></form></div><div class="field" style="margin-top:12px"><label>Email address</label><div class="readonly-profile-value">${esc(state.email || "")}</div><div class="muted" style="font-size:10px;margin-top:4px">Email address cannot be changed here.</div></div></div></div><div class="card"><h3>Notifications</h3><div class="alert info">Deadline reminders, overdue tasks and account alerts appear inside Learnova AI.</div></div><div class="card"><h3>AI status</h3><div class="alert ${state.me?.ai_assistant_available?"success":"info"}">${state.me?.ai_assistant_available?"AI assistant is configured on the backend.":"AI provider is not configured; local fallback study tools remain available."}</div><button class="btn" id="diagnosticsBtn">Run AI diagnostics</button><div id="diagnostics" style="margin-top:10px"></div></div><div class="card"><h3>Account</h3><p class="muted" style="font-size:12px">Your username and email are used for your account. Your email is not displayed in the site header.</p><button class="btn danger" id="settingsLogout">↪ Sign out</button></div></div>`, "Settings"); }
function renderApp() {
  const root = $("#app");
  if (!root) return;
  if (!state.token) {
    root.innerHTML = authScreen();
    bindAuth();
    return;
  }
  if (state.view === "course" && !state.courses.some(c => c.id === state.courseId)) {
    state.view = "courses";
    state.courseId = null;
    state.courseTab = "overview";
  }
  if (state.view === "dashboard") root.innerHTML = dashboardView();
  else if (state.view === "courses") root.innerHTML = coursesView();
  else if (state.view === "notifications") root.innerHTML = notificationsView();
  else if (state.view === "settings") root.innerHTML = settingsView();
  else if (state.view === "course") root.innerHTML = courseView();
  else { state.view = "dashboard"; root.innerHTML = dashboardView(); }
  saveNavigation();
  bindShell();
  if (state.view === "course") bindCourseShell();
}

function bindAuth(){ $("#loginTab").onclick=()=>{ $("#loginTab").classList.add("active");$("#signupTab").classList.remove("active");renderAuthForm("login");}; $("#signupTab").onclick=()=>{ $("#signupTab").classList.add("active");$("#loginTab").classList.remove("active");renderAuthForm("signup");}; renderAuthForm("login"); }
function bindShell(){
  document.querySelectorAll("[data-view]").forEach(b=>b.onclick=async()=>{if(b.dataset.view==="notifications"){try{for(const n of state.notifications.filter(n=>n.kind==="deadline"&&n.days_until<0&&!n.is_read)){await api(`/notifications/${n.id}/read`,{method:"PATCH"});}state.allNotifications=await api("/notifications?unread_only=false");state.notifications=await api("/notifications?unread_only=true");}catch(e){toast(e.message);}}state.view=b.dataset.view;state.courseId=null;state.courseTab="overview";saveNavigation();renderApp();});
  document.querySelectorAll("[data-course]").forEach(b=>b.onclick=()=>{state.courseId=b.dataset.course;state.view="course";state.courseTab="overview";saveNavigation();renderApp();});
  $("#logoutBtn")?.addEventListener("click",()=>logout());
  $("#settingsLogout")?.addEventListener("click",()=>logout());
  $("#mobileMenu")?.addEventListener("click",()=>$("#sidebar").classList.toggle("open"));
  $("#quickAdd")?.addEventListener("click",()=>openCourseModal());
  $("#accountBtn")?.addEventListener("click",openAccountModal);
  $("#notifyBtn")?.addEventListener("click",async()=>{try{for(const n of state.notifications.filter(n=>n.kind==="deadline"&&n.days_until<0&&!n.is_read)){await api(`/notifications/${n.id}/read`,{method:"PATCH"});}state.allNotifications=await api("/notifications?unread_only=false");state.notifications=await api("/notifications?unread_only=true");}catch(e){toast(e.message);}state.view="notifications";saveNavigation();renderApp();});
  $("#addCourseBtn")?.addEventListener("click",()=>openCourseModal());
  $("#coursesBtn")?.addEventListener("click",()=>{if(!state.courses.length){openCourseModal();}else{state.view="courses";saveNavigation();renderApp();}});
  $("#studyFromDashboard")?.addEventListener("click",()=>{if(state.courses[0]){state.courseId=state.courses[0].id;state.view="course";state.courseTab="study";saveNavigation();renderApp();}else openCourseModal();});
  document.querySelectorAll("[data-read-note]").forEach(b=>b.onclick=async()=>{try{await api(`/notifications/${b.dataset.readNote}/read`,{method:"PATCH"});state.allNotifications=await api("/notifications?unread_only=false");state.notifications=await api("/notifications?unread_only=true");renderApp();}catch(e){toast(e.message);}});
  $("#editUsernameBtn")?.addEventListener("click",()=>{const form=$("#profileForm");form.style.display="grid";$("#usernameDisplayRow").style.display="none";$("#profileUsername").focus();});
  $("#cancelUsernameBtn")?.addEventListener("click",()=>{const form=$("#profileForm");form.style.display="none";$("#usernameDisplayRow").style.display="flex";$("#profileUsername").value=state.username;});
  $("#diagnosticsBtn")?.addEventListener("click",diagnostics);
  $("#profileForm")?.addEventListener("submit",async e=>{e.preventDefault();try{await api("/auth/me",{method:"PATCH",body:{username:$("#profileUsername").value}});state.me=await api("/auth/me");state.username=state.me.username;localStorage.setItem("studyhub_username",state.username);toast("Username updated");renderApp();}catch(err){toast(err.message);}});
  $("#photoForm")?.addEventListener("submit",async e=>{e.preventDefault();const file=$("#profilePhoto")?.files?.[0];if(!file){toast("Choose a profile photo first.");return;}const fd=new FormData();fd.append("file",file);try{await api("/auth/me/photo",{method:"POST",body:fd});state.me=await api("/auth/me");toast("Profile photo updated");renderApp();}catch(err){toast(err.message);}});
  $("#removePhotoBtn")?.addEventListener("click",async()=>{try{await api("/auth/me/photo",{method:"DELETE"});state.me=await api("/auth/me");toast("Profile photo removed");renderApp();}catch(err){toast(err.message);}});
}
function bindCourseShell(){ $("#backCourses")?.addEventListener("click",()=>{state.view="courses";state.courseId=null;state.courseTab="overview";saveNavigation();renderApp();}); $("#editCourseBtn")?.addEventListener("click",()=>openCourseModal(state.courses.find(c=>c.id===state.courseId))); $("#deleteCourseBtn")?.addEventListener("click",deleteCourse); document.querySelectorAll("[data-course-tab]").forEach(b=>b.onclick=()=>{state.courseTab=b.dataset.courseTab; if(state.view!=="course")state.view="course"; saveNavigation(); renderApp();}); }
function bindCourseTab(c){ document.querySelectorAll("[data-course-tab]").forEach(b=>b.onclick=()=>{state.courseTab=b.dataset.courseTab;saveNavigation();renderApp();});
  $("#chooseFile")?.addEventListener("click",()=>$("#fileInput").click()); $("#fileInput")?.addEventListener("change",e=>uploadFile(c,e.target.files[0]));
  const dz=$("#dropzone"); if(dz){["dragenter","dragover"].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add("drag")}));["dragleave","drop"].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.remove("drag")}));dz.addEventListener("drop",e=>uploadFile(c,e.dataTransfer.files[0]));}
  document.querySelectorAll("[data-delete-doc]").forEach(b=>b.onclick=async()=>{if(!confirm("Delete this document and rebuild the course index?"))return;try{await api(`/documents/${b.dataset.deleteDoc}`,{method:"DELETE"});toast("Document deleted");loadCourseTab(c);}catch(e){toast(e.message);}});
  document.querySelectorAll("[data-open-document]").forEach(b=>b.onclick=async()=>{
    const id=b.dataset.openDocument; const name=b.textContent.trim();
    try { const docs=await api(`/courses/${c.id}/documents`); const d=docs.find(x=>x.id===id); if(!d)throw new Error("Document not found");
      const modal=openModal(`<div class="modal-head"><div><h3>${esc(d.filename)}</h3><div class="muted" style="font-size:11px">Document preview · ${esc(d.source_type.toUpperCase())}</div></div><button class="icon-btn" data-close>×</button></div><div class="document-preview">${esc(d.preview||"No text preview is available for this document.")}${(d.preview||"").length>=300?"…":""}</div><div class="actions" style="margin-top:14px"><button class="btn primary" id="openOriginalDoc">Open original file</button></div>`);
      modal.querySelector("[data-close]").onclick=()=>modal.remove(); modal.querySelector("#openOriginalDoc").onclick=async()=>{const win=window.open("about:blank","_blank");try{const response=await fetch(`${API}/documents/${id}/open`,{headers:apiHeaders()});if(!response.ok){const msg=await response.text();throw new Error(msg||`Open failed (${response.status})`);}const blob=await response.blob();const url=URL.createObjectURL(blob);if(win)win.location.href=url;else window.location.href=url;modal.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}catch(err){if(win)win.close();toast(err.message||"Could not open this document");}};
    } catch(e){toast(e.message||`Could not open ${name}`);}
  });
  $("#addDeadlineBtn")?.addEventListener("click",()=>openDeadlineModal(c)); document.querySelectorAll("[data-confirm-deadline]").forEach(b=>b.onclick=async()=>{await api(`/deadlines/${b.dataset.confirmDeadline}/confirm`,{method:"PATCH"});toast("Deadline confirmed");loadCourseTab(c);}); document.querySelectorAll("[data-delete-deadline]").forEach(b=>b.onclick=async()=>{if(!confirm("Delete this deadline?"))return;await api(`/deadlines/${b.dataset.deleteDeadline}`,{method:"DELETE"});toast("Deadline deleted");state.dashboard=await api("/dashboard");loadCourseTab(c);}); document.querySelectorAll("[data-edit-deadline]").forEach(b=>b.onclick=()=>openDeadlineModal(c,JSON.parse(b.dataset.editDeadline)));
  $("#chatForm")?.addEventListener("submit",async e=>{e.preventDefault();const input=$("#chatInput"), q=input.value.trim();if(!q)return;const list=$("#chatList");list.innerHTML+=`<div class="bubble user">${esc(q)}</div><div class="bubble ai" id="typing"><span class="spinner"></span></div>`;list.scrollTop=list.scrollHeight;input.value="";try{const r=await api(`/courses/${c.id}/assistant/ask`,{method:"POST",body:{question:q}});$("#typing")?.remove();list.innerHTML+=`<div class="bubble ai">${esc(r.answer)}${r.sources?.length?`<div class="source-list">${r.sources.map(s=>`<span class="source-chip">Source: ${esc(s.slice(0,70))}…</span>`).join("")}</div>`:""}<div class="muted" style="font-size:9px;margin-top:7px">Provider: ${esc(r.provider||"local")}</div></div>`;list.scrollTop=list.scrollHeight;}catch(err){$("#typing")?.remove();toast(err.message);}});
  $("#generateStudy")?.addEventListener("click",()=>generateStudy(c));
  document.querySelectorAll("[data-open-artifact]").forEach(b=>b.onclick=async()=>{try{const items=await api(`/courses/${c.id}/study/history`);const item=items.find(x=>x.id===b.dataset.openArtifact);if(!item)throw new Error("Study artifact not found");const out=$("#studyResult");if(!out){state.courseTab="study";renderApp();return;}renderArtifact(out,item);out.scrollIntoView({behavior:"smooth",block:"start"});}catch(e){toast(e.message);}});
}
async function uploadFile(c,file){
  if(!file)return;
  state.view="course"; state.courseId=c.id; state.courseTab="documents"; saveNavigation();
  const status=$("#uploadStatus");
  if(file.size>25*1024*1024){status.innerHTML=`<div class="alert error">Maximum file size is 25 MB.</div>`;return;}
  const fd=new FormData(); fd.append("file",file);
  status.innerHTML=`<div class="alert info">Uploading and indexing <strong>${esc(file.name)}</strong>…</div>`;
  try{
    const r=await api(`/courses/${c.id}/documents`,{method:"POST",body:fd});
    state.courses=await api("/courses"); state.dashboard=await api("/dashboard");
    await loadCourseTab(c);
    const refreshedStatus=$("#uploadStatus");
    if(refreshedStatus) refreshedStatus.innerHTML=`<div class="alert success">Indexed ${r.chunks_indexed} chunks. ${r.deadlines_auto_added?.length||0} deadlines detected.</div>`;
  }catch(e){
    const refreshedStatus=$("#uploadStatus");
    if(refreshedStatus) refreshedStatus.innerHTML=`<div class="alert error">${esc(e.message)}</div>`;
  }
}

async function generateStudy(c){
  const mode=$("#studyMode").value, doc=$("#studyDoc").value, text=$("#studyText").value.trim();
  if(!doc&&!text){toast("Choose a document or paste text first.");return;}
  const out=$("#studyResult");out.innerHTML=`<div class="alert info">Generating ${esc(mode)}…</div>`;
  try{
    const r=await api(`/courses/${c.id}/study/${mode}`,{method:"POST",body:{document_id:doc||undefined,text:text||undefined}});
    const history=await api(`/courses/${c.id}/study/history`);
    const artifact=history.find(a=>a.kind===mode && (mode==="summary"?a.content?.summary===r.summary:mode==="flashcards"?JSON.stringify(a.content?.cards||[])===JSON.stringify(r.cards||[]):JSON.stringify(a.content?.quiz||[])===JSON.stringify(r.quiz||[]))) || history[0];
    if(artifact) renderArtifact(out,artifact,r.provider); else if(mode==="summary") out.innerHTML=`<div class="card"><div class="study-output">${esc(r.summary)}</div></div>`;
    else if(mode==="flashcards") renderFlashcards(out,r.cards||[],r.provider);
    else renderQuiz(out,r.quiz||[],r.provider);
    await loadCourseTab(c);
    const refreshedOut=$("#studyResult");
    if(refreshedOut && artifact) renderArtifact(refreshedOut,artifact,r.provider);
    refreshedOut?.scrollIntoView({behavior:"smooth",block:"start"});
  }catch(e){out.innerHTML=`<div class="alert error">${esc(e.message)}</div>`;}
}
function renderArtifact(out,artifact,provider){
  const content=artifact.content||{};
  if(artifact.kind==="summary") out.innerHTML=`<div class="card" style="box-shadow:none"><div class="muted" style="font-size:10px;margin-bottom:8px">Saved summary${provider?` · ${esc(provider)}`:""}</div><div class="study-output">${esc(content.summary||"No summary content was saved.")}</div></div>`;
  else if(artifact.kind==="flashcards") renderFlashcards(out,content.cards||[],provider||"saved artifact");
  else if(artifact.kind==="quiz") renderQuiz(out,content.quiz||[],provider||"saved artifact");
  else out.innerHTML=`<div class="alert info">This saved artifact type is not supported yet.</div>`;
}
function renderFlashcards(out,cards,provider){
  if(!cards.length){out.innerHTML=`<div class="alert info">No flashcards could be generated from this document. Try a document with more readable text or use an AI API key.</div>`;return;}
  out.innerHTML=`<div class="muted" style="font-size:10px;margin-bottom:10px">${esc(provider||"study material")} · ${cards.length} flashcards · click a card to reveal its answer</div><div class="grid grid-2">${cards.map((x,i)=>`<button type="button" class="flashcard" data-flip="${i}"><div class="flashcard-inner"><div class="flash-face"><div class="flash-label">Question</div><strong>${esc(x.q||x.question||"")}</strong><div class="muted" style="font-size:10px;margin-top:auto">Click to flip</div></div><div class="flash-face back"><div class="flash-label">Answer</div><div>${esc(x.a||x.answer||"")}</div></div></div></button>`).join("")}</div>`;
  out.querySelectorAll("[data-flip]").forEach(x=>x.onclick=()=>x.classList.toggle("flipped"));
}

function renderQuiz(out,quiz,provider){
  let index=0, answers=[];
  const optionText=(o)=>typeof o==="string"?o:(o?.label??o?.text??o?.answer??String(o??""));
  const correctIndex=(q)=>{
    const opts=q.options||[];
    const raw=q.correct_index ?? q.correctIndex ?? q.answer_index ?? q.answerIndex;
    if(raw!==undefined && raw!==null && raw!=="") {
      const n=Number(raw);
      if(Number.isInteger(n)&&n>=0&&n<opts.length)return n;
      const letter=String(raw).trim().toUpperCase();
      if(/^[A-D]$/.test(letter)) { const idx=letter.charCodeAt(0)-65; if(idx<opts.length)return idx; }
    }
    const answer=q.correct_answer ?? q.correctAnswer ?? q.answer ?? q.correct_option ?? q.correctOption;
    if(answer!==undefined && answer!==null) {
      const target=String(typeof answer==="object"?(answer.label??answer.text??answer.answer??""):answer).trim().toLowerCase();
      const idx=opts.findIndex(o=>optionText(o).trim().toLowerCase()===target);
      if(idx>=0)return idx;
    }
    return -1;
  };
  const draw=()=>{
    if(!quiz.length){out.innerHTML=`<div class="empty">The system could not generate a quiz from this material.</div>`;return;}
    const q=quiz[index];
    out.innerHTML=`<div class="card" style="box-shadow:none;background:#f8fafc"><div class="muted" style="font-size:10px">Question ${index+1} of ${quiz.length} · ${esc(provider||"local")} · 1 mark</div><h3 style="margin-top:8px">${esc(q.question||q.q||"Question")}</h3><div>${(q.options||[]).map((o,i)=>`<button type="button" class="quiz-option ${answers[index]===i?"selected":""}" data-qopt="${i}">${esc(optionText(o))}</button>`).join("")}</div><div class="actions" style="margin-top:15px;justify-content:space-between"><span class="muted" style="font-size:10px">${index?"Your earlier answers are kept":"Choose one answer to earn the mark"}</span><button class="btn primary" id="nextQuiz">${index===quiz.length-1?"Submit quiz":"Next question"}</button></div></div>`;
    out.querySelectorAll("[data-qopt]").forEach(b=>b.onclick=()=>{out.querySelectorAll("[data-qopt]").forEach(x=>x.classList.remove("selected"));b.classList.add("selected");answers[index]=Number(b.dataset.qopt);});
    out.querySelector("#nextQuiz").onclick=()=>{
      if(answers[index]===undefined){toast("Select an answer first.");return;}
      if(index===quiz.length-1){
        const score=quiz.reduce((sum,item,i)=>sum+(correctIndex(item)===answers[i]?1:0),0);
        const review=quiz.map((item,i)=>{
          const opts=item.options||[]; const ci=correctIndex(item); const chosen=answers[i]; const correct=ci===chosen;
          return `<div class="card" style="box-shadow:none;border:1px solid ${correct?"#86efac":"#fca5a5"};margin-top:12px"><div style="display:flex;justify-content:space-between;gap:12px;align-items:start"><strong>Q${i+1}. ${esc(item.question||item.q||"Question")}</strong><strong style="white-space:nowrap;color:${correct?"#047857":"#b91c1c"}">${correct?"1/1 mark":"0/1 marks"}</strong></div><div class="muted" style="font-size:12px;margin-top:10px">Your answer: <strong>${esc(optionText(opts[chosen]))}</strong></div><div style="font-size:12px;margin-top:5px">Correct answer: <strong>${ci>=0?esc(optionText(opts[ci])):"Not supplied by the quiz generator"}</strong></div>${item.explanation?`<div style="font-size:12px;margin-top:8px"><strong>Explanation:</strong> ${esc(item.explanation)}</div>`:`${ci>=0?`<div style="font-size:12px;margin-top:8px">Review the correct option above against the source document.</div>`:`<div class="alert info" style="margin-top:8px">This question has no answer key, so its mark could not be verified.</div>`}`}</div>`;
        }).join("");
        out.innerHTML=`<div class="card" style="box-shadow:none;background:#f8fafc;padding:24px"><div style="font-size:34px">🎯</div><h2 style="margin:6px 0">Quiz results</h2><div style="font-size:28px;font-weight:800">${score}/${quiz.length} marks</div><p class="muted">${Math.round(score/quiz.length*100)}% · Each question is worth 1 mark.</p><button class="btn primary" id="restartQuiz">Generate another quiz</button></div><h3 style="margin-top:20px">Answer review</h3><p class="muted" style="font-size:12px">Review every question, your answer, the correct answer and its marks.</p>${review}`;
        out.querySelector("#restartQuiz").onclick=()=>generateStudy(state.courses.find(x=>x.id===state.courseId));
      }else{index++;draw();}
    };
  };
  draw();
}

function openModal(html){const div=document.createElement("div");div.className="modal-backdrop";div.innerHTML=`<div class="modal">${html}</div>`;document.body.appendChild(div);div.addEventListener("click",e=>{if(e.target===div)div.remove();});return div;}
function openAccountModal(){const modal=openModal(`<div class="modal-head"><div><h3>Account</h3><div class="muted" style="font-size:11px">Your account profile</div></div><button class="icon-btn" data-close>×</button></div><div class="grid" style="gap:12px"><div class="account-profile">${profileAvatar("account-avatar-photo")}<div><strong style="font-size:18px">${esc(state.username)}</strong><div class="muted" style="font-size:11px">Student account</div></div></div><button class="btn" id="accountSettingsBtn">⚙ Open settings</button><button class="btn danger" id="accountLogoutBtn">↪ Sign out</button></div>`);modal.querySelector("[data-close]").onclick=()=>modal.remove();modal.querySelector("#accountSettingsBtn").onclick=()=>{modal.remove();state.view="settings";saveNavigation();renderApp();};modal.querySelector("#accountLogoutBtn").onclick=()=>{modal.remove();logout();};}
function openCourseModal(course=null){const modal=openModal(`<div class="modal-head"><h3>${course?"Edit course":"Create a course"}</h3><button class="icon-btn" data-close>×</button></div><form id="courseForm" class="grid"><div class="field"><label>Course name</label><input class="input" id="courseName" required value="${esc(course?.name||"")}" placeholder="e.g. Database Systems"></div><div class="field"><label>Subject hint</label><input class="input" id="courseHint" value="${esc(course?.subject_hint||"")}" placeholder="e.g. databases, SQL"></div><button class="btn primary" type="submit">${course?"Save changes":"Create course"}</button></form>`);modal.querySelector("[data-close]").onclick=()=>modal.remove();modal.querySelector("#courseForm").onsubmit=async e=>{e.preventDefault();try{const body={name:modal.querySelector("#courseName").value,subject_hint:modal.querySelector("#courseHint").value};if(course)await api(`/courses/${course.id}`,{method:"PATCH",body});else await api("/courses",{method:"POST",body});state.courses=await api("/courses");state.dashboard=await api("/dashboard");modal.remove();toast(course?"Course updated":"Course created");renderApp();}catch(err){toast(err.message);}};}
function openDeadlineModal(c,d=null){const modal=openModal(`<div class="modal-head"><h3>${d?"Edit deadline":"Add deadline"}</h3><button class="icon-btn" data-close>×</button></div><form id="deadlineForm" class="grid"><div class="field"><label>Title</label><input class="input" id="dTitle" required value="${esc(d?.title||"")}" placeholder="Assignment 1"></div><div class="field"><label>Type</label><select class="select" id="dType"><option ${d?.item_type==="assignment"?"selected":""}>assignment</option><option ${d?.item_type==="quiz"?"selected":""}>quiz</option><option ${d?.item_type==="exam"?"selected":""}>exam</option><option ${d?.item_type==="project"?"selected":""}>project</option><option ${d?.item_type==="reading"?"selected":""}>reading</option></select></div><div class="field"><label>Due date</label><input class="input" id="dDate" type="date" required value="${esc(d?.due_date||"")}"></div><button class="btn primary" type="submit">${d?"Save changes":"Add deadline"}</button></form>`);modal.querySelector("[data-close]").onclick=()=>modal.remove();modal.querySelector("#deadlineForm").onsubmit=async e=>{e.preventDefault();try{const body={title:modal.querySelector("#dTitle").value,item_type:modal.querySelector("#dType").value,due_date:modal.querySelector("#dDate").value};if(d)await api(`/deadlines/${d.id}`,{method:"PATCH",body});else await api(`/courses/${c.id}/deadlines`,{method:"POST",body});state.dashboard=await api("/dashboard");modal.remove();toast(d?"Deadline updated":"Deadline added");loadCourseTab(c);}catch(err){toast(err.message);}};}
async function deleteCourse(){const c=state.courses.find(x=>x.id===state.courseId);if(!c||!confirm(`Delete ${c.name}? This removes its documents, deadlines and chat history.`))return;try{await api(`/courses/${c.id}`,{method:"DELETE"});state.courses=await api("/courses");state.dashboard=await api("/dashboard");state.courseId=null;state.view="courses";toast("Course deleted");renderApp();}catch(e){toast(e.message);}}
async function diagnostics(){const out=$("#diagnostics");out.innerHTML=`<div class="alert info">Checking Gemini…</div>`;try{const r=await api("/diagnostics/gemini");out.innerHTML=`<div class="alert ${r.ok?"success":"error"}">${esc(r.ok?`Connected: ${r.model} — ${r.sample_reply}`:(r.hint||r.reason||"AI check failed"))}</div>`;}catch(e){out.innerHTML=`<div class="alert error">${esc(e.message)}</div>`;}}

async function start(){
  if(state.token){ try{await bootstrap(); restoreNavigation();}catch(e){logout(false);} }
  renderApp();
}
start();
