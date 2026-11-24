# Prueba de IA local — texto continuo

Modelo: Qwen3-4B Q4_K_M servido por llama.cpp en CPU.

Tres pruebas reales con datos sintéticos, sin APIs externas ni pacientes reales:

- Rutinas y apoyos: 34.73 segundos; respuesta en texto continuo de 112 palabras.
- Aprendizajes y vínculos: 22.67 segundos; respuesta en texto continuo de 123 palabras.
- Contexto más extenso: 35.16 segundos; respuesta en texto continuo de 109 palabras.

La respuesta orienta la conversación del próximo encuentro con tono cuidadoso y mirada pedagógica. Son borradores para revisión profesional; no decisiones clínicas.

Reproducir con `.venv/bin/python scripts/check_local_ai.py`, teniendo el modelo iniciado.

La comprobación completa desde navegador móvil, con Flask y el modelo real, devolvió un párrafo de 102 palabras en 25,036 segundos y permitió agregarlo a los temas sin tarjetas ni sobrescribir el borrador.
