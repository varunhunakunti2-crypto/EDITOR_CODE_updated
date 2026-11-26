"""Central configuration. Values come from environment variables or a .env file."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path):
    """Tiny .env reader (no extra dependency). Real environment variables win."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(os.path.join(BASE_DIR, ".env"))

SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-.env")

# --- Gemini (nearby-shop suggestions) ---------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Preferred model first; the others are tried automatically if it is unavailable.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_FALLBACK_MODELS = ["gemini-3.5-flash", "gemini-flash-latest"]
# Per-model request timeout in seconds. Gemini 3.x can be slow to cold-start.
GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "90"))

# --- Local Stable Diffusion inpainting model --------------------------------
SD_MODEL_ID = os.environ.get("SD_MODEL_ID", "runwayml/stable-diffusion-inpainting")
# "auto" picks CUDA when available, otherwise CPU. Valid overrides: "cuda", "cpu".
SD_DEVICE = os.environ.get("SD_DEVICE", "auto")
SD_STEPS = int(os.environ.get("SD_STEPS", "12"))

# --- Optional lightweight depth assistant -----------------------------------
# Depth Anything V2 Small is Apache 2.0 and ~99 MB, so it also fits a 4 GB GPU.
DEPTH_ENABLED = os.environ.get("DEPTH_ENABLED", "1").strip().lower() not in (
    "0", "false", "no", "off")
DEPTH_MODEL_ID = os.environ.get(
    "DEPTH_MODEL_ID", "depth-anything/Depth-Anything-V2-Small-hf")
DEPTH_DEVICE = os.environ.get("DEPTH_DEVICE", "auto")
DEPTH_MAX_SIZE = int(os.environ.get("DEPTH_MAX_SIZE", "512"))

