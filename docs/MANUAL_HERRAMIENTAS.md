# Manual: crear herramientas para el agente

> Una **herramienta** es una acción que el agente de IA puede ejecutar durante una
> conversación: una llamada HTTP a una API (consultar una factura, crear un
> ticket, consultar un stock, el clima, un CRM…). El modelo decide **cuándo**
> llamarla a partir de su **descripción**, y tú defines **a dónde** y **cómo** se
> llama. No hay que programar: se configuran desde la web y se guardan en
> `data/tools.json`, que comparten el **chat** y las **llamadas telefónicas**.

Interfaz: <http://localhost:8000> → pestaña **Herramientas**.

---

## 1. Anatomía de una herramienta

| Campo | Para qué sirve |
|---|---|
| **Nombre** | Identificador (sin espacios), p. ej. `consultar_factura`. Es el nombre que "ve" el modelo. |
| **Descripción** | La pista que usa el modelo para decidir si la llama. **Es lo más importante.** Clara y concreta. |
| **Método** | `GET`, `POST`, `PUT`, `DELETE`, `PATCH`. |
| **URL** | El endpoint. Puede ser una **URL externa completa** (`https://…`) o usar `{base}`. Admite `{parámetros}` de ruta. |
| **Autenticación** | `Ninguna` o `Bearer` (usa la clave global `TOOLS_API_KEY` del `.env`). |
| **Cabeceras** | Cabeceras propias de esta herramienta (p. ej. la API key de un servicio externo: `X-API-Key: …`). |
| **Parámetros** | Los datos que el modelo debe rellenar. Cada uno tiene nombre, tipo, ubicación y si es obligatorio. |

### Parámetros: la **ubicación** (location)

- **path** — va dentro de la URL. Debes escribir `{nombre}` en la URL.
  Ej.: URL `https://api.ej.com/facturas/{numero}` + parámetro `numero` (path).
- **query** — va en la query string (`?clave=valor`). Para filtros/búsquedas.
- **body** — va en el cuerpo JSON. Típico en `POST`/`PUT`.

### Marcadores en la URL

- `{base}` → se reemplaza por `TOOLS_BASE_URL` (del `.env`). Útil cuando todas tus
  herramientas apuntan al mismo backend. Si `TOOLS_BASE_URL` está vacío y la URL
  usa `{base}`, la herramienta responde **SIMULADO** (para probar sin backend).
- `{nombre}` → se reemplaza por el valor del parámetro *path* llamado `nombre`.

---

## 2. Consultar un servicio EXTERNO (fuera de este equipo)

Tres casos según dónde viva el servicio:

| El servicio está en… | Qué poner en la URL |
|---|---|
| Internet (API pública/SaaS) | La URL completa: `https://api.proveedor.com/v1/...` |
| **El propio equipo** (otro puerto del host) | `http://host.docker.internal:PUERTO/...` (¡no `localhost`!) |
| Otra máquina de la LAN | `http://IP_DE_LA_MAQUINA:PUERTO/...` |

> **Por qué no `localhost`:** la herramienta se ejecuta **dentro de un
> contenedor**; `localhost` ahí es el propio contenedor, no tu equipo. Para llegar
> al host usa `host.docker.internal`.

Credenciales de un servicio externo: normalmente una **cabecera**. Añádela en
*Cabeceras* (p. ej. `Authorization: Bearer sk-…` o `X-API-Key: …`). La vista
previa enmascara los valores que parezcan secretos.

---

## 3. Ejemplo paso a paso (API externa real)

Vamos a crear una herramienta que consulta el estado de un pedido en una API
externa ficticia `https://api.mitienda.com`.

1. Pestaña **Herramientas** → **+ Nueva**.
2. Rellena:
   - **Nombre:** `estado_pedido`
   - **Descripción:** `Consulta el estado y la fecha de entrega de un pedido a partir de su número.`
   - **Método:** `GET`
   - **URL:** `https://api.mitienda.com/v1/pedidos/{numero}`
   - **Autenticación:** `Ninguna`
   - **Cabeceras:** `+ cabecera` → `X-API-Key` = `tu_clave_real`
   - **Parámetros:** `+ parámetro`
     - nombre `numero`, tipo `string`, ubicación `path`, **req** ✓,
       descripción `Número del pedido`
3. Mira la **Vista previa**: debe mostrar
   `GET https://api.mitienda.com/v1/pedidos/:numero` y la cabecera `X-API-Key: ••••••`.
4. En **Probar**, escribe un `numero` de ejemplo y pulsa **Ejecutar**. Verás el
   resultado con su estado: **✓ Respuesta**, **◐ Simulado** o **✕ Error**.
5. **Guardar**.

Ejemplo con `POST` y body (crear un ticket):

- **Método:** `POST` · **URL:** `https://api.mitienda.com/v1/tickets`
- **Parámetros:** `asunto` (string, body, req), `descripcion` (string, body)
- Vista previa mostrará `body: {"asunto":"…","descripcion":"…"}`.

---

## 4. Probar, estados y vista previa

- **Vista previa:** muestra exactamente la petición que se enviará (método, URL ya
  resuelta con tus valores, cabeceras y body). Úsala para detectar errores antes
  de llamar.
- **Resultado de la prueba:**
  - **✓ Respuesta** — la API respondió (se muestra el JSON).
  - **◐ Simulado** — la URL usa `{base}` y `TOOLS_BASE_URL` está vacío: no se llamó
    a nada real. Pon una URL completa o configura `TOOLS_BASE_URL`.
  - **✕ Error** — hubo un fallo (URL inalcanzable, 4xx/5xx, timeout…). El detalle
    aparece en el JSON.
- **Avisos:** si la URL usa `{algo}` sin un parámetro con ese nombre (o al revés),
  la UI te lo señala antes de guardar.

---

## 5. Escribir buenas descripciones (para que el modelo acierte)

La **descripción** es lo que el modelo lee para decidir. Reglas:

- Di **qué hace** y **cuándo usarla**, en una frase. Ej.: *"Consulta el saldo
  pendiente de un cliente por su cédula. Úsala cuando pregunten por deudas o pagos."*
- Describe bien cada **parámetro** (el modelo rellena esos campos).
- No crees herramientas que se solapen demasiado (el modelo dudará cuál usar).
- Si un modelo pequeño **invoca de más** (llama a la herramienta cuando no toca),
  usa un modelo con mejor *tool calling* (en este proyecto, `qwen3:8b`).

---

## 6. Dónde y cómo se aplican los cambios

- Todo se guarda en **`data/tools.json`**, compartido por la UI, el chat y el
  **agente telefónico**. Un cambio aplica **en caliente** (no hay que reiniciar):
  los esquemas se leen en cada llamada.
- **Exportar / Importar** (botones de la cabecera): descargan o cargan el
  `tools.json` completo. Útil para **llevar tus herramientas a otro equipo** (p.
  ej. de Windows a la Mac): Exportar aquí → Importar allá.

---

## 7. Seguridad de las credenciales

- Las cabeceras y la `TOOLS_API_KEY` se guardan **en claro** en archivos del
  proyecto (`data/tools.json` y `.env`). Trátalos como secretos: no los subas a un
  repositorio público (el `.env` ya está en `.gitignore`).
- La vista previa enmascara valores que parezcan `key`/`token`/`secret`/`auth`,
  pero el valor real sí se envía al servicio que configures.

---

## 8. Referencia rápida de errores

| Resultado | Probable causa | Qué hacer |
|---|---|---|
| `◐ Simulado` | `{base}` sin `TOOLS_BASE_URL` | URL completa o define `TOOLS_BASE_URL` |
| `✕ Error` + *Connection refused* | `localhost` dentro del contenedor, o puerto cerrado | Usa `host.docker.internal`/IP de LAN; abre el puerto |
| `✕ Error` + `401/403` | Falta/!= credencial | Revisa la cabecera o el Bearer |
| `✕ Error` + `404` | Ruta/`{param}` mal | Revisa la URL y los parámetros *path* |
| El modelo no la llama | Descripción floja | Mejora la descripción (§5) |
