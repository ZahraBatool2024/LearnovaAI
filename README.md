# Learnova AI

Learnova AI is a student-focused academic workspace that combines course management, document-based study support, deadline tracking, AI assistance, summaries, flashcards, quizzes, and in-app notifications.

## Features

- **Authentication:** create an account with username, email, and password; sign in with username or email; password hashing and JWT authentication.
- **Dashboard:** overview of courses, study documents, upcoming deadlines, pending reviews, and activity.
- **Course management:** create, edit, view, and delete courses.
- **Document management:** upload PDF, DOCX, PPTX, and TXT study material, extract text, index content, and delete documents.
- **AI course assistant:** ask questions using course material through retrieval-augmented generation (RAG), with source excerpts and a local fallback.
- **Study tools:** generate summaries, flashcards, and quizzes from uploaded material or supplied text.
- **Document access:** click a document name to preview extracted text or open the original file.
- **Deadline management:** add, edit, delete, complete, and review manually or automatically detected deadlines.
- **Notifications:** deadline reminders are displayed inside Learnova AI with persistent seen/unseen state. Opening notifications marks overdue deadline alerts as seen; upcoming alerts remain unread until marked seen. The bell badge counts unread alerts. Only in-app notifications are supported; push webhooks and email notifications have been removed.
- **Account/settings:** edit username on demand, view the read-only account email, manage profile photo, run AI diagnostics, and sign out.

## Technology Stack

### Backend
- Python
- FastAPI
- Uvicorn
- SQLAlchemy
- SQLite by default
- Pydantic
- JWT authentication
- APScheduler

### AI and RAG
- Gemini API integration
- Sentence Transformers when configured
- FAISS/vector retrieval
- Local fallback retrieval and study generation

### Frontend
- HTML
- CSS
- Vanilla JavaScript
- Responsive single-page interface
- Python HTTP server for simple local development

## Project Structure

```text
learnova_ai/
├── backend/
│   ├── main.py
│   ├── models.py
│   ├── database.py
│   ├── auth.py
│   └── services/
│       ├── ai_service.py
│       ├── document_service.py
│       ├── notification_service.py
│       ├── rag_service.py
│       └── syllabus_service.py
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── app.py
│   └── package.json
├── .env.example
├── requirements.txt
├── START_BACKEND.bat
├── START_BACKEND.sh
└── README.md
```

## Requirements

- Python 3.10+ recommended
- A virtual environment
- Gemini API key for Gemini-powered features
- Node.js is optional; the frontend can be served with Python

## Installation

Create and activate a virtual environment:

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and configure the AI key:

```env
GEMINI_API_KEY=your_api_key_here
```

Never commit `.env` or API keys to source control.

## Run the Backend

From the project root:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

API: `http://127.0.0.1:8000`

Swagger documentation: `http://127.0.0.1:8000/docs`

## Run the Frontend

Open a second terminal:

```bash
cd frontend
python -m http.server 5173
```

Open:

`http://127.0.0.1:5173`

Both backend and frontend must be running.

## Authentication

New accounts require:
- Username
- Email
- Password (minimum 8 characters)

The email is retained for account identity and is not displayed as the primary name throughout the interface. Users can sign in with either their username or email. Profile settings let users click **Edit** beside their username to change only the username; the email address is read-only in settings. Users can upload or remove a profile photo, which appears beside the notification icon in the top-right corner. Opening notifications marks overdue deadline alerts as seen while upcoming deadline alerts remain unread until marked seen. The bell badge counts unread alerts.

## RAG Workflow

1. A student uploads course material.
2. Text is extracted from the document.
3. Text is divided into chunks.
4. Chunks are indexed for retrieval.
5. The assistant retrieves relevant chunks for a question.
6. The AI model uses the retrieved context to generate an answer.
7. Relevant source excerpts are returned to the frontend.

## Deadline Workflow

Deadlines can be entered manually or extracted from uploaded academic material. Automatic extractions may be marked for review depending on confidence. Learnova AI creates an in-app reminder two days before a deadline. The Notifications page also shows overdue deadlines and deadlines due within the next seven days.

## Troubleshooting

### Frontend cannot reach the backend

Open `http://127.0.0.1:8000/docs`. If it does not open, start FastAPI:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### CORS error

Serve the frontend through HTTP rather than opening `index.html` with a `file://` URL. The Python server command above is recommended for local development.

### AI is unavailable

Check `GEMINI_API_KEY` in `.env` and restart FastAPI. Local fallback functionality remains available for supported study operations.

## Security and Production Notes

This project is primarily intended for academic/development use. Before production deployment, add HTTPS, strict production CORS origins, stronger secret management, rate limiting, production database migrations, secure token storage, upload scanning, and monitoring.

## Project Goal

Learnova AI aims to give students one organized workspace for courses, deadlines, academic documents, and AI-assisted study while keeping the student's own course material central to the learning workflow.
