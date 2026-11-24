# Backend Grulla

API local en Flask y SQLite. El frontend está exclusivamente en `/Users/joaquinsposetti/Desktop/grulla`; este backend no sirve ni copia sus archivos.

## Ejecutar en local

1. Abrí una terminal para el backend:

   ```sh
   cd /Users/joaquinsposetti/Desktop/grulla_back/grulla_back
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   python -m flask --app app run --host localhost --port 5000
   ```

2. En otra terminal, iniciá el frontend:

   ```sh
   cd /Users/joaquinsposetti/Desktop/grulla
   python3 -m http.server 8000 --bind localhost
   ```

3. Abrí http://localhost:8000 y elegí **Acceso profesionales**, o ingresá directamente a http://localhost:8000/panel/.
4. Las dos cuentas iniciales están en `instance/credenciales-locales.txt`, creado en esta instalación y excluido de Git. Usá el correo y contraseña correspondientes. No hay registro público.
5. Agregá un paciente y después agendá su sesión desde **Calendario y sesiones**. Podés editar datos generales y observaciones independientes para cada sesión.
6. **Activar avisos del navegador** solicita permiso para notificaciones. El panel también muestra las sesiones programadas para la próxima hora.

Usá `localhost` en ambos servidores: mezclarlo con `127.0.0.1` rompe la configuración de origen y cookies. Si el puerto 5000 está ocupado (por ejemplo, AirPlay en macOS), ejecutá el backend en 5001 y actualizá `GRULLA_API_URL` en `grulla/panel/config.js`.

## Cuentas y datos

Las cuentas son Liliana Ugolini y Sofía Sposetti. Las contraseñas se guardan como hashes PBKDF2. La asignación al profesional se toma de la sesión autenticada y cada consulta y modificación verifica la propiedad. Eliminar un paciente elimina también sus sesiones, previa confirmación en el panel.

En una instalación nueva, sin cuentas existentes, crealas con:

```sh
python -m flask --app app create-users
```

El comando pide correo y contraseña para cada profesional y omite cuentas existentes. No hay endpoint de creación de usuarios.

`instance/grulla.sqlite` guarda los datos, `instance/secret.key` firma las cookies. Ambos se generan localmente y se excluyen de Git. Para respaldar, detené el backend y copiá la base de datos a un lugar privado.

La zona horaria por defecto es `America/Argentina/Cordoba`, visible en el panel. Se puede cambiar al iniciar el servidor:

```sh
GRULLA_TIMEZONE=Europe/Zurich python -m flask --app app run --host localhost --port 5000
```

Si cambiás el origen del frontend, configurá `FRONTEND_ORIGIN`, y si cambiás la dirección de la API editá `panel/config.js`.

## Recordatorios

Se consultan al entrar y cada 15 segundos. Muestran sesiones programadas entre ahora y la próxima hora. Las notificaciones del navegador evitan repetir el mismo turno durante la visita e incluyen el nombre del paciente y el recordatorio opcional del último encuentro finalizado. **Requieren el panel abierto y permiso del navegador**; no se envían emails, WhatsApp ni avisos con la aplicación cerrada.

## Verificación

```sh
python -m unittest discover -s tests -v
```

Las pruebas cubren autenticación, CSRF, origen, límite de intentos, ABM, recordatorios y aislamiento entre profesionales. Este servidor está configurado para uso local; publicar requiere un servidor de producción, HTTPS y definir la operación de respaldos.

## Validación de sesiones

Las sesiones nuevas y los cambios de fecha deben ser posteriores al momento actual. Se permite conservar la fecha de una sesión pasada al editar sus observaciones o estado. El panel ofrece fecha y hora separadas, accesos a hoy y mañana, duraciones de 30, 45, 60, 90 y 120 minutos y una duración personalizada entre 5 y 480 minutos. El resumen muestra la hora de finalización.

## Cierre de sesiones y recordatorios

En una sesión programada, pulsá **Finalizar sesión**. Podés dejar un **Recordatorio para el próximo encuentro** y guardar los cambios. También aparece al editar y elegir el estado Realizada. Una hora antes del siguiente turno programado de ese paciente, el panel muestra su nombre y el recordatorio de la última sesión realizada. Si esa última sesión no tiene recordatorio, el aviso sale solo con el nombre y horario. Se verifica cada 15 segundos mientras el panel está abierto; los avisos del navegador requieren activar el permiso. No se envían avisos con la aplicación cerrada.

Al pulsar **Finalizar sesión**, el estado Terminada se guarda inmediatamente. El formulario de cierre permite agregar anotaciones independientes de los temas planificados y propuestas para el próximo encuentro. Cerrar ese formulario sin guardar mantiene la sesión terminada. **Ver cierre** permite completar o revisar las anotaciones después.

Los avisos muestran el intervalo exacto de la próxima hora según el servidor y la zona horaria del panel. Incluyen únicamente sesiones programadas que todavía no comenzaron, hasta 60 minutos inclusive. Se actualizan al recuperar foco, conexión y cada 15 segundos; también pueden actualizarse con **Actualizar avisos**.

## Historia clínica

En **Pacientes → Historia clínica** se consultan las sesiones del paciente, sus estados, temas preparados, anotaciones de cierre y temas para el próximo encuentro. El resumen del proceso lo escribe y guarda la profesional asignada, de forma independiente de los datos generales. La API verifica la propiedad tanto al consultar como al guardar el resumen. Los turnos futuros y cancelados también aparecen identificados en el historial.

## Sesiones pendientes de finalizar

Al pasar la hora de inicio **más la duración** de una sesión que sigue programada, aparece una alerta persistente con el paciente y un botón **Finalizar sesión**. No se puede ocultar manualmente: se retira al finalizar o cancelar la sesión. Se consulta cada 15 segundos y al regresar al panel, sin depender de los filtros del calendario. Si los avisos del navegador están activados, también aparece una notificación; requiere el panel abierto. Las sesiones todavía en curso no se marcan como pendientes.

## IA opcional y publicación

El botón **Pedir sugerencia** prepara ideas para conversar a partir del historial. Utiliza Qwen3-4B mediante un servicio local: no necesita claves y no envía anotaciones a proveedores externos. Requiere tener iniciado `scripts/run_local_ai.py`. Las ideas se revisan antes de agregarlas a los temas.

Ver [AI_Y_DESPLIEGUE.md](AI_Y_DESPLIEGUE.md) para usar y reiniciar la IA local. La publicación queda pendiente de solicitud.
