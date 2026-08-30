# API de Clínica

Proyecto final para **Programación II**: una API con **login**, **7 tablas
relacionadas** en SQLite y un **dashboard** (panel web) que consume la propia
API. Sigue la misma estructura que la práctica de "API de Matrícula" vista en
clase, aplicada a un caso distinto: la gestión de citas y consultas de una
clínica.

## 1. Estructura del proyecto

```
clinica/
├── main.py                                 # toda la API (léalo de arriba a abajo, por PASOS)
├── requirements.txt
├── templates/
│   ├── login.html
│   └── dashboard.html
├── static/
│   ├── estilos.css
│   └── app.js                              # el "frontend": llama a la API con fetch()
└── API_Clinica.postman_collection.json
```

## 2. Preparar el proyecto

### Windows

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Linux o macOS

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. Ejecutar la API

```bash
uvicorn main:app --reload
```

- API: `http://127.0.0.1:8000`
- Documentación automática (Swagger): `http://127.0.0.1:8000/docs`
- Panel de login: `http://127.0.0.1:8000/login`
- Dashboard (requiere iniciar sesión primero): `http://127.0.0.1:8000/dashboard`

Al iniciar, `main.py` crea automáticamente el archivo `clinica.db`, sus 7
tablas, y un usuario de prueba:

| Usuario | Contraseña |
|---|---|
| `admin` | `admin123` |

**Cambie esta contraseña antes de la defensa** (con el endpoint
`POST /auth/usuarios` puede crear otros usuarios).

## 4. Las 7 tablas

| Tabla | Para qué sirve |
|---|---|
| `usuarios` | Cuentas que pueden iniciar sesión (login) en la API/panel |
| `pacientes` | Personas que se atienden en la clínica |
| `doctores` | Médicos que atienden citas, cada uno con su especialidad |
| `citas` | Tabla puente: agenda un `paciente_id` con un `doctor_id`, fecha y hora |
| `consultas` | Diagnóstico y tratamiento registrados al atender una cita |
| `medicamentos` | Catálogo de medicamentos disponibles, con su stock |
| `recetas` | Tabla puente: relaciona una `consulta_id` con los `medicamento_id` recetados |

`citas` y `recetas` son el corazón relacional del proyecto: cada cita une un
paciente con un doctor (y valida que el doctor no tenga dos citas a la misma
fecha/hora); cada receta une una consulta con un medicamento (y descuenta el
stock disponible).

## 5. Flujo completo del negocio

1. Se registra un **paciente** y un **doctor**.
2. Se agenda una **cita** entre ambos (queda en estado `pendiente`).
3. El doctor atiende la cita y se registra una **consulta** (diagnóstico y
   tratamiento). La cita pasa automáticamente a `atendida`.
4. Desde esa consulta se pueden **recetar medicamentos** (una o varias
   filas en `recetas`); el stock del medicamento se descuenta.

Una cita también se puede **cancelar** mientras esté `pendiente`.

## 6. Cómo funciona el login (sin librerías externas de JWT)

1. `POST /auth/login` recibe `nombre_usuario` y `contrasena`.
2. La API compara la contraseña con el **hash** guardado (nunca se guarda la
   contraseña real; se usa `hashlib.pbkdf2_hmac` con un `salt` por usuario).
3. Si es correcta, se genera un **token** aleatorio (`secrets.token_hex`), se
   guarda en la tabla `usuarios` con una fecha de expiración (2 horas), y se
   devuelve en el JSON de respuesta **y** en una cookie llamada `token`.
4. Las rutas protegidas usan `Depends(obtener_usuario_actual)`, que acepta el
   token de dos formas:
   - Encabezado `Authorization: Bearer <token>` → así se prueba desde Postman.
   - Cookie `token` → así funciona automáticamente el dashboard en el navegador.
5. `POST /auth/logout` borra el token (cierra la sesión).

## 7. Probar en Postman

1. Importe `API_Clinica.postman_collection.json`.
2. Ejecute primero **Login**. Postman guarda el `token` de la respuesta en una
   variable de colección automáticamente (revise la pestaña *Tests* de esa
   petición); las demás peticiones ya usan `Authorization: Bearer {{token}}`.
3. Pruebe en orden: Login → Registrar paciente → Registrar doctor → Agendar
   cita → Registrar consulta → Registrar medicamento → Recetar → Listar
   recetas → Resumen del dashboard.

También puede usar `/docs` (Swagger) y el botón **Authorize** para pegar el
token.

## 8. Probar el dashboard (frontend)

1. Con la API corriendo, abra `http://127.0.0.1:8000/login` en el navegador.
2. Inicie sesión con `admin` / `admin123`.
3. Lo redirige a `/dashboard`, donde puede:
   - Ver el resumen (pacientes, doctores, citas pendientes, consultas).
   - Agendar citas y cancelarlas.
   - Registrar consultas a partir de una cita pendiente.
   - Recetar medicamentos desde una consulta.
   - Registrar pacientes, doctores y medicamentos.

Todo lo que hace el dashboard son llamadas `fetch()` (en `static/app.js`) a
los mismos endpoints que se prueban en Postman: **el HTML/JS no sabe nada de
SQLite, solo habla con la API**.

## 9. Endpoints principales

| Operación | Método | URL | Protegido |
|---|---|---|---|
| Verificar API | GET | `/` | No |
| Iniciar sesión | POST | `/auth/login` | No |
| Cerrar sesión | POST | `/auth/logout` | Sí |
| Usuario actual | GET | `/auth/yo` | Sí |
| Crear usuario | POST | `/auth/usuarios` | Sí |
| CRUD pacientes | GET/POST/PUT/DELETE | `/pacientes` | Sí |
| CRUD doctores | GET/POST/PUT/DELETE | `/doctores` | Sí |
| Agendar / listar citas | GET/POST | `/citas` | Sí |
| Cancelar cita | DELETE | `/citas/{id}` | Sí |
| Registrar / listar consultas | GET/POST | `/consultas` | Sí |
| CRUD medicamentos | GET/POST/PUT/DELETE | `/medicamentos` | Sí |
| Recetar / listar recetas | GET/POST | `/recetas` | Sí |
| Resumen dashboard | GET | `/dashboard/resumen` | Sí |

## Conceptos que se practican

- Relaciones entre tablas (llaves foráneas, tablas puente `citas` y `recetas`).
- Autenticación con usuario/contraseña y hash con `salt`.
- Sesiones por token, enviadas por encabezado o por cookie.
- Dependencias de FastAPI (`Depends`) para proteger rutas.
- Reglas de negocio en el backend (evitar doble cita, controlar stock, no
  borrar registros en uso).
- Plantillas HTML con Jinja2 y archivos estáticos (CSS/JS).
- Consumo de una API propia desde JavaScript (`fetch`), es decir, backend → frontend.
- Códigos HTTP: 200, 201, 401, 404, 409 y 422.

## 10. Plan sugerido para las dos semanas

| Semana | Entregable | Qué mostrar |
|---|---|---|
| 1 (primer avance) | Backend + SQLite funcionando | Las 7 tablas creadas, CRUD probado en Postman con la colección importada, `/docs` funcionando |
| 2 (defensa) | Proyecto completo | Login funcionando, dashboard con las citas/consultas/recetas de ejemplo, explicar el flujo cita → consulta → receta y las reglas de negocio (por qué no se puede doble-agendar un doctor, por qué se descuenta el stock, etc.) |

## Reto adicional (opcional, para sumar puntos)

- Agregar un endpoint `GET /pacientes/{id}/historial` que liste todas las
  consultas de un paciente específico.
- Agregar en el dashboard un filtro para ver solo las citas `cancelada`.
- Validar que la `fecha` de una cita no sea anterior a hoy.
