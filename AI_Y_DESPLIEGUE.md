# IA local de Grulla

La IA actual utiliza **Qwen3-4B Q4_K_M**, un modelo abierto con licencia Apache-2.0, mediante llama.cpp. Funciona en esta computadora sin claves, créditos ni servicios externos. No utiliza Groq. La publicación se preparará cuando se solicite; este documento describe únicamente el funcionamiento local.

## Usarla ahora

Abrí http://localhost:8000/panel/, iniciá sesión y, al agendar un encuentro, pulsá **Pedir sugerencia**. Revisá el contexto, marcá la casilla de revisión y pulsá **Generar sugerencias**. La respuesta se presenta como un único párrafo, con una mirada cuidadosa, psicológica y pedagógica. **Agregar texto a los temas** suma la propuesta al borrador sin reemplazar lo escrito. Se guarda al guardar la sesión.

El modelo puede proponer ideas poco precisas. En esta computadora, las pruebas de este formato tardaron aproximadamente entre 20 y 40 segundos. La profesional debe revisar y editar cada idea. No genera decisiones clínicas automáticas. El texto busca conectar avances, dificultades, recursos y temas pendientes, con preguntas abiertas integradas. No se muestran tarjetas ni citas separadas del historial. Se conserva el contexto revisado como referencia antes de generar.

## Reiniciar si se cierran los procesos

Dejá abiertas estas terminales:

**1. Modelo local**

```sh
cd /Users/joaquinsposetti/Desktop/grulla_back/grulla_back
.venv/bin/python scripts/run_local_ai.py
```

**2. Backend**

```sh
cd /Users/joaquinsposetti/Desktop/grulla_back/grulla_back
.venv/bin/python -m flask --app app run --host localhost --port 5000
```

**3. Frontend**

```sh
cd /Users/joaquinsposetti/Desktop/grulla
python3 -m http.server 8000 --bind localhost
```

Abrí http://localhost:8000/panel/. Usá `localhost` en el navegador, no `file://`. Si indica puerto ocupado, puede que el proceso ya esté iniciado.

El modelo escucha solo en `127.0.0.1:8081`. La aplicación conserva las anotaciones localmente: al generar sugerencias se comunican exclusivamente Flask y el servicio local del modelo. La descarga inicial de los archivos sí necesita Internet.

## Instalación inicial en otro Mac

Los pesos y el runtime no se incluyen en Git. En una instalación nueva:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/setup_local_ai.py
```

El instalador descarga el runtime oficial de llama.cpp y aproximadamente 2,5 GB de pesos desde el repositorio oficial de Qwen, verificando los SHA-256. Usa `instance/ai/`, excluido de Git. Soporta Mac Intel y Apple Silicon. Los datos, contraseñas locales, modelos y claves quedan fuera del repositorio mediante `.gitignore`.

## Comprobaciones

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_local_ai.py
```

La segunda comprobación utiliza el modelo real con tres casos sintéticos, sin leer pacientes reales ni consumir APIs externas. El informe de la ejecución realizada está en `instance/ai/live-check.json`, también excluido de Git.

## Publicación pendiente

El modo local no funcionará automáticamente en Railway: `127.0.0.1:8081` se refiere al mismo equipo que ejecuta el backend. Cuando se solicite publicar, se definirá la opción de inferencia adecuada y se entregará el paso a paso. La aplicación contiene un adaptador opcional para modelos gratuitos de OpenRouter; no está activado ni probado con una clave real. No cambia de proveedor automáticamente.

Referencias de los archivos descargados:

- https://huggingface.co/Qwen/Qwen3-4B-GGUF
- https://github.com/ggml-org/llama.cpp/releases/tag/b12020
