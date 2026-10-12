"""
Loading .env here, in the package's __init__, guarantees it runs before
any submodule (main, auth, models, services/*) is imported — several of
them read os.environ.get(...) once at import time (e.g. ai_service's
GEMINI_API_KEY), so this has to happen first or those reads see nothing.
"""

import os
from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))