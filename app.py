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
            precio REAL NOT NULL
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
            <a class="navbar-brand" href="/">🥩 Distribución Carnicerías</a>
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
    cursor.execute("SELECT nombre FROM clientes")
    clientes = [r[0] for r in cursor.fetchall()]
    cursor.execute("SELECT codigo, descripcion, precio FROM productos")
    productos = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) FROM facturas")
    num_factura = f"FAC-2026-{(cursor.fetchone()[0] + 1):03d}"
    conn.close()

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <div class="row">
        <div class="col-md-12">
            <h2 class="mb-4">📄 Emitir Factura / Pedido</h2>
            <form action="/procesar_factura" method="POST" class="card p-4 shadow-sm">
                <div class="row mb-3">
                    <div class="col-md-6">
                        <label class="form-label">Cliente / Carnicería</label>
                        <select name="cliente" class="form-select" required>
                            <option value="">Seleccione un cliente...</option>
                            {% for c in clientes %}
                            <option value="{{ c }}">{{ c }}</option>
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
                    <div class="row mb-2 linea-row">
                        <div class="col-md-5">
                            <select name="producto[]" class="form-select prod-select" onchange="actualizarPrecio(this)" required>
                                <option value="">Seleccione producto...</option>
                                {% for p in productos %}
                                <option value="{{ p[1] }}" data-precio="{{ p[2] }}">{{ p[0] }} - {{ p[1] }} ({{ p[2] }}€)</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="col-md-3">
                            <input type="number" name="cantidad[]" class="form-control" placeholder="Cantidad" value="1" min="1" required>
                        </div>
                        <div class="col-md-3">
                            <input type="number" step="0.01" name="precio_unit[]" class="form-control precio-input" placeholder="Precio Unit. (€)" required>
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
    function actualizarPrecio(select) {
        let precio = select.options[select.selectedIndex].getAttribute('data-precio');
        let row = select.closest('.linea-row');
        row.querySelector('.precio-input').value = precio;
    }
    function addLinea() {
        let container = document.getElementById('lineas-container');
        let primeraLinea = container.querySelector('.linea-row');
        let clone = primeraLinea.cloneNode(true);
        clone.querySelector('input').value = '1';
        container.appendChild(clone);
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
    cursor.execute("SELECT id, codigo, descripcion, precio, iva, stock_inicial, compras, stock_minimo FROM productos")
    rows = cursor.fetchall()
    
    datos = []
    for r in rows:
        p_id, cod, desc, precio, iva, ini, comp, min_s = r
        cursor.execute("SELECT SUM(cantidad) FROM ventas_lineas WHERE producto = %s", (desc,))
        res_v = cursor.fetchone()
        v = res_v[0] if res_v and res_v[0] else 0
        actual = ini + comp - v
        estado = "Reponer" if actual <= min_s else "OK"
        datos.append((p_id, cod, desc, f"{precio:.2f}€", f"{int(iva*100)}%", ini, comp, v, actual, estado))
    conn.close()

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2>📦 Control de Almacén y Productos</h2>
        <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#modalCrearProducto">➕ Nuevo Producto</button>
    </div>
    <table class="table table-striped table-bordered">
        <thead class="table-dark">
            <tr><th>Código</th><th>Descripción</th><th>Precio</th><th>IVA</th><th>Stock Ini.</th><th>Compras</th><th>Ventas</th><th>Disponible</th><th>Estado</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for d in datos %}
            <tr>
                <td>{{ d[1] }}</td><td>{{ d[2] }}</td><td>{{ d[3] }}</td><td>{{ d[4] }}</td><td>{{ d[5] }}</td><td>{{ d[6] }}</td><td>{{ d[7] }}</td><td><strong>{{ d[8] }}</strong></td>
                <td><span class="badge {{ 'bg-danger' if d[9]=='Reponer' else 'bg-success' }}">{{ d[9] }}</span></td>
                <td>
                    <a href="/eliminar_producto/{{ d[0] }}" class="btn btn-danger btn-sm" onclick="return confirm('¿Eliminar producto?')">🗑️</a>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

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
              int(request.form["stock_inicial"]), int(request.form["compras"]), int(request.form["stock_minimo"])))
        conn.commit()
        flash("Producto guardado correctamente", "success")
    except Exception as e:
        flash(f"Error al guardar producto: {e}", "danger")
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
    cursor.execute("SELECT id, nombre, nif, tipo_cliente, recargo, direccion FROM clientes")
    rows = cursor.fetchall()
    conn.close()

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2>👥 Clientes (Carnicerías)</h2>
        <button class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#modalCrearCliente">➕ Nuevo Cliente</button>
    </div>
    <table class="table table-striped table-bordered">
        <thead class="table-dark">
            <tr><th>Nombre</th><th>NIF</th><th>Tipo</th><th>Recargo Equiv.</th><th>Dirección</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for r in rows %}
            <tr>
                <td>{{ r[1] }}</td><td>{{ r[2] }}</td><td>{{ r[3] }}</td><td>{{ r[4] }}</td><td>{{ r[5] }}</td>
                <td><a href="/eliminar_cliente/{{ r[0] }}" class="btn btn-danger btn-sm" onclick="return confirm('¿Eliminar cliente?')">🗑️</a></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

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
            INSERT INTO clientes (nombre, nif, tipo_cliente, recargo, direccion)
            VALUES (%s, %s, %s, %s, %s)
        """, (request.form["nombre"], request.form["nif"], request.form["tipo_cliente"], request.form["recargo"], request.form["direccion"]))
        conn.commit()
        flash("Cliente registrado con éxito", "success")
    except Exception as e:
        flash(f"Error al registrar cliente: {e}", "danger")
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
    cursor.execute("SELECT id, num_factura, fecha, cliente, tipo_cliente, recargo, base_imponible, iva_total, recargo_total, total_factura FROM facturas")
    rows = cursor.fetchall()
    conn.close()

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <h2>📊 Histórico de Facturas</h2>
    <table class="table table-striped table-bordered mt-3">
        <thead class="table-dark">
            <tr><th>Nº Factura</th><th>Fecha</th><th>Cliente</th><th>Base Imp.</th><th>IVA</th><th>Recargo</th><th>Total</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for r in rows %}
            <tr>
                <td>{{ r[1] }}</td><td>{{ r[2] }}</td><td>{{ r[3] }}</td><td>{{ "%.2f"|format(r[6]) }}€</td><td>{{ "%.2f"|format(r[7]) }}€</td><td>{{ "%.2f"|format(r[8]) }}€</td><td><strong>{{ "%.2f"|format(r[9]) }}€</strong></td>
                <td>
                    <a href="/descargar_pdf/{{ r[1] }}" class="btn btn-danger btn-sm">📄 Descargar PDF</a>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    """)
    return render_template_string(html, rows=rows)

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

    cursor.execute("SELECT producto, cantidad, precio FROM ventas_lineas WHERE num_factura = %s", (num_factura,))
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

    story.append(Paragraph(f"<b>FACTURA: {fac[0]}</b>", styles['Title']))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"<b>Fecha:</b> {fac[1]}", styles['Normal']))
    story.append(Paragraph(f"<b>Cliente:</b> {fac[2]} (NIF: {nif_cli})", styles['Normal']))
    story.append(Paragraph(f"<b>Dirección:</b> {dir_cli}", styles['Normal']))
    story.append(Spacer(1, 15))

    table_data = [["Producto", "Cantidad", "Precio Unitario", "Subtotal"]]
    for l in lineas:
        sub = l[1] * l[2]
        table_data.append([l[0], str(l[1]), f"{l[2]:.2f} €", f"{sub:.2f} €"])

    t = Table(table_data, colWidths=[200, 80, 100, 100])
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
    cursor.execute("SELECT id, fecha, factura, cliente, producto, cantidad, precio_venta, subtotal, total FROM ventas")
    rows = cursor.fetchall()
    conn.close()

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <h2>📋 Detalle de Ventas</h2>
    <table class="table table-striped table-bordered mt-3">
        <thead class="table-dark">
            <tr><th>Fecha</th><th>Factura</th><th>Cliente</th><th>Producto</th><th>Cant.</th><th>Precio Unit.</th><th>Subtotal</th><th>Total</th></tr>
        </thead>
        <tbody>
            {% for r in rows %}
            <tr><td>{{ r[1] }}</td><td>{{ r[2] }}</td><td>{{ r[3] }}</td><td>{{ r[4] }}</td><td>{{ r[5] }}</td><td>{{ "%.2f"|format(r[6]) }}€</td><td>{{ "%.2f"|format(r[7]) }}€</td><td><strong>{{ "%.2f"|format(r[8]) }}€</strong></td></tr>
            {% endfor %}
        </tbody>
    </table>
    """)
    return render_template_string(html, rows=rows)

@app.route("/gastos")
@login_required
def gastos():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, fecha, concepto, categoria, importe FROM gastos")
    rows = cursor.fetchall()
    conn.close()

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", """
    <h2>💸 Gastos de la Empresa</h2>
    <form action="/guardar_gasto" method="POST" class="card p-3 mb-4 shadow-sm">
        <div class="row">
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
    <table class="table table-striped table-bordered">
        <thead class="table-dark"><tr><th>Fecha</th><th>Concepto</th><th>Categoría</th><th>Importe</th></tr></thead>
        <tbody>
            {% for r in rows %}
            <tr><td>{{ r[1] }}</td><td>{{ r[2] }}</td><td>{{ r[3] }}</td><td>{{ "%.2f"|format(r[4]) }}€</td></tr>
            {% endfor %}
        </tbody>
    </table>
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

@app.route("/balance")
@login_required
def balance():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(subtotal) FROM ventas")
    res_v = cursor.fetchone()
    ventas = res_v[0] if res_v and res_v[0] else 0.0
    cursor.execute("SELECT SUM(importe) FROM gastos")
    res_g = cursor.fetchone()
    gastos = res_g[0] if res_g and res_g[0] else 0.0
    conn.close()
    neto = ventas - gastos

    html = BASE_LAYOUT.replace("{% block content %}{% endblock %}", f"""
    <h2>📈 Balance General de Resultados</h2>
    <div class="card p-4 shadow-sm mt-4">
        <h4 class="text-success">(+) Ventas Totales (Base Imponible): {ventas:.2f} €</h4>
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

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT nif, tipo_cliente, recargo, direccion FROM clientes WHERE nombre = %s", (cliente,))
    res_cli = cursor.fetchone()
    _, tipo_cliente, aplica_recargo, _ = res_cli if res_cli else ("", "Estándar", "NO", "")

    base_10, base_21 = 0, 0
    lineas_temp = []

    for prod, cant_s, prec_s in zip(productos, cantidades, precios):
        if not prod: continue
        cant = int(cant_s)
        precio = float(prec_s)

        cursor.execute("SELECT iva FROM productos WHERE descripcion = %s", (prod,))
        p_data = cursor.fetchone()
        iva = p_data[0] if p_data else 0.21

        sub = cant * precio
        lineas_temp.append((prod, cant, precio, iva, sub))

        if iva == 0.10: base_10 += sub
        elif iva == 0.21: base_21 += sub

    iva_total = (base_10 * 0.10) + (base_21 * 0.21)
    recargo_total = ((base_10 * 0.014) + (base_21 * 0.052)) if aplica_recargo == "SÍ" else 0
    base_imponible = base_10 + base_21
    total_factura = base_imponible + iva_total + recargo_total
    fecha_hoy = datetime.date.today().strftime("%Y-%m-%d")

    try:
        cursor.execute("""
            INSERT INTO facturas (num_factura, fecha, cliente, tipo_cliente, recargo, base_imponible, iva_total, recargo_total, total_factura)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (num_fac, fecha_hoy, cliente, tipo_cliente, aplica_recargo, base_imponible, iva_total, recargo_total, total_factura))

        for item in lineas_temp:
            desc, cant, precio, iva, sub = item
            cursor.execute("INSERT INTO ventas_lineas (num_factura, producto, cantidad, precio) VALUES (%s, %s, %s, %s)", (num_fac, desc, cant, precio))
            rec_linea = (sub * 0.014) if iva == 0.10 and aplica_recargo == "SÍ" else ((sub * 0.052) if iva == 0.21 and aplica_recargo == "SÍ" else 0)
            tot_linea = sub + (sub * iva) + rec_linea
            
            cursor.execute("""
                INSERT INTO ventas (fecha, factura, cliente, tipo_cliente, producto, cantidad, precio_venta, subtotal, recargo_equivalencia, total)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (fecha_hoy, num_fac, cliente, tipo_cliente, desc, cant, precio, sub, rec_linea, tot_linea))

        conn.commit()
        flash("Factura emitida correctamente y stock actualizado", "success")
    except Exception as e:
        flash(f"Error al procesar la factura: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("historico"))

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)

