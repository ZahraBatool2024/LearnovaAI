"""
Streamlit frontend. Talks to the FastAPI backend only over HTTP (with a
JWT bearer token once signed in) — this file has no database or AI logic,
so the backend can be swapped for any other client later untouched.

Run with:
    streamlit run frontend/app.py
"""

import os
import datetime
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Learnova AI", page_icon="📚", layout="wide")

# Same palette as the rest of the product, so the course colors and
# the chrome around them read as one designed thing rather than default
# Streamlit grey.
INK = "#20242A"
INK_SOFT = "#5B6168"
PAPER = "#F6F3EC"
LINE = "#DCD6C8"
ACCENT = "#2F5D8A"
ACCENT_SOFT = "#E7EEF5"
WARN = "#B5760A"
WARN_SOFT = "#FBEBD2"
DANGER = "#A6402A"
DANGER_SOFT = "#F6DDD6"
GOOD = "#43704A"
GOOD_SOFT = "#E4EEE1"
COURSE_PALETTE = [ACCENT, DANGER, GOOD, "#8A5FB0", WARN, "#3E7C7B"]


def course_color(course_id: str) -> str:
    return COURSE_PALETTE[abs(hash(course_id)) % len(COURSE_PALETTE)]


def inject_theme():
    st.markdown(f"""
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
      html, body, [class*="css"] {{ font-family: 'IBM Plex Sans', -apple-system, sans-serif; }}
      h1, h2, h3 {{ font-family: 'Fraunces', Georgia, serif !important; font-weight: 600 !important; }}

      section[data-testid="stSidebar"] {{
          background: {PAPER}; border-right: 1px solid {LINE};
      }}
      section[data-testid="stSidebar"] .stRadio > label {{ font-weight: 500; }}

      .stButton > button {{
          border-radius: 8px; border: 1px solid {ACCENT}; font-weight: 500;
      }}
      .stButton > button[kind="primary"], .stButton > button:hover {{
          border-color: {ACCENT};
      }}
      div[data-testid="stFormSubmitButton"] > button {{
          background: {ACCENT}; color: white; border: none;
      }}

      .shub-card {{
          background: white; border: 1px solid {LINE}; border-radius: 12px;
          padding: 18px 20px; margin-bottom: 10px;
      }}
      .shub-brand {{
          font-family: 'Fraunces', Georgia, serif; font-weight: 700; font-size: 26px;
          color: {INK}; margin-bottom: 2px;
      }}
      .shub-tagline {{ color: {INK_SOFT}; font-size: 14px; margin-bottom: 18px; }}
      .shub-pill {{
          display: inline-block; padding: 3px 10px; border-radius: 20px;
          font-size: 12px; font-weight: 600; white-space: nowrap;
      }}
      .shub-dot {{
          display: inline-block; width: 9px; height: 9px; border-radius: 50%;
          margin-right: 8px; vertical-align: middle;
      }}
      .shub-row {{
          display: flex; align-items: center; gap: 12px; padding: 10px 14px;
          background: white; border: 1px solid {LINE}; border-radius: 9px; margin-bottom: 6px;
      }}
      .shub-row .shub-title {{ flex: 1; font-size: 14.5px; color: {INK}; }}
      .shub-row .shub-meta {{ font-size: 12.5px; color: {INK_SOFT}; }}
    </style>
    """, unsafe_allow_html=True)


def pill(text: str, tone: str) -> str:
    colors = {
        "danger": (DANGER_SOFT, DANGER), "warn": (WARN_SOFT, WARN),
        "good": (GOOD_SOFT, GOOD), "neutral": (ACCENT_SOFT, ACCENT),
    }
    bg, fg = colors.get(tone, colors["neutral"])
    return f'<span class="shub-pill" style="background:{bg};color:{fg};">{text}</span>'


def badge_html(days: int) -> str:
    if days < 0:
        return pill(f"overdue {abs(days)}d", "danger")
    if days <= 2:
        return pill(f"🔔 due in {days}d" if days else "🔔 due today", "warn")
    if days <= 5:
        return pill(f"in {days}d", "warn")
    return pill(f"in {days}d", "good")


inject_theme()


def auth_headers():
    token = st.session_state.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def safe_error_detail(response, fallback: str) -> str:
    """The backend always returns JSON errors, but a proxy, a dead server, or
    a version mismatch could still hand back something else — never let a
    malformed error body crash the app on top of the original error."""
    if response is None:
        return fallback
    try:
        data = response.json()
        return data.get("detail", fallback) if isinstance(data, dict) else fallback
    except ValueError:
        text = (response.text or "").strip()
        return (text[:200] if text else fallback)


def api(method, path, **kwargs):
    headers = kwargs.pop("headers", {})
    headers.update(auth_headers())
    try:
        r = requests.request(method, f"{BACKEND_URL}{path}", headers=headers, timeout=60, **kwargs)
    except requests.RequestException:
        st.error("Can't reach the backend. Start it with: `uvicorn backend.main:app --reload`")
        st.stop()
    if r.status_code == 401:
        st.session_state.pop("token", None)
        st.session_state.pop("email", None)
        st.rerun()
    if not r.ok:
        st.error(safe_error_detail(r, f"Request failed ({r.status_code})."))
        st.stop()
    try:
        return r.json()
    except ValueError:
        st.error("The server returned an unexpected response.")
        st.stop()


# ---------------------------------------------------------------------------
# Sign in / sign up gate — nothing else renders until authenticated
# ---------------------------------------------------------------------------

if "token" not in st.session_state:
    left, mid, right = st.columns([1, 1.4, 1])
    with mid:
        st.markdown('<div class="shub-brand">📚 Learnova AI</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="shub-tagline">One place for every syllabus, deadline, and study session — '
            'sign in or create an account to get started.</div>', unsafe_allow_html=True,
        )

        with st.container(border=True):
            tab_login, tab_signup = st.tabs(["Sign in", "Create account"])

            with tab_login:
                with st.form("login_form"):
                    email = st.text_input("Email")
                    password = st.text_input("Password", type="password")
                    submitted = st.form_submit_button("Sign in", use_container_width=True)
                if submitted:
                    try:
                        r = requests.post(f"{BACKEND_URL}/auth/login", data={"username": email, "password": password}, timeout=30)
                    except requests.RequestException:
                        st.error("Can't reach the backend. Start it with: `uvicorn backend.main:app --reload`")
                    else:
                        if r.ok:
                            data = r.json()
                            st.session_state["token"] = data["access_token"]
                            st.session_state["email"] = data["email"]
                            st.rerun()
                        else:
                            st.error(safe_error_detail(r, "Incorrect email or password."))

            with tab_signup:
                with st.form("signup_form"):
                    new_username = st.text_input("Username", key="signup_username")
                    new_email = st.text_input("Email", key="signup_email")
                    new_password = st.text_input("Password (8+ characters)", type="password", key="signup_password")
                    submitted = st.form_submit_button("Create account", use_container_width=True)
                if submitted:
                    try:
                        r = requests.post(f"{BACKEND_URL}/auth/signup",
                                           json={"username": new_username.strip(), "email": new_email, "password": new_password}, timeout=30)
                    except requests.RequestException:
                        st.error("Can't reach the backend. Start it with: `uvicorn backend.main:app --reload`")
                    else:
                        if r.ok:
                            data = r.json()
                            st.session_state["token"] = data["access_token"]
                            st.session_state["email"] = data["email"]
                            st.rerun()
                        else:
                            st.error(safe_error_detail(r, "Couldn't create that account."))
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar: account, course list + creation (fully student-defined)
# ---------------------------------------------------------------------------

st.sidebar.markdown('<div class="shub-brand" style="font-size:20px;">📚 Learnova AI</div>', unsafe_allow_html=True)
st.sidebar.caption(f"Signed in as {st.session_state.get('email', '')}")
if st.sidebar.button("Sign out", use_container_width=True):
    st.session_state.pop("token", None)
    st.session_state.pop("email", None)
    st.rerun()

st.sidebar.divider()

me = api("GET", "/auth/me")
if not me.get("ai_assistant_available"):
    st.sidebar.caption("⚠️ AI assistant not configured by the app owner yet (missing GEMINI_API_KEY) — study tools use a basic fallback.")

courses = api("GET", "/courses")

course_names = {c["id"]: c["name"] for c in courses}
view = st.sidebar.radio("Workspace", ["🗓 Semester dashboard"] + [c["name"] for c in courses], label_visibility="collapsed")

with st.sidebar.expander("➕ Add a course"):
    new_name = st.text_input("Course name")
    new_subject = st.text_input("Subject keyword (optional)", help="e.g. statistics, biology — helps match open textbooks")
    if st.button("Create course", use_container_width=True) and new_name.strip():
        api("POST", "/courses", json={"name": new_name.strip(), "subject_hint": new_subject.strip()})
        st.rerun()

notes = api("GET", "/notifications")
if notes:
    st.sidebar.markdown("**🔔 Reminders**")
    for n in notes:
        if st.sidebar.button("Dismiss", key=f"dismiss_{n['id']}", use_container_width=True):
            api("PATCH", f"/notifications/{n['id']}/read")
            st.rerun()

# ---------------------------------------------------------------------------
# Semester dashboard
# ---------------------------------------------------------------------------

if view.startswith("🗓"):
    st.markdown('<div class="shub-brand">This semester</div>', unsafe_allow_html=True)
    rows = api("GET", "/dashboard")
    if not rows:
        st.info("Add a course and upload its syllabus to see deadlines here.")
    else:
        urgent = [r for r in rows if 0 <= r["days_until"] <= 2]
        if urgent:
            with st.container(border=True):
                st.markdown("**🔔 Due within 2 days**")
                for r in urgent:
                    st.markdown(
                        f'<div class="shub-row"><span class="shub-dot" style="background:{course_color(r["course_id"])}"></span>'
                        f'<span class="shub-title">{r["title"]}</span>'
                        f'<span class="shub-meta">{r["course_name"]}</span>'
                        f'<span class="shub-meta">{r["due_date"]}</span>'
                        f'{badge_html(r["days_until"])}</div>', unsafe_allow_html=True,
                    )
        pending = [r for r in rows if r.get("status") == "pending_review"]
        if pending:
            st.info(f"{len(pending)} auto-extracted deadline(s) need a quick confirm — open the course's Deadlines tab.")

        st.markdown("**All deadlines**")
        for r in rows:
            flag = " ⏳" if r.get("status") == "pending_review" else ""
            st.markdown(
                f'<div class="shub-row"><span class="shub-dot" style="background:{course_color(r["course_id"])}"></span>'
                f'<span class="shub-title">{r["title"]}{flag}</span>'
                f'<span class="shub-meta">{r["course_name"]}</span>'
                f'<span class="shub-meta">{r["due_date"]}</span>'
                f'{badge_html(r["days_until"])}</div>', unsafe_allow_html=True,
            )
    st.stop()


# ---------------------------------------------------------------------------
# Per-course workspace
# ---------------------------------------------------------------------------

course_id = next(cid for cid, name in course_names.items() if name == view)
st.markdown(f'<div class="shub-brand">{view}</div>', unsafe_allow_html=True)

tab_deadlines, tab_docs, tab_assistant, tab_study = st.tabs(
    ["Deadlines", "Syllabus & documents", "AI assistant", "Study tools"]
)

with tab_deadlines:
    items = api("GET", f"/courses/{course_id}/deadlines")
    urgent = [i for i in items if 0 <= i["days_until"] <= 2]
    if urgent:
        with st.container(border=True):
            st.markdown("**🔔 Due within 2 days**")
            for i in urgent:
                st.markdown(
                    f'<div class="shub-row"><span class="shub-title">{i["title"]}</span>'
                    f'<span class="shub-meta">{i["due_date"]}</span>{badge_html(i["days_until"])}</div>',
                    unsafe_allow_html=True,
                )

    pending = [i for i in items if i["status"] == "pending_review"]
    if pending:
        st.info("These were auto-detected but the extractor wasn't fully sure — confirm or remove them.")
        for i in pending:
            with st.expander(f"⏳ {i['title']} — {i['due_date']} ({i['confidence']} confidence)"):
                st.caption(f"Found in: \u201c{i['source_line']}\u201d")
                cc1, cc2 = st.columns(2)
                if cc1.button("✅ Confirm", key=f"confirm_{i['id']}", use_container_width=True):
                    api("PATCH", f"/deadlines/{i['id']}/confirm")
                    st.rerun()
                if cc2.button("✕ Remove", key=f"reject_{i['id']}", use_container_width=True):
                    api("DELETE", f"/deadlines/{i['id']}")
                    st.rerun()

    with st.form("add_deadline", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([3, 1.5, 1.5, 1])
        title = c1.text_input("Title")
        item_type = c2.selectbox("Type", ["assignment", "quiz", "exam", "reading", "project"])
        due = c3.date_input("Due date")
        submit = c4.form_submit_button("Add", use_container_width=True)
        if submit and title.strip():
            api("POST", f"/courses/{course_id}/deadlines", json={
                "title": title.strip(), "item_type": item_type, "due_date": due.isoformat(),
            })
            st.rerun()

    confirmed = [i for i in items if i["status"] != "pending_review"]
    if not confirmed:
        st.info("No confirmed deadlines yet. Upload a syllabus (auto-extracts them) or add one above.")
    else:
        for i in sorted(confirmed, key=lambda x: x["days_until"]):
            cols = st.columns([3, 1.2, 1.5, 1.3, 1])
            cols[0].write(i["title"])
            cols[1].write(i["item_type"])
            cols[2].write(i["due_date"])
            cols[3].markdown(badge_html(i["days_until"]) + (" · auto" if i["source"] == "auto" else ""), unsafe_allow_html=True)
            if cols[4].button("Remove", key=f"del_{i['id']}"):
                api("DELETE", f"/deadlines/{i['id']}")
                st.rerun()

with tab_docs:
    st.subheader("Upload today's syllabus, handout, or slides")
    uploaded = st.file_uploader("PDF, DOCX, PPTX, or TXT — upload as many as you get", accept_multiple_files=True)
    if uploaded and st.button("Ingest uploaded files"):
        for f in uploaded:
            headers = auth_headers()
            r = requests.post(f"{BACKEND_URL}/courses/{course_id}/documents", headers=headers,
                               files={"file": (f.name, f.getvalue())}, timeout=120)
            if r.ok:
                resp = r.json()
                added = resp["deadlines_auto_added"]
                st.success(f"{f.name}: indexed {resp['chunks_indexed']} chunk(s)"
                           + (f", found {len(added)} deadline(s)" if added else ""))
            else:
                st.error(f"{f.name}: {safe_error_detail(r, 'failed to process')}")
        st.rerun()

    st.subheader("Uploaded material")
    docs = api("GET", f"/courses/{course_id}/documents")
    if not docs:
        st.caption("Nothing uploaded yet.")
    for d in docs:
        with st.expander(f"{d['filename']}  ·  {d['uploaded_at'][:10]}"):
            st.text(d["preview"] + ("…" if len(d["preview"]) == 300 else ""))

with tab_assistant:
    st.caption("Grounded in this course's uploaded material first, but not limited to it — "
               "it'll fill gaps with Gemini's general knowledge, same as asking Gemini directly. "
               "Conversation is remembered across visits.")
    history = api("GET", f"/courses/{course_id}/assistant/history")
    for m in history:
        with st.chat_message("user" if m["role"] == "user" else "assistant"):
            st.write(m["content"])
    question = st.chat_input("Ask about this course — notes, or anything else...")
    if question:
        with st.chat_message("user"):
            st.write(question)
        result = api("POST", f"/courses/{course_id}/assistant/ask", json={"question": question})
        with st.chat_message("assistant"):
            st.write(result["answer"])
            st.caption(f"via {result.get('provider', 'local heuristic')}")
        st.rerun()

with tab_study:
    st.caption("Generate study material from pasted notes or an already-uploaded document.")
    docs = api("GET", f"/courses/{course_id}/documents")
    source_choice = st.radio("Source", ["Paste text"] + [d["filename"] for d in docs], horizontal=True)
    text_input = ""
    document_id = None
    if source_choice == "Paste text":
        text_input = st.text_area("Notes", height=150)
    else:
        document_id = next(d["id"] for d in docs if d["filename"] == source_choice)

    payload = {"text": text_input} if source_choice == "Paste text" else {"document_id": document_id}

    c1, c2, c3 = st.columns(3)
    if c1.button("Generate summary", use_container_width=True):
        st.session_state["study_result"] = ("summary", api("POST", f"/courses/{course_id}/study/summary", json=payload))
    if c2.button("Generate flashcards", use_container_width=True):
        st.session_state["study_result"] = ("flashcards", api("POST", f"/courses/{course_id}/study/flashcards", json=payload))
    if c3.button("Generate quiz", use_container_width=True):
        st.session_state["study_result"] = ("quiz", api("POST", f"/courses/{course_id}/study/quiz", json=payload))

    result = st.session_state.get("study_result")
    if result:
        kind, data = result
        st.caption(f"via {data.get('provider', 'local heuristic')}")
        if kind == "summary":
            st.write(data["summary"])
        elif kind == "flashcards":
            for card in data["cards"]:
                with st.expander(card["q"]):
                    st.write(card["a"])
        elif kind == "quiz":
            for i, q in enumerate(data["quiz"]):
                st.markdown(f"**{i+1}. {q['question']}**")
                choice = st.radio("", q["options"], key=f"quiz_{i}", label_visibility="collapsed")
                if st.button("Check", key=f"check_{i}"):
                    correct = q["options"][q["correct_index"]]
                    if choice == correct:
                        st.success("Correct — " + q["explanation"])
                    else:
                        st.error(f"Not quite. Correct answer: {correct}\n\n{q['explanation']}")

