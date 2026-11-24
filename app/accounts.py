"""Account administration; clinical records remain assigned to their owner."""
import sqlite3
import click
from flask import jsonify
from werkzeug.security import generate_password_hash


def identity(data):
    name, email = data.get('name'), data.get('email')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
        raise ValueError('Ingresá un nombre de hasta 200 caracteres.')
    if not isinstance(email, str) or len(email) > 200:
        raise ValueError('Ingresá un correo válido.')
    email = email.strip().lower()
    if email.count('@') != 1 or not all(email.split('@')) or any(c.isspace() for c in email):
        raise ValueError('Ingresá un correo válido.')
    return name.strip(), email


def password_hash(password):
    if not isinstance(password, str) or not 10 <= len(password) <= 500:
        raise ValueError('La contraseña debe tener entre 10 y 500 caracteres.')
    return generate_password_hash(password, method='pbkdf2:sha256')


def register_accounts(app, db, administrator, json_data):
    @app.get('/api/admin/professionals')
    @administrator
    def list_accounts():
        return jsonify([dict(row) for row in db().execute('''
            SELECT u.id,u.name,u.email,u.role,u.active,
            (SELECT COUNT(*) FROM patients p WHERE p.professional_id=u.id) AS patient_count
            FROM professionals u ORDER BY u.role,u.name
        ''')])

    @app.post('/api/admin/professionals')
    @administrator
    def create_account():
        data = json_data()
        if 'role' in data or 'active' in data:
            raise ValueError('Las cuentas nuevas se crean como profesionales activas.')
        name, email = identity(data)
        hashed = password_hash(data.get('password'))
        try:
            cursor = db().execute('INSERT INTO professionals(name,email,password) VALUES(?,?,?)', (name,email,hashed))
            db().commit()
        except sqlite3.IntegrityError:
            db().rollback()
            return jsonify(error='Ya existe una cuenta con ese correo.'), 409
        return jsonify(id=cursor.lastrowid), 201

    @app.put('/api/admin/professionals/<int:uid>')
    @administrator
    def edit_account(uid):
        account = db().execute('SELECT * FROM professionals WHERE id=?', (uid,)).fetchone()
        if not account:
            return jsonify(error='La cuenta no existe.'), 404
        if account['role'] == 'admin':
            return jsonify(error='Esta acción solo está disponible para profesionales.'), 403
        data = json_data()
        if set(data) - {'name', 'email', 'password', 'active'}:
            raise ValueError('Campos de cuenta no permitidos.')
        name, email = identity({**dict(account), **data})
        active = data.get('active', bool(account['active']))
        if not isinstance(active, bool):
            raise ValueError('El estado de la cuenta no es válido.')
        hashed = password_hash(data['password']) if 'password' in data else account['password']
        revoke = int('password' in data or active != bool(account['active']) or email != account['email'])
        try:
            db().execute('UPDATE professionals SET name=?,email=?,password=?,active=?,session_version=session_version+? WHERE id=?', (name,email,hashed,int(active),revoke,uid))
            db().commit()
        except sqlite3.IntegrityError:
            db().rollback()
            return jsonify(error='Ya existe una cuenta con ese correo.'), 409
        return jsonify(ok=True)

    @app.cli.command('create-admin')
    def create_admin():
        """Create the single administrator, or promote an existing account explicitly."""
        if db().execute("SELECT id FROM professionals WHERE role='admin'").fetchone():
            raise click.ClickException('Ya existe una cuenta administradora. No se modificó.')
        try:
            name, email = identity({'name': click.prompt('Nombre del administrador'), 'email': click.prompt('Correo del administrador')})
            existing = db().execute('SELECT id FROM professionals WHERE email=?', (email,)).fetchone()
            if existing and not click.confirm('Ese correo ya existe. ¿Convertir esa cuenta en administradora y cambiar su contraseña?'):
                raise click.ClickException('Operación cancelada.')
            hashed = password_hash(click.prompt('Contraseña (mínimo 10 caracteres)', hide_input=True, confirmation_prompt=True))
            if existing:
                db().execute("UPDATE professionals SET name=?,password=?,role='admin',active=1,session_version=session_version+1 WHERE id=?", (name,hashed,existing['id']))
            else:
                db().execute("INSERT INTO professionals(name,email,password,role) VALUES(?,?,?,'admin')", (name,email,hashed))
            db().commit()
        except ValueError as error:
            raise click.ClickException(str(error))
        except sqlite3.IntegrityError:
            db().rollback()
            raise click.ClickException('Ya existe una cuenta administradora o ese correo está en uso.')
        click.echo('Administrador creado: ' + email)
