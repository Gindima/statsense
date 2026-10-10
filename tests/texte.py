import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django; django.setup()
from ai.chaine import repondre
for q in sys.argv[1:]:
    r = repondre(q)
    print("-", q, "\n ", r.get("statut"), "|", r.get("texte") or r.get("message"))
