import os
from dotenv import load_dotenv

load_dotenv()


def _env(name, default):
    """Treat unset AND empty values as missing (GitHub passes empty strings for unset variables)."""
    v = os.environ.get(name, "")
    return v.strip() or default


DATABASE_URL = _env("DATABASE_URL", "")
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY", "")
EXTRACT_MODEL = _env("EXTRACT_MODEL", "claude-haiku-4-5-20251001")
MAX_SOURCES_PER_RUN = int(_env("MAX_SOURCES_PER_RUN", "80"))
MAX_EXTRACTIONS_PER_RUN = int(_env("MAX_EXTRACTIONS_PER_RUN", "60"))
# Identifies the bot honestly, in the browser-compatible format many government sites expect.
USER_AGENT = _env("USER_AGENT", "Mozilla/5.0 (compatible; ArtsIntelligenceBot/0.1; research)")
SUPABASE_URL = _env("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = _env("SUPABASE_SERVICE_KEY", "")

# Rough per-million-token prices used only for the job_runs cost estimate.
PRICE_PER_MTOK = {"input": 1.00, "output": 5.00}
