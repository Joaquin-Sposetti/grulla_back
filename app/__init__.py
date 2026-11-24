import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, request, session
from .suggestions import prepare_context, generate_suggestions, SuggestionError

from werkzeug.security import check_password_hash, generate_password_hash


def create_app(test_config=None):
    instance = os.getenv('GRULLA_DATA_DIR')
    app = Flask(__name__, instance_relative_config=True, **({'instance_path': str(Path(instance).resolve())} if instance else {}))
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    secret = os.getenv('GRULLA_SECRET_KEY')
    if not secret:
        key_file = Path(app.instance_path) / 'secret.key'
        if not key_file.exists():
            key_file.write_text(secrets.token_hex(32))
            key_file.chmod(0o600)
        secret = key_file.read_text().strip()
    app.config.update(SECRET_KEY=secret, DATABASE=str(Path(app.instance_path) / 'grulla.sqlite'),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.getenv('GRULLA_SECURE_COOKIES', '0') == '1',
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
                      FRONTEND_ORIGIN=os.getenv('FRONTEND_ORIGIN', 'http://localhost:8000').rstrip('/'),
                      FRONTEND_ORIGINS=os.getenv('FRONTEND_ORIGINS', ''),
                      AI_PROVIDER=os.getenv('GRULLA_AI_PROVIDER', 'local'),
                      OPENROUTER_API_KEY=os.getenv('OPENROUTER_API_KEY', ''),
                      LOCAL_AI_URL=os.getenv('GRULLA_LOCAL_AI_URL', 'http://127.0.0.1:8081'),
                      AI_MODEL=os.getenv('GRULLA_AI_MODEL', 'grulla-local' if os.getenv('GRULLA_AI_PROVIDER', 'local') == 'local' else 'openrouter/free'),
                      TIMEZONE=os.getenv('GRULLA_TIMEZONE', 'America/Argentina/Cordoba'), MAX_CONTENT_LENGTH=100_000)
    if test_config:
        app.config.update(test_config)
    allowed_origins = {
        origin.strip().rstrip('/')
        for origin in (app.config['FRONTEND_ORIGINS'] or app.config['FRONTEND_ORIGIN']).split(',')
        if origin.strip()
    }

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'])
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    @app.teardown_appcontext
    def close_db(error):
        conn = g.pop('db', None)
        if conn:
            conn.close()

    with app.app_context():
        db().executescript('''
        CREATE TABLE IF NOT EXISTS professionals(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS patients(id INTEGER PRIMARY KEY, professional_id INTEGER NOT NULL REFERENCES professionals(id), name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', birth_date TEXT NOT NULL DEFAULT '', general_notes TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS appointments(id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE, professional_id INTEGER NOT NULL REFERENCES professionals(id), starts_at TEXT NOT NULL, duration INTEGER NOT NULL DEFAULT 60, notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'scheduled');
        CREATE INDEX IF NOT EXISTS appointments_owner_date ON appointments(professional_id, starts_at);
        CREATE TABLE IF NOT EXISTS ai_usage(professional_id INTEGER PRIMARY KEY REFERENCES professionals(id), last_requested REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY, count INTEGER NOT NULL, reset_at REAL NOT NULL);
        ''')
        account_columns = {row['name'] for row in db().execute('PRAGMA table_info(professionals)')}
        for column, definition in (
            ('role', "TEXT NOT NULL DEFAULT 'professional'"),
            ('active', 'INTEGER NOT NULL DEFAULT 1'),
            ('session_version', 'INTEGER NOT NULL DEFAULT 0'),
        ):
            if column not in account_columns:
                db().execute(f'ALTER TABLE professionals ADD COLUMN {column} {definition}')
        db().execute("CREATE UNIQUE INDEX IF NOT EXISTS single_admin ON professionals(role) WHERE role='admin'")
        appointment_columns = {row['name'] for row in db().execute('PRAGMA table_info(appointments)')}
        if 'follow_up_reminder' not in appointment_columns:
            db().execute("ALTER TABLE appointments ADD COLUMN follow_up_reminder TEXT NOT NULL DEFAULT ''")
        if 'completion_notes' not in appointment_columns:
            db().execute("ALTER TABLE appointments ADD COLUMN completion_notes TEXT NOT NULL DEFAULT ''")
        columns = {row['name'] for row in db().execute('PRAGMA table_info(patients)')}
        if 'clinical_summary' not in columns:
            db().execute("ALTER TABLE patients ADD COLUMN clinical_summary TEXT NOT NULL DEFAULT ''")
        if 'first_name' not in columns:
            db().execute("ALTER TABLE patients ADD COLUMN first_name TEXT NOT NULL DEFAULT ''")
            db().execute("ALTER TABLE patients ADD COLUMN last_name TEXT NOT NULL DEFAULT ''")
            # Keep the original full name intact; split existing values only once.
            for row in db().execute('SELECT id,name FROM patients').fetchall():
                parts = row['name'].split(' ', 1)
                db().execute('UPDATE patients SET first_name=?,last_name=? WHERE id=?', (parts[0], parts[1] if len(parts)>1 else '', row['id']))
        db().commit()

    @app.before_request
    def protect_origin():
        if request.method == 'OPTIONS':
            return '', 204
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            origin = request.headers.get('Origin')
            if origin and origin not in allowed_origins:
                return jsonify(error='Origen no permitido.'), 403
            if request.path != '/api/login' and session.get('user_id'):
                if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), session.get('csrf', '')):
                    return jsonify(error='Sesión inválida. Volvé a iniciar sesión.'), 403

    @app.after_request
    def headers(response):
        origin = request.headers.get('Origin')
        response.vary.add('Origin')
        if origin in allowed_origins:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-CSRF-Token'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Expose-Headers'] = 'X-Reminder-Window-Start, X-Reminder-Window-End'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def authenticated(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('user_id'):
                return jsonify(error='Iniciá sesión para continuar.'), 401
            account = db().execute('SELECT * FROM professionals WHERE id=?', (session['user_id'],)).fetchone()
            if not account or not account['active'] or session.get('version', 0) != account['session_version']:
                session.clear()
                return jsonify(error='Tu sesión terminó. Volvé a iniciar sesión.'), 401
            g.account = account
            return fn(*args, **kwargs)
        return wrapped

    def administrator(fn):
        @authenticated
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if g.account['role'] != 'admin':
                return jsonify(error='Se requiere una cuenta administradora.'), 403
            return fn(*args, **kwargs)
        return wrapped

    def text_field(data, name, maximum=10000):
        value = data.get(name, '')
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError('Datos inválidos o demasiado extensos.')
        return value.strip()

    def json_data():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError('Se esperaba un objeto con los datos del formulario.')
        return data

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(404)
    def missing(error):
        return jsonify(error='Registro no encontrado.'), 404

    @app.get('/api/health')
    def health():
        return jsonify(status='ok')

    @app.post('/api/login')
    def login():
        data = json_data()
        email = text_field(data, 'email', 200).lower()
        key = (request.remote_addr or '') + ':' + email
        now = datetime.now(timezone.utc).timestamp()
        attempt = db().execute('SELECT * FROM login_attempts WHERE key=?', (key,)).fetchone()
        if attempt and attempt['reset_at'] > now and attempt['count'] >= 10:
            return jsonify(error='Demasiados intentos. Esperá 15 minutos.'), 429
        user = db().execute('SELECT * FROM professionals WHERE email=?', (email,)).fetchone()
        password = data.get('password', '')
        if not isinstance(password, str) or len(password) > 500:
            raise ValueError('Contraseña inválida.')
        if not user or not user['active'] or not check_password_hash(user['password'], password):
            count = attempt['count'] + 1 if attempt and attempt['reset_at'] > now else 1
            db().execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)', (key, count, now + 900))
            db().commit()
            return jsonify(error='Correo o contraseña incorrectos.'), 401
        db().execute('DELETE FROM login_attempts WHERE key=?', (key,))
        db().commit()
        session.clear()
        session.permanent = True
        session.update(user_id=user['id'], version=user['session_version'], csrf=secrets.token_hex(32))
        return jsonify(user=dict(id=user['id'], name=user['name'], email=user['email'], role=user['role']), csrf=session['csrf'], timezone=app.config['TIMEZONE'])

    @app.get('/api/me')
    @authenticated
    def me():
        user = db().execute('SELECT id,name,email,role FROM professionals WHERE id=?', (session['user_id'],)).fetchone()
        return jsonify(user=dict(user), csrf=session['csrf'], timezone=app.config['TIMEZONE'])

    @app.post('/api/logout')
    @authenticated
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.route('/api/patients', methods=['GET', 'POST'])
    @authenticated
    def patients():
        if request.method == 'GET':
            return jsonify([dict(r) for r in db().execute('SELECT * FROM patients WHERE professional_id=? ORDER BY name', (session['user_id'],))])
        values = patient_values(json_data())
        cursor = db().execute('INSERT INTO patients(professional_id,name,phone,email,birth_date,general_notes,first_name,last_name) VALUES(?,?,?,?,?,?,?,?)', (session['user_id'], *values))
        db().commit()
        return jsonify(id=cursor.lastrowid), 201

    def patient_values(data):
        values = [text_field(data, k, 10000 if k == 'general_notes' else 200) for k in ('name', 'phone', 'email', 'birth_date', 'general_notes')]
        if 'first_name' in data or 'last_name' in data:
            first = text_field(data, 'first_name', 100)
            last = text_field(data, 'last_name', 100)
            if not first or not last:
                raise ValueError('El nombre y el apellido son obligatorios.')
            values[0] = f'{first} {last}'
        else:
            parts = values[0].split(' ', 1)
            first, last = parts[0], parts[1] if len(parts)>1 else ''
        if not values[0]:
            raise ValueError('El nombre es obligatorio.')
        if values[3]:
            try:
                birth = datetime.strptime(values[3], '%Y-%m-%d').date()
            except ValueError:
                raise ValueError('La fecha de nacimiento no es válida.')
            if birth > datetime.now(ZoneInfo(app.config['TIMEZONE'])).date():
                raise ValueError('La fecha de nacimiento no puede ser futura.')
        return [*values, first, last]

    @app.route('/api/patients/<int:pid>', methods=['PUT', 'DELETE'])
    @authenticated
    def patient(pid):
        if not db().execute('SELECT id FROM patients WHERE id=? AND professional_id=?', (pid, session['user_id'])).fetchone():
            return missing(None)
        if request.method == 'DELETE':
            db().execute('DELETE FROM patients WHERE id=?', (pid,))
        else:
            db().execute('UPDATE patients SET name=?,phone=?,email=?,birth_date=?,general_notes=?,first_name=?,last_name=? WHERE id=?', (*patient_values(json_data()), pid))
        db().commit()
        return jsonify(ok=True)

    @app.route('/api/patients/<int:pid>/history', methods=['GET', 'PUT'])
    @authenticated
    def patient_history(pid):
        patient = db().execute('SELECT p.*,u.name AS professional_name FROM patients p JOIN professionals u ON u.id=p.professional_id WHERE p.id=? AND p.professional_id=?', (pid, session['user_id'])).fetchone()
        if not patient:
            return missing(None)
        if request.method == 'PUT':
            summary = text_field(json_data(), 'clinical_summary', 5000)
            db().execute('UPDATE patients SET clinical_summary=? WHERE id=? AND professional_id=?', (summary, pid, session['user_id']))
            db().commit()
            return jsonify(ok=True, clinical_summary=summary)
        appointments = db().execute('SELECT * FROM appointments WHERE patient_id=? AND professional_id=? ORDER BY julianday(starts_at) DESC,id DESC', (pid, session['user_id']))
        return jsonify(patient=dict(patient), sessions=[dict(row) for row in appointments])

    @app.post('/api/patients/<int:pid>/suggestion-context')
    @authenticated
    def suggestion_context(pid):
        patient = db().execute('SELECT * FROM patients WHERE id=? AND professional_id=?', (pid, session['user_id'])).fetchone()
        if not patient:
            return missing(None)
        data = json_data()
        rows = db().execute("SELECT * FROM appointments WHERE patient_id=? AND professional_id=? AND status!='cancelled' AND (status='completed' OR julianday(starts_at)<=julianday(?)) ORDER BY julianday(starts_at) DESC,id DESC", (pid, session['user_id'], datetime.now(timezone.utc).isoformat())).fetchall()
        context = prepare_context(patient, rows, text_field(data, 'session_topics'))
        if not context['context']:
            return jsonify(error='Agregá anotaciones, un resumen o temas para conversar antes de pedir una sugerencia.'), 400
        local = app.config['AI_PROVIDER'] == 'local'
        return jsonify(**context, enabled=local or bool(app.config['OPENROUTER_API_KEY']), provider='IA local · Qwen' if local else 'OpenRouter', external=not local)

    @app.post('/api/patients/<int:pid>/suggestions')
    @authenticated
    def suggestions(pid):
        if not db().execute('SELECT id FROM patients WHERE id=? AND professional_id=?', (pid, session['user_id'])).fetchone():
            return missing(None)
        data = json_data()
        local = app.config['AI_PROVIDER'] == 'local'
        if data.get('reviewed') is not True or (not local and data.get('external_consent') is not True):
            return jsonify(error='Revisá el texto y confirmá cómo se procesará antes de generar sugerencias.'), 400
        context = text_field(data, 'context', 12000)
        if not context:
            raise ValueError('El texto para revisar está vacío.')
        if not local and not app.config['OPENROUTER_API_KEY']:
            return jsonify(error='Las sugerencias de IA todavía no están habilitadas.'), 503
        now = datetime.now(timezone.utc).timestamp()
        cooldown = 5 if local else 60
        cursor = db().execute('INSERT INTO ai_usage(professional_id,last_requested) VALUES(?,?) ON CONFLICT(professional_id) DO UPDATE SET last_requested=excluded.last_requested WHERE ai_usage.last_requested<=?', (session['user_id'], now, now-cooldown))
        db().commit()
        if cursor.rowcount == 0:
            return jsonify(error='Esperá unos segundos entre solicitudes.' if local else 'Esperá un minuto entre solicitudes de sugerencias.'), 429
        try:
            result = generate_suggestions(context, app.config['OPENROUTER_API_KEY'], app.config['AI_MODEL'], provider=app.config['AI_PROVIDER'], local_url=app.config['LOCAL_AI_URL'])
        except SuggestionError as error:
            return jsonify(error=str(error)), error.status
        return jsonify(suggestion=result, provider='IA local · Qwen' if local else 'OpenRouter', model=app.config['AI_MODEL'])

    @app.route('/api/sessions', methods=['GET', 'POST'])
    @authenticated
    def appointments():
        if request.method == 'GET':
            return jsonify([dict(r) for r in db().execute('SELECT a.*,p.name AS patient_name FROM appointments a JOIN patients p ON p.id=a.patient_id WHERE a.professional_id=? ORDER BY starts_at', (session['user_id'],))])
        values = appointment_values(json_data())
        cursor = db().execute('INSERT INTO appointments(patient_id,starts_at,duration,notes,status,follow_up_reminder,professional_id) VALUES(?,?,?,?,?,?,?)', (*values, session['user_id']))
        db().commit()
        return jsonify(id=cursor.lastrowid), 201

    def appointment_values(data, existing_start=None):
        try:
            pid = int(data.get('patient_id', 0))
            duration = int(data.get('duration', 60))
        except (ValueError, TypeError):
            raise ValueError('Paciente o duración inválidos.')
        if not db().execute('SELECT id FROM patients WHERE id=? AND professional_id=?', (pid, session['user_id'])).fetchone():
            raise ValueError('Seleccioná un paciente propio.')
        if not 5 <= duration <= 480:
            raise ValueError('La duración debe ser de 5 a 480 minutos.')
        raw_start = text_field(data, 'starts_at', 50)
        try:
            if 'T' not in raw_start:
                raise ValueError()
            start = datetime.fromisoformat(raw_start)
        except ValueError:
            raise ValueError('Seleccioná una fecha y hora válidas para la sesión.')
        if start.tzinfo is None:
            start = start.replace(tzinfo=ZoneInfo(app.config['TIMEZONE']))
        start = start.astimezone(timezone.utc)
        unchanged = existing_start and start == datetime.fromisoformat(existing_start)
        if start <= datetime.now(timezone.utc) and not unchanged:
            raise ValueError('La sesión debe comenzar después de la fecha y hora actuales.')
        start = start.isoformat()
        status = text_field(data, 'status', 30) or 'scheduled'
        if status not in ('scheduled', 'completed', 'cancelled'):
            raise ValueError('Estado inválido.')
        return pid, start, duration, text_field(data, 'notes'), status, text_field(data, 'follow_up_reminder', 2000)

    @app.route('/api/sessions/<int:sid>', methods=['PUT', 'DELETE'])
    @authenticated
    def appointment(sid):
        existing = db().execute('SELECT * FROM appointments WHERE id=? AND professional_id=?', (sid, session['user_id'])).fetchone()
        if not existing:
            return missing(None)
        if request.method == 'DELETE':
            db().execute('DELETE FROM appointments WHERE id=?', (sid,))
        else:
            data = json_data()
            data.setdefault('follow_up_reminder', existing['follow_up_reminder'])
            db().execute('UPDATE appointments SET patient_id=?,starts_at=?,duration=?,notes=?,status=?,follow_up_reminder=? WHERE id=?', (*appointment_values(data, existing['starts_at']), sid))
        db().commit()
        return jsonify(ok=True)

    @app.post('/api/sessions/<int:sid>/complete')
    @authenticated
    def complete_appointment(sid):
        existing = db().execute('SELECT * FROM appointments WHERE id=? AND professional_id=?', (sid, session['user_id'])).fetchone()
        if not existing:
            return missing(None)
        if existing['status'] == 'cancelled':
            return jsonify(error='No se puede finalizar una sesión cancelada.'), 409
        data = json_data()
        annotations = text_field(data, 'completion_notes') if 'completion_notes' in data else existing['completion_notes']
        reminder = text_field(data, 'follow_up_reminder', 2000) if 'follow_up_reminder' in data else existing['follow_up_reminder']
        db().execute("UPDATE appointments SET status='completed',completion_notes=?,follow_up_reminder=? WHERE id=? AND professional_id=?", (annotations, reminder, sid, session['user_id']))
        db().commit()
        return jsonify(ok=True, status='completed')

    @app.get('/api/reminders')
    @authenticated
    def reminders():
        now = datetime.now(timezone.utc)
        rows = db().execute("""
            SELECT a.id,a.starts_at,p.name AS patient_name,
                COALESCE((SELECT previous.follow_up_reminder FROM appointments previous
                    WHERE previous.patient_id=a.patient_id AND previous.professional_id=a.professional_id
                    AND previous.status='completed' AND julianday(previous.starts_at)<julianday(a.starts_at)
                    ORDER BY julianday(previous.starts_at) DESC,previous.id DESC LIMIT 1), '') AS reminder
            FROM appointments a JOIN patients p ON p.id=a.patient_id
            WHERE a.professional_id=? AND a.status='scheduled' AND julianday(a.starts_at)>julianday(?) AND julianday(a.starts_at)<=julianday(?)
            ORDER BY julianday(a.starts_at)
        """, (session['user_id'], now.isoformat(), (now + timedelta(hours=1)).isoformat()))
        response = jsonify([dict(r) for r in rows])
        response.headers['X-Reminder-Window-Start'] = now.isoformat()
        response.headers['X-Reminder-Window-End'] = (now + timedelta(hours=1)).isoformat()
        return response

    @app.get('/api/overdue-sessions')
    @authenticated
    def overdue_sessions():
        now = datetime.now(timezone.utc)
        rows = db().execute("""
            SELECT a.*,p.name AS patient_name FROM appointments a JOIN patients p ON p.id=a.patient_id
            WHERE a.professional_id=? AND a.status='scheduled'
              AND julianday(a.starts_at)+a.duration/1440.0<=julianday(?)
            ORDER BY julianday(a.starts_at)
        """, (session['user_id'], now.isoformat()))
        result = []
        for row in rows:
            item = dict(row)
            item['ends_at'] = (datetime.fromisoformat(item['starts_at']) + timedelta(minutes=item['duration'])).isoformat()
            result.append(item)
        return jsonify(result)

    @app.cli.command('create-users')
    def create_users():
        """Create the two professional accounts, prompting for passwords."""
        import click
        if db().execute("SELECT id FROM professionals WHERE role='admin'").fetchone():
            click.echo('Creá las cuentas profesionales desde el panel del administrador.')
            return
        for uid, name, default_email in ((1, 'Liliana Ugolini', 'liliana@grulla.local'), (2, 'Sofía Sposetti', 'sofia@grulla.local')):
            if db().execute('SELECT id FROM professionals WHERE id=?', (uid,)).fetchone():
                click.echo(name + ': la cuenta ya existe.')
                continue
            email = click.prompt('Correo de ' + name, default=default_email).strip().lower()
            password = click.prompt('Contraseña (mínimo 10 caracteres)', hide_input=True, confirmation_prompt=True)
            if len(password) < 10:
                raise click.ClickException('La contraseña debe tener al menos 10 caracteres.')
            db().execute('INSERT INTO professionals(id,email,name,password) VALUES(?,?,?,?)', (uid, email, name, generate_password_hash(password, method='pbkdf2:sha256')))
            db().commit()
            click.echo('Cuenta creada: ' + email)

    from .accounts import register_accounts
    register_accounts(app, db, administrator, json_data)
    return app
