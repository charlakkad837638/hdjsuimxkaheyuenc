from pathlib import Path

from fastapi.templating import Jinja2Templates


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = PROJECT_ROOT / "web"
TEMPLATES = Jinja2Templates(directory=WEB_ROOT / "templates")
