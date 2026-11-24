"""Real local inference check using synthetic data only; requires run_local_ai.py."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.suggestions import generate_suggestions

CASES = [
    ('Rutinas y apoyos', 'La persona está trabajando en organizar su rutina semanal. En el último encuentro pudo sostener dos actividades planificadas y le costó pedir ayuda cuando se sintió frustrada. Para retomar: qué ayudó a sostener la rutina y qué apoyos podría pedir.'),
    ('Aprendizajes y vínculos', 'En el último encuentro la persona contó que disfruta dibujar y que le cuesta participar en grupos nuevos. La profesional anotó para la próxima sesión: conocer en qué situaciones se siente más cómoda al compartir sus dibujos.'),
    ('Contexto más extenso', '\n'.join(f'Encuentro {i}: La persona está trabajando en anticipar actividades, expresar preferencias y pedir ayuda. Comentó avances al preparar materiales el día anterior. Para retomar: apoyos que le resultaron útiles.' for i in range(12)))
]
report = []
for label, context in CASES:
    started = time.monotonic()
    suggestion = generate_suggestions(context, '', 'grulla-local', provider='local')
    assert isinstance(suggestion,str) and 60 <= len(suggestion) <= 4000
    assert not any(line.lstrip().startswith(('- ', '* ', '1. ', '#')) for line in suggestion.splitlines())
    report.append({'case': label, 'seconds': round(time.monotonic()-started, 2), 'suggestion': suggestion})
print(json.dumps({'model': 'Qwen3-4B Q4_K_M', 'real_inference': True, 'synthetic_data_only': True, 'cases': report}, ensure_ascii=False, indent=2))
