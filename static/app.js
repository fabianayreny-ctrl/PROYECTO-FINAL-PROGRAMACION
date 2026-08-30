// Funciones compartidas entre login.html y dashboard.html.
// Todo el "frontend" de esta práctica es JavaScript sencillo (fetch) que
// consume los mismos endpoints que se prueban en Postman.

async function apiFetch(url, opciones = {}) {
  const respuesta = await fetch(url, {
    credentials: "same-origin", // envía automáticamente la cookie de sesión
    headers: { "Content-Type": "application/json" },
    ...opciones,
  });

  if (respuesta.status === 401) {
    window.location.href = "/login";
    throw new Error("Sesión expirada");
  }

  return respuesta;
}

function mostrarError(elemento, texto) {
  elemento.textContent = texto;
  elemento.hidden = false;
}

// -----------------------------------------------------------------------
// Cerrar sesión (presente solo en dashboard.html)
// -----------------------------------------------------------------------
const botonSalir = document.getElementById("boton-salir");
if (botonSalir) {
  botonSalir.addEventListener("click", async () => {
    await apiFetch("/auth/logout", { method: "POST" });
    window.location.href = "/login";
  });
}

// -----------------------------------------------------------------------
// Todo lo que sigue solo corre dentro del dashboard
// -----------------------------------------------------------------------
const tarjetasResumen = document.getElementById("tarjetas-resumen");

if (tarjetasResumen) {
  const selectCitaPaciente = document.getElementById("cita-paciente");
  const selectCitaDoctor = document.getElementById("cita-doctor");
  const selectConsultaCita = document.getElementById("consulta-cita");
  const selectRecetaConsulta = document.getElementById("receta-consulta");
  const selectRecetaMedicamento = document.getElementById("receta-medicamento");

  const cuerpoTablaCitas = document.getElementById("cuerpo-tabla-citas");
  const cuerpoTablaConsultas = document.getElementById("cuerpo-tabla-consultas");
  const cuerpoTablaRecetas = document.getElementById("cuerpo-tabla-recetas");
  const cuerpoTablaMedicamentos = document.getElementById("cuerpo-tabla-medicamentos");

  async function cargarResumen() {
    const respuesta = await apiFetch("/dashboard/resumen");
    const datos = await respuesta.json();
    document.getElementById("dato-pacientes").textContent = datos.total_pacientes;
    document.getElementById("dato-doctores").textContent = datos.total_doctores;
    document.getElementById("dato-citas-pendientes").textContent = datos.citas_pendientes;
    document.getElementById("dato-consultas").textContent = datos.total_consultas;
  }

  async function cargarPacientesEnSelect() {
    const respuesta = await apiFetch("/pacientes");
    const pacientes = await respuesta.json();
    selectCitaPaciente.innerHTML = '<option value="">Seleccione un paciente</option>';
    pacientes.forEach((paciente) => {
      const opcion = document.createElement("option");
      opcion.value = paciente.id;
      opcion.textContent = `${paciente.nombre} (${paciente.identidad})`;
      selectCitaPaciente.appendChild(opcion);
    });
  }

  async function cargarDoctoresEnSelect() {
    const respuesta = await apiFetch("/doctores");
    const doctores = await respuesta.json();
    selectCitaDoctor.innerHTML = '<option value="">Seleccione un doctor</option>';
    doctores.forEach((doctor) => {
      const opcion = document.createElement("option");
      opcion.value = doctor.id;
      opcion.textContent = `${doctor.nombre} - ${doctor.especialidad}`;
      selectCitaDoctor.appendChild(opcion);
    });
  }

  async function cargarCitasPendientesEnSelect() {
    const respuesta = await apiFetch("/citas");
    const citas = await respuesta.json();
    const pendientes = citas.filter((cita) => cita.estado === "pendiente");
    selectConsultaCita.innerHTML = '<option value="">Seleccione una cita pendiente</option>';
    pendientes.forEach((cita) => {
      const opcion = document.createElement("option");
      opcion.value = cita.id;
      opcion.textContent = `${cita.paciente_nombre} con ${cita.doctor_nombre} (${cita.fecha} ${cita.hora})`;
      selectConsultaCita.appendChild(opcion);
    });
  }

  async function cargarConsultasEnSelect() {
    const respuesta = await apiFetch("/consultas");
    const consultas = await respuesta.json();
    selectRecetaConsulta.innerHTML = '<option value="">Seleccione una consulta</option>';
    consultas.forEach((consulta) => {
      const opcion = document.createElement("option");
      opcion.value = consulta.id;
      opcion.textContent = `#${consulta.id} - ${consulta.paciente_nombre} (${consulta.diagnostico})`;
      selectRecetaConsulta.appendChild(opcion);
    });
  }

  async function cargarMedicamentosEnSelect() {
    const respuesta = await apiFetch("/medicamentos");
    const medicamentos = await respuesta.json();
    selectRecetaMedicamento.innerHTML = '<option value="">Seleccione un medicamento</option>';
    medicamentos.forEach((medicamento) => {
      const opcion = document.createElement("option");
      opcion.value = medicamento.id;
      opcion.textContent = `${medicamento.nombre} (stock: ${medicamento.stock})`;
      selectRecetaMedicamento.appendChild(opcion);
    });
  }

  async function cargarTablaCitas() {
    const respuesta = await apiFetch("/citas");
    const citas = await respuesta.json();

    if (citas.length === 0) {
      cuerpoTablaCitas.innerHTML = '<tr><td colspan="7">Todavía no hay citas</td></tr>';
      return;
    }

    cuerpoTablaCitas.innerHTML = "";
    citas.forEach((cita) => {
      const fila = document.createElement("tr");
      fila.innerHTML = `
        <td>${cita.paciente_nombre}</td>
        <td>${cita.doctor_nombre}</td>
        <td>${cita.fecha}</td>
        <td>${cita.hora}</td>
        <td>${cita.motivo}</td>
        <td><span class="etiqueta-estado etiqueta-${cita.estado}">${cita.estado}</span></td>
        <td></td>
      `;

      if (cita.estado === "pendiente") {
        const botonCancelar = document.createElement("button");
        botonCancelar.textContent = "Cancelar";
        botonCancelar.className = "boton-pequeno";
        botonCancelar.addEventListener("click", async () => {
          await apiFetch(`/citas/${cita.id}`, { method: "DELETE" });
          await actualizarTodo();
        });
        fila.lastElementChild.appendChild(botonCancelar);
      }

      cuerpoTablaCitas.appendChild(fila);
    });
  }

  async function cargarTablaConsultas() {
    const respuesta = await apiFetch("/consultas");
    const consultas = await respuesta.json();

    if (consultas.length === 0) {
      cuerpoTablaConsultas.innerHTML = '<tr><td colspan="5">Todavía no hay consultas</td></tr>';
      return;
    }

    cuerpoTablaConsultas.innerHTML = "";
    consultas.forEach((consulta) => {
      const fila = document.createElement("tr");
      const fecha = new Date(consulta.fecha_consulta).toLocaleString();
      fila.innerHTML = `
        <td>${consulta.paciente_nombre}</td>
        <td>${consulta.doctor_nombre}</td>
        <td>${consulta.diagnostico}</td>
        <td>${consulta.tratamiento}</td>
        <td>${fecha}</td>
      `;
      cuerpoTablaConsultas.appendChild(fila);
    });
  }

  async function cargarTablaRecetas() {
    const respuesta = await apiFetch("/recetas");
    const recetas = await respuesta.json();

    if (recetas.length === 0) {
      cuerpoTablaRecetas.innerHTML = '<tr><td colspan="5">Todavía no hay recetas</td></tr>';
      return;
    }

    cuerpoTablaRecetas.innerHTML = "";
    recetas.forEach((receta) => {
      const fila = document.createElement("tr");
      fila.innerHTML = `
        <td>#${receta.consulta_id}</td>
        <td>${receta.medicamento_nombre}</td>
        <td>${receta.dosis}</td>
        <td>${receta.cantidad}</td>
        <td>${receta.indicaciones || "-"}</td>
      `;
      cuerpoTablaRecetas.appendChild(fila);
    });
  }

  async function cargarTablaMedicamentos() {
    const respuesta = await apiFetch("/medicamentos");
    const medicamentos = await respuesta.json();

    if (medicamentos.length === 0) {
      cuerpoTablaMedicamentos.innerHTML = '<tr><td colspan="3">Todavía no hay medicamentos</td></tr>';
      return;
    }

    cuerpoTablaMedicamentos.innerHTML = "";
    medicamentos.forEach((medicamento) => {
      const fila = document.createElement("tr");
      fila.innerHTML = `
        <td>${medicamento.nombre}</td>
        <td>${medicamento.presentacion}</td>
        <td>${medicamento.stock}</td>
      `;
      cuerpoTablaMedicamentos.appendChild(fila);
    });
  }

  async function actualizarTodo() {
    await Promise.all([
      cargarResumen(),
      cargarPacientesEnSelect(),
      cargarDoctoresEnSelect(),
      cargarCitasPendientesEnSelect(),
      cargarConsultasEnSelect(),
      cargarMedicamentosEnSelect(),
      cargarTablaCitas(),
      cargarTablaConsultas(),
      cargarTablaRecetas(),
      cargarTablaMedicamentos(),
    ]);
  }

  // Formulario: nueva cita
  document.getElementById("formulario-cita").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const mensaje = document.getElementById("mensaje-cita");
    mensaje.hidden = true;

    const cuerpo = {
      paciente_id: Number(selectCitaPaciente.value),
      doctor_id: Number(selectCitaDoctor.value),
      fecha: document.getElementById("cita-fecha").value,
      hora: document.getElementById("cita-hora").value,
      motivo: document.getElementById("cita-motivo").value,
    };

    const respuesta = await apiFetch("/citas", {
      method: "POST",
      body: JSON.stringify(cuerpo),
    });

    if (!respuesta.ok) {
      const error = await respuesta.json();
      mostrarError(mensaje, error.detail || "No se pudo agendar la cita");
      return;
    }

    evento.target.reset();
    await actualizarTodo();
  });

  // Formulario: nueva consulta
  document.getElementById("formulario-consulta").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const mensaje = document.getElementById("mensaje-consulta");
    mensaje.hidden = true;

    const notas = document.getElementById("consulta-notas").value;
    const cuerpo = {
      cita_id: Number(selectConsultaCita.value),
      diagnostico: document.getElementById("consulta-diagnostico").value,
      tratamiento: document.getElementById("consulta-tratamiento").value,
      notas: notas ? notas : null,
    };

    const respuesta = await apiFetch("/consultas", {
      method: "POST",
      body: JSON.stringify(cuerpo),
    });

    if (!respuesta.ok) {
      const error = await respuesta.json();
      mostrarError(mensaje, error.detail || "No se pudo registrar la consulta");
      return;
    }

    evento.target.reset();
    await actualizarTodo();
  });

  // Formulario: nueva receta
  document.getElementById("formulario-receta").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const mensaje = document.getElementById("mensaje-receta");
    mensaje.hidden = true;

    const indicaciones = document.getElementById("receta-indicaciones").value;
    const cuerpo = {
      consulta_id: Number(selectRecetaConsulta.value),
      medicamento_id: Number(selectRecetaMedicamento.value),
      dosis: document.getElementById("receta-dosis").value,
      cantidad: Number(document.getElementById("receta-cantidad").value),
      indicaciones: indicaciones ? indicaciones : null,
    };

    const respuesta = await apiFetch("/recetas", {
      method: "POST",
      body: JSON.stringify(cuerpo),
    });

    if (!respuesta.ok) {
      const error = await respuesta.json();
      mostrarError(mensaje, error.detail || "No se pudo recetar el medicamento");
      return;
    }

    evento.target.reset();
    await actualizarTodo();
  });

  // Formulario: nuevo paciente
  document.getElementById("formulario-paciente").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const mensaje = document.getElementById("mensaje-paciente");
    mensaje.hidden = true;

    const cuerpo = {
      nombre: document.getElementById("p-nombre").value,
      identidad: document.getElementById("p-identidad").value,
      telefono: document.getElementById("p-telefono").value,
      correo: document.getElementById("p-correo").value,
      edad: Number(document.getElementById("p-edad").value),
    };

    const respuesta = await apiFetch("/pacientes", {
      method: "POST",
      body: JSON.stringify(cuerpo),
    });

    if (!respuesta.ok) {
      const error = await respuesta.json();
      mostrarError(mensaje, error.detail || "No se pudo registrar el paciente");
      return;
    }

    evento.target.reset();
    await actualizarTodo();
  });

  // Formulario: nuevo doctor
  document.getElementById("formulario-doctor").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const mensaje = document.getElementById("mensaje-doctor");
    mensaje.hidden = true;

    const cuerpo = {
      nombre: document.getElementById("d-nombre").value,
      colegiacion: document.getElementById("d-colegiacion").value,
      especialidad: document.getElementById("d-especialidad").value,
      telefono: document.getElementById("d-telefono").value,
      correo: document.getElementById("d-correo").value,
    };

    const respuesta = await apiFetch("/doctores", {
      method: "POST",
      body: JSON.stringify(cuerpo),
    });

    if (!respuesta.ok) {
      const error = await respuesta.json();
      mostrarError(mensaje, error.detail || "No se pudo registrar el doctor");
      return;
    }

    evento.target.reset();
    await actualizarTodo();
  });

  // Formulario: nuevo medicamento
  document.getElementById("formulario-medicamento").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const mensaje = document.getElementById("mensaje-medicamento");
    mensaje.hidden = true;

    const cuerpo = {
      nombre: document.getElementById("m-nombre").value,
      presentacion: document.getElementById("m-presentacion").value,
      stock: Number(document.getElementById("m-stock").value),
    };

    const respuesta = await apiFetch("/medicamentos", {
      method: "POST",
      body: JSON.stringify(cuerpo),
    });

    if (!respuesta.ok) {
      const error = await respuesta.json();
      mostrarError(mensaje, error.detail || "No se pudo registrar el medicamento");
      return;
    }

    evento.target.reset();
    await actualizarTodo();
  });

  actualizarTodo();
}
