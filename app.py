import os
import datetime
from io import BytesIO
from flask import Flask, render_template_string, request, redirect, url_for, flash, send_file
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor

# Librerías para generación de PDF
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

app = Flask(__name__)
app.secret_key = "clave_secreta_para_sesiones_seguras"

# Cadena de conexión actualizada a Supabase usando el pooler / puerto de conexión directa
SUPABASE_DB_URL = "postgresql://postgres.ocfpyiecmsgngurquphs:63Aa49Jemarta9$@aws-0-eu-west-2.pooler.supabase.com:6543/postgres"

def get_db_connection():
    conn = psycopg2.connect(SUPABASE_DB_URL)
    return conn

# Configuración de Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT id, username, password FROM usuarios WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return User(id=row['id'], username=row['username'], password_hash=row['password'])
    return None

# --- INICIALIZACIÓN DE TABLAS EN SUPABASE ---
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS productos (
            id SERIAL PRIMARY KEY,
            codigo TEXT UNIQUE NOT NULL,
            descripcion TEXT NOT NULL,
            precio REAL NOT NULL,
            iva REAL NOT NULL,
            stock_inicial INTEGER NOT NULL,
            compras INTEGER NOT NULL,
            stock_minimo INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            nombre TEXT UNIQUE NOT NULL,
            nif TEXT NOT NULL,
            tipo_cliente TEXT NOT NULL,
            categoria_negocio TEXT DEFAULT 'carnicería',
            recargo TEXT NOT NULL,
            direccion TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS facturas (
            id SERIAL PRIMARY KEY,
            num_factura TEXT UNIQUE NOT NULL,
            fecha TEXT NOT NULL,
            cliente TEXT NOT NULL,
            tipo_cliente TEXT NOT NULL,
            recargo TEXT NOT NULL,
            base_imponible REAL NOT NULL,
            iva_total REAL NOT NULL,
            recargo_total REAL NOT NULL,
            total_factura REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ventas_lineas (
            id SERIAL PRIMARY KEY,
            num_factura TEXT NOT NULL,
            producto TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            precio REAL NOT NULL,
            iva REAL DEFAULT 0.10
        );
        CREATE TABLE IF NOT EXISTS ventas (
            id SERIAL PRIMARY KEY,
            fecha TEXT NOT NULL,
            factura TEXT NOT NULL,
            cliente TEXT NOT NULL,
            tipo_cliente TEXT NOT NULL,
            producto TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            precio_venta REAL NOT NULL,
            subtotal REAL NOT NULL,
            iva_linea REAL DEFAULT 0.0,
            recargo_equivalencia REAL NOT NULL,
            total REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS gastos (
            id SERIAL PRIMARY KEY,
            fecha TEXT NOT NULL,
            concepto TEXT NOT NULL,
            categoria TEXT NOT NULL,
            importe REAL NOT NULL
        );
    """)

    # Migración de seguridad por si las tablas ya existían
    cursor.execute("""
        DO $$ 
        BEGIN 
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='clientes' and column_name='categoria_negocio') THEN
                ALTER TABLE clientes ADD COLUMN categoria_negocio TEXT DEFAULT 'carnicería';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='ventas' and column_name='iva_linea') THEN
                ALTER TABLE ventas ADD COLUMN iva_linea REAL DEFAULT 0.0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='ventas_lineas' and column_name='iva') THEN
                ALTER TABLE ventas_lineas ADD COLUMN iva REAL DEFAULT 0.10;
            END IF;
        END $$;
    """)

    # Crear usuario predeterminado si no existe (admin / admin123)
    cursor.execute("SELECT COUNT(*) FROM usuarios;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO usuarios (username, password) VALUES (%s, %s)", 
                       ("admin", generate_password_hash("admin123")))

    conn.commit()
    conn.close()

# --- DISEÑO BASE WEB ---
BASE_LAYOUT = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gestión de Distribución - Carnicerías</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
    {% if current_user.is_authenticated %}
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">🥩 Productos Almendros</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav me-auto">
                    <li class="nav-item"><a class="nav-link" href="/">Emitir Factura</a></li>
                    <li class="nav-item"><a class="nav-link" href="/stock">Almacén</a></li>
                    <li class="nav-item"><a class="nav-link" href="/clientes">Clientes</a></li>
                    <li class="nav-item"><a class="nav-link" href="/historico">Histórico Facturas</a></li>
                    <li class="nav-item"><a class="nav-link" href="/ventas">Ventas</a></li>
                    <li class="nav-item"><a class="nav-link" href="/gastos">Gastos</a></li>
                    <li class="nav-item"><a class="nav-link" href="/balance">Balance</a></li>
                </ul>
                <span class="navbar-text me-3">👤 {{ current_user.username }}</span>
                <a href="/logout" class="btn btn-outline-danger btn-sm">Cerrar Sesión</a>
            </div>
        </div>
    </nav>
    {% endif %}
    <div class="container my-4">
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                {{ message }}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}

        {% block content %}{% endblock %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# --- INICIO DE SESIÓN ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, username, password FROM usuarios WHERE username = %s", (username,))
        row = cursor.fetchone()
        conn.close()
        
        if row and check_password_hash(row['password'], password):
            user = User(id=row['id'], username=row['username'], password_hash=row['password'])
            login_user(user)
            return redirect(url_for("index"))
        else:
            flash("Usuario o contraseña incorrectos", "danger")

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <div class="row justify-content-center mt-5">
        <div class="col-md-4">
            <div class="card shadow-sm">
                <div class="card-body">
                    <h3 class="card-title text-center mb-4">🔑 Iniciar Sesión</h3>
                    <form method="POST">
                        <div class="mb-3">
                            <label class="form-label">Usuario</label>
                            <input type="text" name="username" class="form-control" required placeholder="admin">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Contraseña</label>
                            <input type="password" name="password" class="form-control" required placeholder="admin123">
                        </div>
                        <button type="submit" class="btn btn-primary w-100">Entrar</button>
                    </form>
                </div>
            </div>
        </div>
    </div>
    """)
    return render_template_string(html)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Has cerrado sesión correctamente", "info")
    return redirect(url_for("login"))

# --- EMITIR FACTURA ---
@app.route("/")
@login_required
def index():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT nombre, categoria_negocio FROM clientes ORDER BY nombre ASC")
    clientes = cursor.fetchall()
    
    cursor.execute("SELECT codigo, descripcion, precio, iva FROM productos ORDER BY descripcion ASC")
    productos = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) FROM facturas")
    num_factura = f"FAC-2026-{(cursor.fetchone()[0] + 1):03d}"
    conn.close()

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <div class="row">
        <div class="col-md-12">
            <div class="card p-3 mb-4 bg-white shadow-sm border-0">
                <h5 class="text-secondary mb-1">Emitido por:</h5>
                <h4 class="fw-bold">Productos Almendros</h4>
                <p class="mb-0 text-muted">NIF: 03808927N | Calle Los Ángeles, 37, 45860 Toledo</p>
            </div>
            <h2 class="mb-4">📄 Emitir Factura / Pedido</h2>
            <form action="/procesar_factura" method="POST" class="card p-4 shadow-sm">
                <div class="row mb-3">
                    <div class="col-md-6">
                        <label class="form-label">Cliente / Negocio</label>
                        <input type="text" id="buscador-cliente" class="form-control mb-2" placeholder="🔍 Filtrar cliente por nombre..." onkeyup="filtrarClientes()">
                        <select name="cliente" id="select-cliente" class="form-select" required>
                            <option value="">Seleccione un cliente...</option>
                            {% for c in clientes %}
                            <option value="{{ c[0] }}">{{ c[0] }} ({{ c[1]|capitalize }})</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label">Nº Factura</label>
                        <input type="text" name="num_factura" class="form-control" value="{{ num_factura }}" required>
                    </div>
                </div>
                <hr>
                <h5 class="mb-3">Añadir Líneas de Venta</h5>
                <div id="lineas-container">
                    <div class="row mb-2 linea-row align-items-center">
                        <div class="col-md-4">
                            <input type="text" class="form-control form-control-sm mb-1 buscador-prod" placeholder="🔍 Buscar producto por descripción..." onkeyup="filtrarProductos(this)">
                            <select name="producto[]" class="form-select prod-select" onchange="actualizarDatosProducto(this)" required>
                                <option value="">Seleccione producto...</option>
                                {% for p in productos %}
                                <option value="{{ p[1] }}" data-precio="{{ p[2] }}" data-iva="{{ p[3] }}">{{ p[1] }} ({{ p[2] }}€)</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label small text-muted mb-0">Cantidad</label>
                            <input type="number" name="cantidad[]" class="form-control" value="1" min="1" required>
                        </div>
                        <div class="col-md-2">
                            <label class="form-label small text-muted mb-0">Precio Unit. (€)</label>
                            <input type="number" step="0.01" name="precio_unit[]" class="form-control precio-input" required>
                        </div>
                        <div class="col-md-3">
                            <label class="form-label small text-muted mb-0">IVA (%)</label>
                            <select name="iva_linea[]" class="form-select iva-select" required>
                                <option value="0.10">10% (Reducido)</option>
                                <option value="0.21">21% (General)</option>
                                <option value="0.04">4% (Superreducido)</option>
                                <option value="0.00">0% (Exento)</option>
                            </select>
                        </div>
                        <div class="col-md-1 text-center">
                            <label class="form-label small text-muted mb-0">&nbsp;</label><br>
                            <button type="button" class="btn btn-outline-danger btn-sm" onclick="eliminarLinea(this)">🗑️</button>
                        </div>
                    </div>
                </div>
                <button type="button" class="btn btn-secondary btn-sm mt-2 w-25" onclick="addLinea()">➕ Añadir otra línea</button>
                <div class="mt-4">
                    <button type="submit" class="btn btn-success btn-lg w-100">💾 Formalizar Factura y Descontar Stock</button>
                </div>
            </form>
        </div>
    </div>
    <script>
    function filtrarClientes() {
        let filtro = document.getElementById('buscador-cliente').value.toLowerCase();
        let select = document.getElementById('select-cliente');
        let opciones = select.options;
        for (let i = 1; i < opciones.length; i++) {
            let texto = opciones[i].text.toLowerCase();
            opciones[i].style.display = texto.includes(filtro) ? '' : 'none';
        }
    }

    function filtrarProductos(input) {
        let filtro = input.value.toLowerCase();
        let row = input.closest('.linea-row');
        let select = row.querySelector('.prod-select');
        let opciones = select.options;
        for (let i = 1; i < opciones.length; i++) {
            let texto = opciones[i].text.toLowerCase();
            if (texto.includes(filtro)) {
                opciones[i].style.display = '';
            } else {
                opciones[i].style.display = 'none';
            }
        }
    }

    function actualizarDatosProducto(select) {
        let option = select.options[select.selectedIndex];
        let precio = option.getAttribute('data-precio');
        let iva = option.getAttribute('data-iva');
        let row = select.closest('.linea-row');
        
        if (precio) {
            row.querySelector('.precio-input').value = precio;
        }
        if (iva !== null) {
            let ivaSelect = row.querySelector('.iva-select');
            ivaSelect.value = parseFloat(iva).toFixed(2);
        }
    }

    function addLinea() {
        let container = document.getElementById('lineas-container');
        let primeraLinea = container.querySelector('.linea-row');
        let clone = primeraLinea.cloneNode(true);
        clone.querySelector('.buscador-prod').value = '';
        clone.querySelector('input[name="cantidad[]"]').value = '1';
        clone.querySelector('.precio-input').value = '';
        let select = clone.querySelector('.prod-select');
        select.selectedIndex = 0;
        for (let opt of select.options) { opt.style.display = ''; }
        container.appendChild(clone);
    }

    function eliminarLinea(btn) {
        let container = document.getElementById('lineas-container');
        if (container.querySelectorAll('.linea-row').length > 1) {
            btn.closest('.linea-row').remove();
        } else {
            alert('Debe mantenerse al menos una línea de venta.');
        }
    }
    </script>
    """)
    return render_template_string(html, clientes=clientes, productos=productos, num_factura=num_factura)

# --- ALMACÉN Y PRODUCTOS ---
@app.route("/stock")
@login_required
def stock():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, codigo, descripcion, precio, iva, stock_inicial, compras, stock_minimo FROM productos ORDER BY descripcion ASC")
    rows = cursor.fetchall()
    
    datos = []
    for r in rows:
        p_id, cod, desc, precio, iva, ini, comp, min_s = r
        cursor.execute("SELECT SUM(cantidad) FROM ventas_lineas WHERE producto = %s", (desc,))
        res_v = cursor.fetchone()
        v = res_v[0] if res_v and res_v[0] else 0
        actual = ini + comp - v
        estado = "Reponer" if actual <= min_s else "OK"
        datos.append((p_id, cod, desc, precio, iva, ini, comp, v, actual, estado))
    conn.close()

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2>📦 Control de Almacén y Productos</h2>
        <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#modalCrearProducto">➕ Nuevo Producto</button>
    </div>
    <div class="mb-3">
        <input type="text" id="buscador-stock" class="form-control" placeholder="🔍 Buscar producto en almacén por descripción..." onkeyup="filtrarStock()">
    </div>
    <div class="table-responsive">
    <table class="table table-striped table-bordered align-middle" id="tabla-stock">
        <thead class="table-dark">
            <tr><th>Código</th><th>Descripción</th><th>Precio</th><th>IVA</th><th>Stock Ini.</th><th>Compras</th><th>Ventas</th><th>Disponible</th><th>Estado</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for d in datos %}
            <tr>
                <form action="/actualizar_producto/{{ d[0] }}" method="POST">
                    <td>{{ d[1] }}</td>
                    <td class="desc-producto">{{ d[2] }}</td>
                    <td><input type="number" step="0.01" name="precio" value="{{ d[3] }}" class="form-control form-control-sm" style="width: 80px;" required></td>
                    <td>{{ "%.0f"|format(d[4]*100) }}%</td>
                    <td><input type="number" name="stock_inicial" value="{{ d[5] }}" class="form-control form-control-sm" style="width: 70px;" required></td>
                    <td><input type="number" name="compras" value="{{ d[6] }}" class="form-control form-control-sm" style="width: 70px;" required></td>
                    <td>{{ d[7] }}</td>
                    <td><strong>{{ d[8] }}</strong></td>
                    <td><span class="badge {{ 'bg-danger' if d[9]=='Reponer' else 'bg-success' }}">{{ d[9] }}</span></td>
                    <td>
                        <button type="submit" class="btn btn-success btn-sm" title="Guardar cambios">💾</button>
                        <a href="/eliminar_producto/{{ d[0] }}" class="btn btn-danger btn-sm" onclick="return confirm('¿Eliminar producto?')" title="Eliminar">🗑️</a>
                    </td>
                </form>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    </div>

    <script>
    function filtrarStock() {
        let filtro = document.getElementById('buscador-stock').value.toLowerCase();
        let filas = document.querySelectorAll('#tabla-stock tbody tr');
        filas.forEach(fila => {
            let desc = fila.querySelector('.desc-producto').textContent.toLowerCase();
            if (desc.includes(filtro)) {
                fila.style.display = '';
            } else {
                fila.style.display = 'none';
            }
        });
    }
    </script>

    <div class="modal fade" id="modalCrearProducto" tabindex="-1">
      <div class="modal-dialog">
        <form action="/guardar_producto" method="POST" class="modal-content">
          <div class="modal-header"><h5 class="modal-title">Añadir Producto</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
          <div class="modal-body">
            <div class="mb-2"><label>Código</label><input type="text" name="codigo" class="form-control" required></div>
            <div class="mb-2"><label>Descripción</label><input type="text" name="descripcion" class="form-control" required></div>
            <div class="mb-2"><label>Precio (€)</label><input type="number" step="0.01" name="precio" class="form-control" required></div>
            <div class="mb-2"><label>IVA (0.10 para 10%, 0.21 para 21%)</label><input type="number" step="0.01" name="iva" class="form-control" value="0.10" required></div>
            <div class="mb-2"><label>Stock Inicial</label><input type="number" name="stock_inicial" class="form-control" value="0" required></div>
            <div class="mb-2"><label>Compras</label><input type="number" name="compras" class="form-control" value="0" required></div>
            <div class="mb-2"><label>Stock Mínimo</label><input type="number" name="stock_minimo" class="form-control" value="10" required></div>
          </div>
          <div class="modal-footer"><button type="submit" class="btn btn-primary">Guardar</button></div>
        </form>
      </div>
    </div>
    """)
    return render_template_string(html, datos=datos)

@app.route("/guardar_producto", methods=["POST"])
@login_required
def guardar_producto():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO productos (codigo, descripcion, precio, iva, stock_inicial, compras, stock_minimo)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (request.form["codigo"], request.form["descripcion"], float(request.form["precio"]), float(request.form["iva"]),
              int(request.form["stock_inicial"]), int(request.form["compras"]), 10))
        conn.commit()
        flash("Producto guardado correctamente", "success")
    except Exception as e:
        flash(f"Error al guardar producto: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("stock"))

@app.route("/actualizar_producto/<int:id>", methods=["POST"])
@login_required
def actualizar_producto(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE productos SET precio = %s, stock_inicial = %s, compras = %s WHERE id = %s
        """, (float(request.form["precio"]), int(request.form["stock_inicial"]), int(request.form["compras"]), id))
        conn.commit()
        flash("Producto actualizado correctamente", "success")
    except Exception as e:
        flash(f"Error al actualizar producto: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("stock"))

@app.route("/eliminar_producto/<int:id>")
@login_required
def eliminar_producto(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM productos WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    flash("Producto eliminado", "warning")
    return redirect(url_for("stock"))

# --- CLIENTES ---
@app.route("/clientes")
@login_required
def clientes():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre, nif, tipo_cliente, categoria_negocio, recargo, direccion FROM clientes ORDER BY nombre ASC")
    rows = cursor.fetchall()
    conn.close()

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2>👥 Clientes y Negocios</h2>
        <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#modalCrearCliente">➕ Nuevo Cliente</button>
    </div>
    <div class="table-responsive">
    <table class="table table-striped table-bordered align-middle">
        <thead class="table-dark">
            <tr><th>Nombre</th><th>NIF</th><th>Tipo</th><th>Categoría Negocio</th><th>Recargo Equiv.</th><th>Dirección</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for r in rows %}
            <tr>
                <td>{{ r[1] }}</td>
                <td>{{ r[2] }}</td>
                <td>{{ r[3] }}</td>
                <td><span class="badge bg-secondary">{{ r[4]|capitalize }}</span></td>
                <td>{{ r[5] }}</td>
                <td>{{ r[6] }}</td>
                <td>
                    <button class="btn btn-warning btn-sm" data-bs-toggle="modal" data-bs-target="#modalEditarCliente{{ r[0] }}" title="Editar">✏️</button>
                    <a href="/eliminar_cliente/{{ r[0] }}" class="btn btn-danger btn-sm" onclick="return confirm('¿Eliminar cliente?')" title="Eliminar">🗑️</a>
                </td>
            </tr>

            <!-- Modal Editar Cliente -->
            <div class="modal fade" id="modalEditarCliente{{ r[0] }}" tabindex="-1">
              <div class="modal-dialog">
                <form action="/actualizar_cliente/{{ r[0] }}" method="POST" class="modal-content">
                  <div class="modal-header"><h5 class="modal-title">Editar Cliente: {{ r[1] }}</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                  <div class="modal-body">
                    <div class="mb-2"><label>Nombre</label><input type="text" name="nombre" value="{{ r[1] }}" class="form-control" required></div>
                    <div class="mb-2"><label>NIF / CIF</label><input type="text" name="nif" value="{{ r[2] }}" class="form-control" required></div>
                    <div class="mb-2"><label>Tipo de Cliente</label>
                        <select name="tipo_cliente" class="form-select">
                            <option {% if r[3]=='Estándar' %}selected{% endif %}>Estándar</option>
                            <option {% if r[3]=='VIP' %}selected{% endif %}>VIP</option>
                            <option {% if r[3]=='Mayorista' %}selected{% endif %}>Mayorista</option>
                        </select>
                    </div>
                    <div class="mb-2"><label>Categoría del Negocio</label>
                        <select name="categoria_negocio" class="form-select" required>
                            <option value="carnicería" {% if r[4]=='carnicería' %}selected{% endif %}>Carnicería</option>
                            <option value="restauración" {% if r[4]=='restauración' %}selected{% endif %}>Restauración</option>
                            <option value="catering" {% if r[4]=='catering' %}selected{% endif %}>Catering</option>
                            <option value="otro" {% if r[4]=='otro' %}selected{% endif %}>Otro</option>
                        </select>
                    </div>
                    <div class="mb-2"><label>Aplica Recargo Equivalencia</label>
                        <select name="recargo" class="form-select">
                            <option value="SÍ" {% if r[5]=='SÍ' %}selected{% endif %}>SÍ</option>
                            <option value="NO" {% if r[5]=='NO' %}selected{% endif %}>NO</option>
                        </select>
                    </div>
                    <div class="mb-2"><label>Dirección</label><input type="text" name="direccion" value="{{ r[6] }}" class="form-control" required></div>
                  </div>
                  <div class="modal-footer"><button type="submit" class="btn btn-primary">Actualizar</button></div>
                </form>
              </div>
            </div>
            {% endfor %}
        </tbody>
    </table>
    </div>

    <div class="modal fade" id="modalCrearCliente" tabindex="-1">
      <div class="modal-dialog">
        <form action="/guardar_cliente" method="POST" class="modal-content">
          <div class="modal-header"><h5 class="modal-title">Añadir Cliente</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
          <div class="modal-body">
            <div class="mb-2"><label>Nombre</label><input type="text" name="nombre" class="form-control" required></div>
            <div class="mb-2"><label>NIF / CIF</label><input type="text" name="nif" class="form-control" required></div>
            <div class="mb-2"><label>Tipo de Cliente</label>
                <select name="tipo_cliente" class="form-select">
                    <option>Estándar</option><option>VIP</option><option>Mayorista</option>
                </select>
            </div>
            <div class="mb-2"><label>Categoría del Negocio</label>
                <select name="categoria_negocio" class="form-select" required>
                    <option value="carnicería">Carnicería</option>
                    <option value="restauración">Restauración</option>
                    <option value="catering">Catering</option>
                    <option value="otro">Otro</option>
                </select>
            </div>
            <div class="mb-2"><label>Aplica Recargo Equivalencia</label>
                <select name="recargo" class="form-select">
                    <option value="SÍ">SÍ</option><option value="NO">NO</option>
                </select>
            </div>
            <div class="mb-2"><label>Dirección</label><input type="text" name="direccion" class="form-control" required></div>
          </div>
          <div class="modal-footer"><button type="submit" class="btn btn-primary">Guardar</button></div>
        </form>
      </div>
    </div>
    """)
    return render_template_string(html, rows=rows)

@app.route("/guardar_cliente", methods=["POST"])
@login_required
def guardar_cliente():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO clientes (nombre, nif, tipo_cliente, categoria_negocio, recargo, direccion)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (request.form["nombre"], request.form["nif"], request.form["tipo_cliente"], request.form["categoria_negocio"], request.form["recargo"], request.form["direccion"]))
        conn.commit()
        flash("Cliente registrado con éxito", "success")
    except Exception as e:
        flash(f"Error al registrar cliente: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("clientes"))

@app.route("/actualizar_cliente/<int:id>", methods=["POST"])
@login_required
def actualizar_cliente(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE clientes SET nombre = %s, nif = %s, tipo_cliente = %s, categoria_negocio = %s, recargo = %s, direccion = %s WHERE id = %s
        """, (request.form["nombre"], request.form["nif"], request.form["tipo_cliente"], request.form["categoria_negocio"], request.form["recargo"], request.form["direccion"], id))
        conn.commit()
        flash("Cliente actualizado correctamente", "success")
    except Exception as e:
        flash(f"Error al actualizar cliente: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("clientes"))

@app.route("/eliminar_cliente/<int:id>")
@login_required
def eliminar_cliente(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM clientes WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    flash("Cliente eliminado", "warning")
    return redirect(url_for("clientes"))

# --- HISTÓRICO Y FACTURAS EN PDF ---
@app.route("/historico")
@login_required
def historico():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, num_factura, fecha, cliente, tipo_cliente, recargo, base_imponible, iva_total, recargo_total, total_factura FROM facturas ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <h2>📊 Histórico de Facturas</h2>
    <div class="table-responsive">
    <table class="table table-striped table-bordered mt-3 align-middle">
        <thead class="table-dark">
            <tr><th>Nº Factura</th><th>Fecha</th><th>Cliente</th><th>Base Imp.</th><th>IVA</th><th>Recargo</th><th>Total</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for r in rows %}
            <tr>
                <td>{{ r[1] }}</td><td>{{ r[2] }}</td><td>{{ r[3] }}</td><td>{{ "%.2f"|format(r[6]) }}€</td><td>{{ "%.2f"|format(r[7]) }}€</td><td>{{ "%.2f"|format(r[8]) }}€</td><td><strong>{{ "%.2f"|format(r[9]) }}€</strong></td>
                <td>
                    <a href="/descargar_pdf/{{ r[1] }}" class="btn btn-danger btn-sm" title="Descargar PDF">📄 PDF</a>
                    <a href="/eliminar_factura/{{ r[1] }}" class="btn btn-outline-danger btn-sm" onclick="return confirm('¿Seguro que deseas eliminar esta factura y sus ventas asociadas?')" title="Eliminar factura y ventas">🗑️</a>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    </div>
    """)
    return render_template_string(html, rows=rows)

@app.route("/eliminar_factura/<num_factura>")
@login_required
def eliminar_factura(num_factura):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM facturas WHERE num_factura = %s", (num_factura,))
        cursor.execute("DELETE FROM ventas_lineas WHERE num_factura = %s", (num_factura,))
        cursor.execute("DELETE FROM ventas WHERE factura = %s", (num_factura,))
        conn.commit()
        flash(f"Factura {num_factura} y sus ventas asociadas eliminadas correctamente", "warning")
    except Exception as e:
        flash(f"Error al eliminar la factura: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for("historico"))

@app.route("/descargar_pdf/<num_factura>")
@login_required
def descargar_pdf(num_factura):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT num_factura, fecha, cliente, base_imponible, iva_total, recargo_total, total_factura FROM facturas WHERE num_factura = %s", (num_factura,))
    fac = cursor.fetchone()
    if not fac:
        conn.close()
        return "Factura no encontrada", 404

    cursor.execute("SELECT producto, cantidad, precio, iva FROM ventas_lineas WHERE num_factura = %s", (num_factura,))
    lineas = cursor.fetchall()
    
    cursor.execute("SELECT nif, direccion FROM clientes WHERE nombre = %s", (fac[2],))
    cli = cursor.fetchone()
    nif_cli = cli[0] if cli else ""
    dir_cli = cli[1] if cli else ""
    conn.close()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # Cabecera Emisor
    story.append(Paragraph("<b>PRODUCTOS ALMENDROS</b>", styles['Heading1']))
    story.append(Paragraph("NIF: 03808927N", styles['Normal']))
    story.append(Paragraph("Calle Los Ángeles, 37, 45860 Toledo", styles['Normal']))
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"<b>FACTURA: {fac[0]}</b>", styles['Title']))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"<b>Fecha:</b> {fac[1]}", styles['Normal']))
    story.append(Paragraph(f"<b>Cliente:</b> {fac[2]} (NIF: {nif_cli})", styles['Normal']))
    story.append(Paragraph(f"<b>Dirección:</b> {dir_cli}", styles['Normal']))
    story.append(Spacer(1, 15))

    table_data = [["Producto", "Cant.", "Precio Unit.", "IVA", "Subtotal"]]
    for l in lineas:
        sub = l[1] * l[2]
        iva_pct = f"{int(l[3]*100)}%" if l[3] is not None else "10%"
        table_data.append([l[0], str(l[1]), f"{l[2]:.2f} €", iva_pct, f"{sub:.2f} €"])

    t = Table(table_data, colWidths=[180, 50, 90, 80, 100])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold')
    ]))
    story.append(t)
    story.append(Spacer(1, 15))

    story.append(Paragraph(f"<b>Base Imponible:</b> {fac[3]:.2f} €", styles['Normal']))
    story.append(Paragraph(f"<b>IVA Total:</b> {fac[4]:.2f} €", styles['Normal']))
    story.append(Paragraph(f"<b>Recargo Equivalencia:</b> {fac[5]:.2f} €", styles['Normal']))
    story.append(Paragraph(f"<h3><b>TOTAL FACTURA: {fac[6]:.2f} €</b></h3>", styles['Normal']))

    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"{num_factura}.pdf", mimetype="application/pdf")

# --- VENTAS, GASTOS Y BALANCE ---
@app.route("/ventas")
@login_required
def ventas():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, fecha, factura, cliente, producto, cantidad, precio_venta, subtotal, iva_linea, total FROM ventas ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <h2>📋 Detalle de Ventas</h2>
    <div class="table-responsive">
    <table class="table table-striped table-bordered mt-3 align-middle">
        <thead class="table-dark">
            <tr><th>Fecha</th><th>Factura</th><th>Cliente</th><th>Producto</th><th>Cant.</th><th>Precio Unit.</th><th>Subtotal</th><th>IVA</th><th>Total</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for r in rows %}
            <tr>
                <td>{{ r[1] }}</td><td>{{ r[2] }}</td><td>{{ r[3] }}</td><td>{{ r[4] }}</td><td>{{ r[5] }}</td><td>{{ "%.2f"|format(r[6]) }}€</td><td>{{ "%.2f"|format(r[7]) }}€</td><td>{{ "%.2f"|format(r[8]) }}€</td><td><strong>{{ "%.2f"|format(r[9]) }}€</strong></td>
                <td>
                    <a href="/eliminar_venta/{{ r[0] }}" class="btn btn-danger btn-sm" onclick="return confirm('¿Eliminar este registro de venta?')" title="Eliminar">🗑️</a>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    </div>
    """)
    return render_template_string(html, rows=rows)

@app.route("/eliminar_venta/<int:id>")
@login_required
def eliminar_venta(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ventas WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    flash("Registro de venta eliminado", "warning")
    return redirect(url_for("ventas"))

@app.route("/gastos")
@login_required
def gastos():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, fecha, concepto, categoria, importe FROM gastos ORDER BY fecha DESC")
    rows = cursor.fetchall()
    conn.close()

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <h2>💸 Gastos de la Empresa</h2>
    <form action="/guardar_gasto" method="POST" class="card p-3 mb-4 shadow-sm">
        <div class="row g-2">
            <div class="col-md-3"><input type="date" name="fecha" class="form-control" required></div>
            <div class="col-md-3"><input type="text" name="concepto" class="form-control" placeholder="Concepto" required></div>
            <div class="col-md-3">
                <select name="categoria" class="form-select">
                    <option>Gasolina / Transporte</option><option>Alquileres</option><option>Mantenimiento</option><option>Producto / Mercancía</option><option>Otros</option>
                </select>
            </div>
            <div class="col-md-2"><input type="number" step="0.01" name="importe" class="form-control" placeholder="Importe (€)" required></div>
            <div class="col-md-1"><button type="submit" class="btn btn-primary w-100">Guardar</button></div>
        </div>
    </form>
    <div class="table-responsive">
    <table class="table table-striped table-bordered align-middle">
        <thead class="table-dark"><tr><th>Fecha</th><th>Concepto</th><th>Categoría</th><th>Importe</th><th>Acciones</th></tr></thead>
        <tbody>
            {% for r in rows %}
            <tr>
                <td>{{ r[1] }}</td><td>{{ r[2] }}</td><td>{{ r[3] }}</td><td>{{ "%.2f"|format(r[4]) }}€</td>
                <td>
                    <button class="btn btn-warning btn-sm" data-bs-toggle="modal" data-bs-target="#modalEditarGasto{{ r[0] }}" title="Editar">✏️</button>
                    <a href="/eliminar_gasto/{{ r[0] }}" class="btn btn-danger btn-sm" onclick="return confirm('¿Eliminar gasto?')" title="Eliminar">🗑️</a>
                </td>
            </tr>

            <!-- Modal Editar Gasto -->
            <div class="modal fade" id="modalEditarGasto{{ r[0] }}" tabindex="-1">
              <div class="modal-dialog">
                <form action="/actualizar_gasto/{{ r[0] }}" method="POST" class="modal-content">
                  <div class="modal-header"><h5 class="modal-title">Editar Gasto</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
                  <div class="modal-body">
                    <div class="mb-2"><label>Fecha</label><input type="date" name="fecha" value="{{ r[1] }}" class="form-control" required></div>
                    <div class="mb-2"><label>Concepto</label><input type="text" name="concepto" value="{{ r[2] }}" class="form-control" required></div>
                    <div class="mb-2"><label>Categoría</label>
                        <select name="categoria" class="form-select">
                            <option {% if r[3]=='Gasolina / Transporte' %}selected{% endif %}>Gasolina / Transporte</option>
                            <option {% if r[3]=='Alquileres' %}selected{% endif %}>Alquileres</option>
                            <option {% if r[3]=='Mantenimiento' %}selected{% endif %}>Mantenimiento</option>
                            <option {% if r[3]=='Producto / Mercancía' %}selected{% endif %}>Producto / Mercancía</option>
                            <option {% if r[3]=='Otros' %}selected{% endif %}>Otros</option>
                        </select>
                    </div>
                    <div class="mb-2"><label>Importe (€)</label><input type="number" step="0.01" name="importe" value="{{ r[4] }}" class="form-control" required></div>
                  </div>
                  <div class="modal-footer"><button type="submit" class="btn btn-primary">Actualizar</button></div>
                </form>
              </div>
            </div>
            {% endfor %}
        </tbody>
    </table>
    </div>
    """)
    return render_template_string(html, rows=rows)

@app.route("/guardar_gasto", methods=["POST"])
@login_required
def guardar_gasto():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO gastos (fecha, concepto, categoria, importe) VALUES (%s, %s, %s, %s)",
                   (request.form["fecha"], request.form["concepto"], request.form["categoria"], float(request.form["importe"])))
    conn.commit()
    conn.close()
    flash("Gasto guardado", "success")
    return redirect(url_for("gastos"))

@app.route("/actualizar_gasto/<int:id>", methods=["POST"])
@login_required
def actualizar_gasto(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE gastos SET fecha = %s, concepto = %s, categoria = %s, importe = %s WHERE id = %s",
                   (request.form["fecha"], request.form["concepto"], request.form["categoria"], float(request.form["importe"]), id))
    conn.commit()
    conn.close()
    flash("Gasto actualizado", "success")
    return redirect(url_for("gastos"))

@app.route("/eliminar_gasto/<int:id>")
@login_required
def eliminar_gasto(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM gastos WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    flash("Gasto eliminado", "warning")
    return redirect(url_for("gastos"))

@app.route("/balance")
@login_required
def balance():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(subtotal) FROM ventas")
    res_v = cursor.fetchone()
    ventas = res_v[0] if res_v and res_v[0] else 0.0

    cursor.execute("SELECT SUM(iva_linea) FROM ventas")
    res_iva = cursor.fetchone()
    iva_ventas = res_iva[0] if res_iva and res_iva[0] else 0.0

    cursor.execute("SELECT SUM(importe) FROM gastos")
    res_g = cursor.fetchone()
    gastos = res_g[0] if res_g and res_g[0] else 0.0
    conn.close()
    
    neto = ventas - gastos

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", f"""
    <h2>📈 Balance General de Resultados</h2>
    <div class="card p-4 shadow-sm mt-4">
        <h4 class="text-success">(+) Ventas Totales (Base Imponible): {ventas:.2f} €</h4>
        <h4 class="text-info mt-3">(+) IVA Repercutido (Ventas): {iva_ventas:.2f} €</h4>
        <h4 class="text-danger mt-3">(-) Total Gastos Imputados: {gastos:.2f} €</h4>
        <hr>
        <h3 class="mt-3 {'text-success' if neto >= 0 else 'text-danger'}">(=) BALANCE NETO / BENEFICIO: {neto:.2f} €</h3>
    </div>
    """)
    return render_template_string(html)

@app.route("/procesar_factura", methods=["POST"])
@login_required
def procesar_factura():
    cliente = request.form["cliente"]
    num_fac = request.form["num_factura"]
    productos = request.form.getlist("producto[]")
    cantidades = request.form.getlist("cantidad[]")
    precios = request.form.getlist("precio_unit[]")
    ivas = request.form.getlist("iva_linea[]")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT nif, tipo_cliente, recargo, direccion FROM clientes WHERE nombre = %s", (cliente,))
    res_cli = cursor.fetchone()
    _, tipo_cliente, aplica_recargo, _ = res_cli if res_cli else ("", "Estándar", "NO", "")

    base_imponible_total = 0
    iva_total = 0
    recargo_total = 0
    lineas_temp = []

    for prod, cant_s, prec_s, iva_s in zip(productos, cantidades, precios, ivas):
        if not prod: continue
        cant = int(cant_s)
        precio = float(prec_s)
        iva = float(iva_s)

        sub = cant * precio
        iva_linea_val = sub * iva
        
        # Recargo de equivalencia estándar (1.4% para IVA 10%, 5.2% para IVA 21%)
        rec_linea = 0
        if aplica_recargo == "SÍ":
            if abs(iva - 0.10) < 0.01:
                rec_linea = sub * 0.014
            elif abs(iva - 0.21) < 0.01:
                rec_linea = sub * 0.052

        base_imponible_total += sub
        iva_total += iva_linea_val
        recargo_total += rec_linea

        lineas_temp.append((prod, cant, precio, iva, sub, iva_linea_val, rec_linea))

    total_factura = base_imponible_total + iva_total + recargo_total
    fecha_hoy = datetime.date.today().strftime("%Y-%m-%d")

    try:
        cursor.execute("""
            INSERT INTO facturas (num_factura, fecha, cliente, tipo_cliente, recargo, base_imponible, iva_total, recargo_total, total_factura)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (num_fac, fecha_hoy, cliente, tipo_cliente, aplica_recargo, base_imponible_total, iva_total, recargo_total, total_factura))

        for item in lineas_temp:
            desc, cant, precio, iva, sub, iva_linea_val, rec_linea = item
            cursor.execute("INSERT INTO ventas_lineas (num_factura, producto, cantidad, precio, iva) VALUES (%s, %s, %s, %s, %s)", 
                           (num_fac, desc, cant, precio, iva))
            
            tot_linea = sub + iva_linea_val + rec_linea
            
            cursor.execute("""
                INSERT INTO ventas (fecha, factura, cliente, tipo_cliente, producto, cantidad, precio_venta, subtotal, iva_linea, recargo_equivalencia, total)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (fecha_hoy, num_fac, cliente, tipo_cliente, desc, cant, precio, sub, iva_linea_val, rec_linea, tot_linea))

        conn.commit()
        flash("Factura emitida correctamente, IVA contabilizado y stock actualizado", "success")
    except Exception as e:
        flash(f"Error al procesar la factura: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("historico"))

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)

