"""
API de Clínica - Programación II (Proyecto final)
--------------------------------------------------
Construida siguiendo la misma línea que la "API de Matrícula" vista en
clase, pero con un tema distinto (una clínica) y más tablas:

  - 7 tablas relacionadas en SQLite:
        usuarios, pacientes, doctores, citas, consultas, medicamentos, recetas
  - Login con usuario y contraseña (contraseñas guardadas con hash, nunca en texto plano)
  - Sesión por token (parecido a un "gafete" que el servidor entrega al iniciar sesión)
  - Un Dashboard (panel) en HTML que consume la propia API con JavaScript (fetch)

El archivo se lee de arriba hacia abajo, en el mismo orden en que se va
construyendo: PASO 1, PASO 2, PASO 3...

Flujo del negocio (lo importante para entender el proyecto):
    1. Se registra un paciente y un doctor.
    2. Se agenda una CITA entre un paciente y un doctor (fecha + hora).
    3. Cuando el doctor atiende la cita, se registra una CONSULTA
       (diagnóstico y tratamiento). La cita pasa de "pendiente" a "atendida".
    4. Desde una consulta se pueden recetar MEDICAMENTOS -> eso genera
       una o varias filas en RECETAS, y se descuenta el stock del medicamento.
"""

import hashlib
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field


# =============================================================================
# PASO 1: Configuración general y conexión a la base de datos
# =============================================================================

DB_NAME = "clinica.db"
DURACION_SESION_HORAS = 2  # cuánto dura activo un token después de iniciar sesión


def obtener_conexion():
    conexion = sqlite3.connect(DB_NAME)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


# =============================================================================
# PASO 2: Creación de las 7 tablas
# =============================================================================
# usuarios      -> cuentas que pueden iniciar sesión (login) al panel/API
# pacientes     -> personas que se atienden en la clínica
# doctores      -> médicos que atienden citas
# citas         -> tabla "puente" que agenda un paciente con un doctor
# consultas     -> resultado de atender una cita (diagnóstico y tratamiento)
# medicamentos  -> catálogo de medicamentos disponibles (con stock)
# recetas       -> tabla "puente" que relaciona una consulta con los
#                  medicamentos que se recetaron en ella


def crear_tablas():
    with obtener_conexion() as conexion:
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_usuario TEXT NOT NULL UNIQUE,
                contrasena_hash TEXT NOT NULL,
                contrasena_salt TEXT NOT NULL,
                rol TEXT NOT NULL DEFAULT 'admin',
                token TEXT,
                token_expira TEXT
            )
            """
        )
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS pacientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                identidad TEXT NOT NULL UNIQUE,
                telefono TEXT NOT NULL,
                correo TEXT NOT NULL UNIQUE,
                edad INTEGER NOT NULL
            )
            """
        )
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS doctores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                colegiacion TEXT NOT NULL UNIQUE,
                especialidad TEXT NOT NULL,
                telefono TEXT NOT NULL,
                correo TEXT NOT NULL UNIQUE
            )
            """
        )
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS citas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paciente_id INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                motivo TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente',
                FOREIGN KEY (paciente_id) REFERENCES pacientes (id),
                FOREIGN KEY (doctor_id) REFERENCES doctores (id),
                UNIQUE (doctor_id, fecha, hora)
            )
            """
        )
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS consultas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cita_id INTEGER NOT NULL UNIQUE,
                paciente_id INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                diagnostico TEXT NOT NULL,
                tratamiento TEXT NOT NULL,
                notas TEXT,
                fecha_consulta TEXT NOT NULL,
                FOREIGN KEY (cita_id) REFERENCES citas (id),
                FOREIGN KEY (paciente_id) REFERENCES pacientes (id),
                FOREIGN KEY (doctor_id) REFERENCES doctores (id)
            )
            """
        )
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS medicamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                presentacion TEXT NOT NULL,
                stock INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS recetas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                consulta_id INTEGER NOT NULL,
                medicamento_id INTEGER NOT NULL,
                dosis TEXT NOT NULL,
                cantidad INTEGER NOT NULL,
                indicaciones TEXT,
                FOREIGN KEY (consulta_id) REFERENCES consultas (id),
                FOREIGN KEY (medicamento_id) REFERENCES medicamentos (id)
            )
            """
        )


def crear_usuario_admin_si_no_existe():
    """Crea un usuario admin/admin123 la primera vez que se ejecuta el proyecto,
    para poder iniciar sesión sin tener que registrar nada a mano."""
    with obtener_conexion() as conexion:
        existe = conexion.execute("SELECT id FROM usuarios").fetchone()
        if existe is None:
            salt, hash_ = generar_hash_contrasena("admin123")
            conexion.execute(
                """
                INSERT INTO usuarios (nombre_usuario, contrasena_hash, contrasena_salt, rol)
                VALUES (?, ?, ?, ?)
                """,
                ("admin", hash_, salt, "admin"),
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    crear_tablas()
    crear_usuario_admin_si_no_existe()
    yield


app = FastAPI(
    title="API de Clínica",
    description="API CRUD con login y dashboard para Programación II, usando FastAPI y SQLite.",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
plantillas = Jinja2Templates(directory="templates")


# =============================================================================
# PASO 3: Seguridad -> hash de contraseñas y manejo del token de sesión
# =============================================================================
# Nunca guardamos la contraseña "tal cual" en la base de datos. Guardamos:
#   - un "salt" (texto aleatorio) distinto para cada usuario
#   - el resultado de mezclar la contraseña + salt con un algoritmo (PBKDF2)
# Así, aunque alguien vea la base de datos, no puede leer la contraseña real.


def generar_hash_contrasena(contrasena: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    hash_bytes = hashlib.pbkdf2_hmac(
        "sha256", contrasena.encode("utf-8"), salt.encode("utf-8"), 100_000
    )
    return salt, hash_bytes.hex()


def verificar_contrasena(contrasena: str, salt: str, hash_guardado: str) -> bool:
    _, hash_calculado = generar_hash_contrasena(contrasena, salt)
    return secrets.compare_digest(hash_calculado, hash_guardado)


def obtener_usuario_por_token(token: str):
    with obtener_conexion() as conexion:
        fila = conexion.execute(
            "SELECT * FROM usuarios WHERE token = ?", (token,)
        ).fetchone()
    if fila is None:
        return None
    if fila["token_expira"] is None or datetime.fromisoformat(fila["token_expira"]) < datetime.utcnow():
        return None
    return fila


def obtener_usuario_actual(request: Request):
    """Dependencia de FastAPI: revisa el encabezado Authorization (para Postman)
    o la cookie 'token' (para el navegador) y devuelve el usuario si la sesión
    es válida. Si no, corta la petición con un error 401."""
    token = None
    encabezado = request.headers.get("Authorization")
    if encabezado and encabezado.startswith("Bearer "):
        token = encabezado.removeprefix("Bearer ").strip()
    if token is None:
        token = request.cookies.get("token")

    if not token:
        raise HTTPException(status_code=401, detail="No ha iniciado sesión")

    usuario = obtener_usuario_por_token(token)
    if usuario is None:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    return usuario


# =============================================================================
# PASO 4: Modelos Pydantic (uno por tabla)
# =============================================================================

class LoginEntrada(BaseModel):
    nombre_usuario: str = Field(min_length=3, max_length=50)
    contrasena: str = Field(min_length=4, max_length=100)


class UsuarioCrear(BaseModel):
    nombre_usuario: str = Field(min_length=3, max_length=50)
    contrasena: str = Field(min_length=4, max_length=100)
    rol: str = Field(default="admin", max_length=20)


class UsuarioRespuesta(BaseModel):
    id: int
    nombre_usuario: str
    rol: str


class PacienteBase(BaseModel):
    nombre: str = Field(min_length=3, max_length=100)
    identidad: str = Field(min_length=3, max_length=30)
    telefono: str = Field(min_length=4, max_length=20)
    correo: EmailStr
    edad: int = Field(ge=0, le=120)


class PacienteCrear(PacienteBase):
    pass


class PacienteRespuesta(PacienteBase):
    id: int


class DoctorBase(BaseModel):
    nombre: str = Field(min_length=3, max_length=100)
    colegiacion: str = Field(min_length=2, max_length=30)
    especialidad: str = Field(min_length=3, max_length=100)
    telefono: str = Field(min_length=4, max_length=20)
    correo: EmailStr


class DoctorCrear(DoctorBase):
    pass


class DoctorRespuesta(DoctorBase):
    id: int


class CitaCrear(BaseModel):
    paciente_id: int
    doctor_id: int
    fecha: str = Field(min_length=8, max_length=10, description="Formato AAAA-MM-DD")
    hora: str = Field(min_length=4, max_length=5, description="Formato HH:MM")
    motivo: str = Field(min_length=3, max_length=200)


class CitaRespuesta(BaseModel):
    id: int
    paciente_id: int
    paciente_nombre: str
    doctor_id: int
    doctor_nombre: str
    fecha: str
    hora: str
    motivo: str
    estado: str


class ConsultaCrear(BaseModel):
    cita_id: int
    diagnostico: str = Field(min_length=3, max_length=300)
    tratamiento: str = Field(min_length=3, max_length=300)
    notas: str | None = Field(default=None, max_length=500)


class ConsultaRespuesta(BaseModel):
    id: int
    cita_id: int
    paciente_id: int
    paciente_nombre: str
    doctor_id: int
    doctor_nombre: str
    diagnostico: str
    tratamiento: str
    notas: str | None
    fecha_consulta: str


class MedicamentoBase(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    presentacion: str = Field(min_length=2, max_length=100)
    stock: int = Field(ge=0, le=100000)


class MedicamentoCrear(MedicamentoBase):
    pass


class MedicamentoRespuesta(MedicamentoBase):
    id: int


class RecetaCrear(BaseModel):
    consulta_id: int
    medicamento_id: int
    dosis: str = Field(min_length=2, max_length=100)
    cantidad: int = Field(ge=1, le=1000)
    indicaciones: str | None = Field(default=None, max_length=300)


class RecetaRespuesta(BaseModel):
    id: int
    consulta_id: int
    medicamento_id: int
    medicamento_nombre: str
    dosis: str
    cantidad: int
    indicaciones: str | None


class ResumenDashboard(BaseModel):
    total_pacientes: int
    total_doctores: int
    citas_pendientes: int
    total_consultas: int


# =============================================================================
# PASO 5: Raíz de la API
# =============================================================================

@app.get("/")
def inicio():
    return {"mensaje": "API de clínica funcionando correctamente"}


# =============================================================================
# PASO 6: Autenticación -> /auth/login, /auth/logout, /auth/yo, /auth/usuarios
# =============================================================================

@app.post("/auth/login")
def iniciar_sesion(datos: LoginEntrada, response: Response):
    with obtener_conexion() as conexion:
        usuario = conexion.execute(
            "SELECT * FROM usuarios WHERE nombre_usuario = ?", (datos.nombre_usuario,)
        ).fetchone()

        if usuario is None or not verificar_contrasena(
            datos.contrasena, usuario["contrasena_salt"], usuario["contrasena_hash"]
        ):
            raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

        token = secrets.token_hex(32)
        expira = datetime.utcnow() + timedelta(hours=DURACION_SESION_HORAS)
        conexion.execute(
            "UPDATE usuarios SET token = ?, token_expira = ? WHERE id = ?",
            (token, expira.isoformat(), usuario["id"]),
        )

    # Cookie para que el navegador (dashboard.html) mantenga la sesión sin
    # tener que guardar el token a mano en JavaScript.
    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
        max_age=DURACION_SESION_HORAS * 3600,
    )
    return {
        "mensaje": "Sesión iniciada correctamente",
        "token": token,
        "usuario": usuario["nombre_usuario"],
        "rol": usuario["rol"],
    }


@app.post("/auth/logout")
def cerrar_sesion(response: Response, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        conexion.execute(
            "UPDATE usuarios SET token = NULL, token_expira = NULL WHERE id = ?",
            (usuario["id"],),
        )
    response.delete_cookie("token")
    return {"mensaje": "Sesión cerrada correctamente"}


@app.get("/auth/yo", response_model=UsuarioRespuesta)
def usuario_autenticado(usuario=Depends(obtener_usuario_actual)):
    return dict(usuario)


@app.post(
    "/auth/usuarios",
    response_model=UsuarioRespuesta,
    status_code=status.HTTP_201_CREATED,
)
def crear_usuario(datos: UsuarioCrear, usuario=Depends(obtener_usuario_actual)):
    try:
        salt, hash_ = generar_hash_contrasena(datos.contrasena)
        with obtener_conexion() as conexion:
            cursor = conexion.execute(
                """
                INSERT INTO usuarios (nombre_usuario, contrasena_hash, contrasena_salt, rol)
                VALUES (?, ?, ?, ?)
                """,
                (datos.nombre_usuario, hash_, salt, datos.rol),
            )
            fila = conexion.execute(
                "SELECT * FROM usuarios WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(fila)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ese nombre de usuario ya existe")


@app.get("/auth/usuarios", response_model=list[UsuarioRespuesta])
def listar_usuarios(usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        filas = conexion.execute("SELECT * FROM usuarios ORDER BY id").fetchall()
        return [dict(fila) for fila in filas]


# =============================================================================
# PASO 7: CRUD de pacientes
# =============================================================================

@app.post(
    "/pacientes",
    response_model=PacienteRespuesta,
    status_code=status.HTTP_201_CREATED,
)
def crear_paciente(paciente: PacienteCrear, usuario=Depends(obtener_usuario_actual)):
    try:
        with obtener_conexion() as conexion:
            cursor = conexion.execute(
                """
                INSERT INTO pacientes (nombre, identidad, telefono, correo, edad)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    paciente.nombre,
                    paciente.identidad,
                    paciente.telefono,
                    paciente.correo,
                    paciente.edad,
                ),
            )
            fila = conexion.execute(
                "SELECT * FROM pacientes WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(fila)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409, detail="La identidad o el correo ya están registrados"
        )


@app.get("/pacientes", response_model=list[PacienteRespuesta])
def listar_pacientes(usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        filas = conexion.execute("SELECT * FROM pacientes ORDER BY id").fetchall()
        return [dict(fila) for fila in filas]


@app.get("/pacientes/{paciente_id}", response_model=PacienteRespuesta)
def obtener_paciente(paciente_id: int, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        fila = conexion.execute(
            "SELECT * FROM pacientes WHERE id = ?", (paciente_id,)
        ).fetchone()
    if fila is None:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    return dict(fila)


@app.put("/pacientes/{paciente_id}", response_model=PacienteRespuesta)
def actualizar_paciente(
    paciente_id: int, paciente: PacienteCrear, usuario=Depends(obtener_usuario_actual)
):
    try:
        with obtener_conexion() as conexion:
            cursor = conexion.execute(
                """
                UPDATE pacientes
                SET nombre = ?, identidad = ?, telefono = ?, correo = ?, edad = ?
                WHERE id = ?
                """,
                (
                    paciente.nombre,
                    paciente.identidad,
                    paciente.telefono,
                    paciente.correo,
                    paciente.edad,
                    paciente_id,
                ),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Paciente no encontrado")
            fila = conexion.execute(
                "SELECT * FROM pacientes WHERE id = ?", (paciente_id,)
            ).fetchone()
            return dict(fila)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409, detail="La identidad o el correo ya pertenecen a otro paciente"
        )


@app.delete("/pacientes/{paciente_id}")
def eliminar_paciente(paciente_id: int, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        en_uso = conexion.execute(
            "SELECT id FROM citas WHERE paciente_id = ?", (paciente_id,)
        ).fetchone()
        if en_uso:
            raise HTTPException(
                status_code=409,
                detail="No se puede eliminar: el paciente tiene citas registradas",
            )
        cursor = conexion.execute("DELETE FROM pacientes WHERE id = ?", (paciente_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Paciente no encontrado")
    return {"mensaje": "Paciente eliminado correctamente"}


# =============================================================================
# PASO 8: CRUD de doctores
# =============================================================================

@app.post("/doctores", response_model=DoctorRespuesta, status_code=status.HTTP_201_CREATED)
def crear_doctor(doctor: DoctorCrear, usuario=Depends(obtener_usuario_actual)):
    try:
        with obtener_conexion() as conexion:
            cursor = conexion.execute(
                """
                INSERT INTO doctores (nombre, colegiacion, especialidad, telefono, correo)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    doctor.nombre,
                    doctor.colegiacion,
                    doctor.especialidad,
                    doctor.telefono,
                    doctor.correo,
                ),
            )
            fila = conexion.execute(
                "SELECT * FROM doctores WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(fila)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409, detail="La colegiación o el correo ya están registrados"
        )


@app.get("/doctores", response_model=list[DoctorRespuesta])
def listar_doctores(usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        filas = conexion.execute("SELECT * FROM doctores ORDER BY id").fetchall()
        return [dict(fila) for fila in filas]


@app.get("/doctores/{doctor_id}", response_model=DoctorRespuesta)
def obtener_doctor(doctor_id: int, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        fila = conexion.execute("SELECT * FROM doctores WHERE id = ?", (doctor_id,)).fetchone()
    if fila is None:
        raise HTTPException(status_code=404, detail="Doctor no encontrado")
    return dict(fila)


@app.put("/doctores/{doctor_id}", response_model=DoctorRespuesta)
def actualizar_doctor(doctor_id: int, doctor: DoctorCrear, usuario=Depends(obtener_usuario_actual)):
    try:
        with obtener_conexion() as conexion:
            cursor = conexion.execute(
                """
                UPDATE doctores
                SET nombre = ?, colegiacion = ?, especialidad = ?, telefono = ?, correo = ?
                WHERE id = ?
                """,
                (
                    doctor.nombre,
                    doctor.colegiacion,
                    doctor.especialidad,
                    doctor.telefono,
                    doctor.correo,
                    doctor_id,
                ),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Doctor no encontrado")
            fila = conexion.execute(
                "SELECT * FROM doctores WHERE id = ?", (doctor_id,)
            ).fetchone()
            return dict(fila)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ya existe otro doctor con esa colegiación o correo")


@app.delete("/doctores/{doctor_id}")
def eliminar_doctor(doctor_id: int, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        en_uso = conexion.execute(
            "SELECT id FROM citas WHERE doctor_id = ?", (doctor_id,)
        ).fetchone()
        if en_uso:
            raise HTTPException(
                status_code=409,
                detail="No se puede eliminar: el doctor tiene citas registradas",
            )
        cursor = conexion.execute("DELETE FROM doctores WHERE id = ?", (doctor_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Doctor no encontrado")
    return {"mensaje": "Doctor eliminado correctamente"}


# =============================================================================
# PASO 9: Citas -> la tabla que une pacientes con doctores
# =============================================================================

def _fila_a_cita(conexion, cita_id: int) -> dict:
    fila = conexion.execute(
        """
        SELECT c.id, c.paciente_id, p.nombre AS paciente_nombre,
               c.doctor_id, d.nombre AS doctor_nombre,
               c.fecha, c.hora, c.motivo, c.estado
        FROM citas c
        JOIN pacientes p ON p.id = c.paciente_id
        JOIN doctores d ON d.id = c.doctor_id
        WHERE c.id = ?
        """,
        (cita_id,),
    ).fetchone()
    return dict(fila)


@app.post("/citas", response_model=CitaRespuesta, status_code=status.HTTP_201_CREATED)
def crear_cita(datos: CitaCrear, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        paciente = conexion.execute(
            "SELECT id FROM pacientes WHERE id = ?", (datos.paciente_id,)
        ).fetchone()
        if paciente is None:
            raise HTTPException(status_code=404, detail="Paciente no encontrado")

        doctor = conexion.execute(
            "SELECT id FROM doctores WHERE id = ?", (datos.doctor_id,)
        ).fetchone()
        if doctor is None:
            raise HTTPException(status_code=404, detail="Doctor no encontrado")

        try:
            cursor = conexion.execute(
                """
                INSERT INTO citas (paciente_id, doctor_id, fecha, hora, motivo, estado)
                VALUES (?, ?, ?, ?, ?, 'pendiente')
                """,
                (datos.paciente_id, datos.doctor_id, datos.fecha, datos.hora, datos.motivo),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409, detail="Ese doctor ya tiene una cita agendada en esa fecha y hora"
            )

        return _fila_a_cita(conexion, cursor.lastrowid)


@app.get("/citas", response_model=list[CitaRespuesta])
def listar_citas(usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        filas = conexion.execute("SELECT id FROM citas ORDER BY id").fetchall()
        return [_fila_a_cita(conexion, fila["id"]) for fila in filas]


@app.get("/citas/{cita_id}", response_model=CitaRespuesta)
def obtener_cita(cita_id: int, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        existe = conexion.execute("SELECT id FROM citas WHERE id = ?", (cita_id,)).fetchone()
        if existe is None:
            raise HTTPException(status_code=404, detail="Cita no encontrada")
        return _fila_a_cita(conexion, cita_id)


@app.delete("/citas/{cita_id}")
def cancelar_cita(cita_id: int, usuario=Depends(obtener_usuario_actual)):
    """En vez de borrar la fila, la marcamos como 'cancelada'. Solo se puede
    cancelar una cita que todavía está pendiente (una cita ya atendida tiene
    una consulta asociada y no debe cancelarse)."""
    with obtener_conexion() as conexion:
        cursor = conexion.execute(
            "UPDATE citas SET estado = 'cancelada' WHERE id = ? AND estado = 'pendiente'",
            (cita_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404, detail="Cita no encontrada o ya no está pendiente"
            )
    return {"mensaje": "Cita cancelada correctamente"}


# =============================================================================
# PASO 10: Consultas -> se registran cuando un doctor atiende una cita
# =============================================================================

def _fila_a_consulta(conexion, consulta_id: int) -> dict:
    fila = conexion.execute(
        """
        SELECT co.id, co.cita_id, co.paciente_id, p.nombre AS paciente_nombre,
               co.doctor_id, d.nombre AS doctor_nombre,
               co.diagnostico, co.tratamiento, co.notas, co.fecha_consulta
        FROM consultas co
        JOIN pacientes p ON p.id = co.paciente_id
        JOIN doctores d ON d.id = co.doctor_id
        WHERE co.id = ?
        """,
        (consulta_id,),
    ).fetchone()
    return dict(fila)


@app.post(
    "/consultas",
    response_model=ConsultaRespuesta,
    status_code=status.HTTP_201_CREATED,
)
def crear_consulta(datos: ConsultaCrear, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        cita = conexion.execute(
            "SELECT * FROM citas WHERE id = ?", (datos.cita_id,)
        ).fetchone()
        if cita is None:
            raise HTTPException(status_code=404, detail="Cita no encontrada")
        if cita["estado"] != "pendiente":
            raise HTTPException(
                status_code=409, detail="Esa cita ya fue atendida o está cancelada"
            )

        cursor = conexion.execute(
            """
            INSERT INTO consultas
                (cita_id, paciente_id, doctor_id, diagnostico, tratamiento, notas, fecha_consulta)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cita["id"],
                cita["paciente_id"],
                cita["doctor_id"],
                datos.diagnostico,
                datos.tratamiento,
                datos.notas,
                datetime.utcnow().isoformat(),
            ),
        )
        conexion.execute(
            "UPDATE citas SET estado = 'atendida' WHERE id = ?", (cita["id"],)
        )

        return _fila_a_consulta(conexion, cursor.lastrowid)


@app.get("/consultas", response_model=list[ConsultaRespuesta])
def listar_consultas(usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        filas = conexion.execute("SELECT id FROM consultas ORDER BY id").fetchall()
        return [_fila_a_consulta(conexion, fila["id"]) for fila in filas]


@app.get("/consultas/{consulta_id}", response_model=ConsultaRespuesta)
def obtener_consulta(consulta_id: int, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        existe = conexion.execute(
            "SELECT id FROM consultas WHERE id = ?", (consulta_id,)
        ).fetchone()
        if existe is None:
            raise HTTPException(status_code=404, detail="Consulta no encontrada")
        return _fila_a_consulta(conexion, consulta_id)


# =============================================================================
# PASO 11: CRUD de medicamentos (catálogo con stock)
# =============================================================================

@app.post(
    "/medicamentos",
    response_model=MedicamentoRespuesta,
    status_code=status.HTTP_201_CREATED,
)
def crear_medicamento(medicamento: MedicamentoCrear, usuario=Depends(obtener_usuario_actual)):
    try:
        with obtener_conexion() as conexion:
            cursor = conexion.execute(
                "INSERT INTO medicamentos (nombre, presentacion, stock) VALUES (?, ?, ?)",
                (medicamento.nombre, medicamento.presentacion, medicamento.stock),
            )
            fila = conexion.execute(
                "SELECT * FROM medicamentos WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(fila)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ya existe un medicamento con ese nombre")


@app.get("/medicamentos", response_model=list[MedicamentoRespuesta])
def listar_medicamentos(usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        filas = conexion.execute("SELECT * FROM medicamentos ORDER BY id").fetchall()
        return [dict(fila) for fila in filas]


@app.get("/medicamentos/{medicamento_id}", response_model=MedicamentoRespuesta)
def obtener_medicamento(medicamento_id: int, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        fila = conexion.execute(
            "SELECT * FROM medicamentos WHERE id = ?", (medicamento_id,)
        ).fetchone()
    if fila is None:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado")
    return dict(fila)


@app.put("/medicamentos/{medicamento_id}", response_model=MedicamentoRespuesta)
def actualizar_medicamento(
    medicamento_id: int, medicamento: MedicamentoCrear, usuario=Depends(obtener_usuario_actual)
):
    try:
        with obtener_conexion() as conexion:
            cursor = conexion.execute(
                "UPDATE medicamentos SET nombre = ?, presentacion = ?, stock = ? WHERE id = ?",
                (medicamento.nombre, medicamento.presentacion, medicamento.stock, medicamento_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Medicamento no encontrado")
            fila = conexion.execute(
                "SELECT * FROM medicamentos WHERE id = ?", (medicamento_id,)
            ).fetchone()
            return dict(fila)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ya existe otro medicamento con ese nombre")


@app.delete("/medicamentos/{medicamento_id}")
def eliminar_medicamento(medicamento_id: int, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        en_uso = conexion.execute(
            "SELECT id FROM recetas WHERE medicamento_id = ?", (medicamento_id,)
        ).fetchone()
        if en_uso:
            raise HTTPException(
                status_code=409,
                detail="No se puede eliminar: el medicamento tiene recetas registradas",
            )
        cursor = conexion.execute("DELETE FROM medicamentos WHERE id = ?", (medicamento_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Medicamento no encontrado")
    return {"mensaje": "Medicamento eliminado correctamente"}


# =============================================================================
# PASO 12: Recetas -> une una consulta con los medicamentos recetados
# =============================================================================

def _fila_a_receta(conexion, receta_id: int) -> dict:
    fila = conexion.execute(
        """
        SELECT r.id, r.consulta_id, r.medicamento_id, m.nombre AS medicamento_nombre,
               r.dosis, r.cantidad, r.indicaciones
        FROM recetas r
        JOIN medicamentos m ON m.id = r.medicamento_id
        WHERE r.id = ?
        """,
        (receta_id,),
    ).fetchone()
    return dict(fila)


@app.post("/recetas", response_model=RecetaRespuesta, status_code=status.HTTP_201_CREATED)
def crear_receta(datos: RecetaCrear, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        consulta = conexion.execute(
            "SELECT id FROM consultas WHERE id = ?", (datos.consulta_id,)
        ).fetchone()
        if consulta is None:
            raise HTTPException(status_code=404, detail="Consulta no encontrada")

        medicamento = conexion.execute(
            "SELECT * FROM medicamentos WHERE id = ?", (datos.medicamento_id,)
        ).fetchone()
        if medicamento is None:
            raise HTTPException(status_code=404, detail="Medicamento no encontrado")

        if medicamento["stock"] < datos.cantidad:
            raise HTTPException(
                status_code=409,
                detail=f"No hay suficiente stock de {medicamento['nombre']} (disponible: {medicamento['stock']})",
            )

        cursor = conexion.execute(
            """
            INSERT INTO recetas (consulta_id, medicamento_id, dosis, cantidad, indicaciones)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datos.consulta_id,
                datos.medicamento_id,
                datos.dosis,
                datos.cantidad,
                datos.indicaciones,
            ),
        )
        conexion.execute(
            "UPDATE medicamentos SET stock = stock - ? WHERE id = ?",
            (datos.cantidad, datos.medicamento_id),
        )

        return _fila_a_receta(conexion, cursor.lastrowid)


@app.get("/recetas", response_model=list[RecetaRespuesta])
def listar_recetas(usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        filas = conexion.execute("SELECT id FROM recetas ORDER BY id").fetchall()
        return [_fila_a_receta(conexion, fila["id"]) for fila in filas]


@app.get("/recetas/{receta_id}", response_model=RecetaRespuesta)
def obtener_receta(receta_id: int, usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        existe = conexion.execute("SELECT id FROM recetas WHERE id = ?", (receta_id,)).fetchone()
        if existe is None:
            raise HTTPException(status_code=404, detail="Receta no encontrada")
        return _fila_a_receta(conexion, receta_id)


# =============================================================================
# PASO 13: Endpoint de resumen para el dashboard (lo consume dashboard.html)
# =============================================================================

@app.get("/dashboard/resumen", response_model=ResumenDashboard)
def resumen_dashboard(usuario=Depends(obtener_usuario_actual)):
    with obtener_conexion() as conexion:
        total_pacientes = conexion.execute(
            "SELECT COUNT(*) AS total FROM pacientes"
        ).fetchone()["total"]
        total_doctores = conexion.execute(
            "SELECT COUNT(*) AS total FROM doctores"
        ).fetchone()["total"]
        citas_pendientes = conexion.execute(
            "SELECT COUNT(*) AS total FROM citas WHERE estado = 'pendiente'"
        ).fetchone()["total"]
        total_consultas = conexion.execute(
            "SELECT COUNT(*) AS total FROM consultas"
        ).fetchone()["total"]
    return {
        "total_pacientes": total_pacientes,
        "total_doctores": total_doctores,
        "citas_pendientes": citas_pendientes,
        "total_consultas": total_consultas,
    }


# =============================================================================
# PASO 14: Páginas HTML -> aquí es donde el backend "se conecta" al frontend
# =============================================================================

@app.get("/login")
def pagina_login(request: Request):
    return plantillas.TemplateResponse(request, "login.html")


@app.get("/dashboard")
def pagina_dashboard(request: Request):
    token = request.cookies.get("token")
    usuario = obtener_usuario_por_token(token) if token else None
    if usuario is None:
        return RedirectResponse(url="/login")
    return plantillas.TemplateResponse(
        request, "dashboard.html", {"nombre_usuario": usuario["nombre_usuario"]}
    )
