# Dia operations MCP — versión 0.2 del fork

Este módulo expone operaciones reales de Dia mediante el SDK oficial MCP
1.30.0 y transporte local `stdio`. Cada edición materializa un documento con
los tipos, puntos de conexión y exportadores nativos de Dia. El servidor no
controla una ventana abierta del editor. La implementación actual usa GTK3;
la migración a GTK4 tiene un [plan independiente](../docs/modernization/gtk4-migration.md).

## Runtime discovery audit (2026-09-19)

The server now includes read-only `list_sheets` and `list_object_types` tools,
for 11 tools in total. They query the native worker's loaded sheets/factories,
paginate results, preserve human-readable labels and distinguish installed types
from those supported by MCP creation. The verified worker contains 38 sheets and
887 registered types; these counts are observations, not a fixed catalog.

See the [architecture](../docs/mcp-architecture.md),
[complete inventory](../docs/mcp-capabilities.md),
[tool reference](../docs/mcp-tools.md), [development](../docs/mcp-development.md)
and [progress](../docs/progress.md). The existing snapshot editing contract below
is preserved. MCP does not yet attach to an open GUI document or its undo history.

## Inicio reproducible en Ubuntu 26

Desde la raíz del fork, con Docker disponible:

```sh
task mcp:build
task mcp:test
task mcp:demo
```

La imagen compila Dia desde este checkout y ejecuta sus pruebas Meson. La
segunda orden prueba API, integración nativa y mensajes MCP reales. La tercera
genera `artifacts/workflow.dia`, `.svg` y `.png`; abrir `.dia` en Dia conserva
las figuras editables y conexiones. El ejemplo rechaza archivos existentes;
usar otro directorio o retirarlos conscientemente antes de repetirlo.

Si Task no está instalado, los comandos Docker equivalentes se encuentran en
[Taskfile.yml](../Taskfile.yml). La imagen base Ubuntu 26.04 y xpm-pixbuf están
fijados por digest/SHA. Python usa [uv.lock](uv.lock) y el
[export de dependencias con hashes](requirements.lock). APT usa los repositorios
Ubuntu vigentes: las versiones del sistema no constituyen un snapshot inmutable.
Ver [entorno y construcción](../build-aux/mcp/README.md) y
[evidencias](../docs/modernization/validation.md).

Para desarrollar sólo el contrato, sin compilar GTK:

```sh
task mcp:check
```

No confundir esas pruebas unitarias con las pruebas nativas. `pytest` omite
integración salvo que `DIA_MCP_NATIVE=1`; `task mcp:test` la activa explícitamente.
Para iterar Python sobre una imagen existente, montar `mcp` de sólo lectura y
establecer `PYTHONPATH=/work/src`; los cambios C exigen reconstruir Dia.

## Conectar un cliente MCP

Crear previamente el directorio de salida. Ejemplo de configuración genérica
MCP para este equipo (adaptar ruta y UID/GID en otro equipo):

```json
{
  "mcpServers": {
    "dia": {
      "command": "docker",
      "args": [
        "run", "--rm", "--init", "-i", "--network=none", "--user", "1000:1000",
        "-v", "/home/jc/Projects/dia/artifacts:/workspace",
        "dia-mcp:ubuntu26", "xvfb-run", "-a", "dia-mcp", "--workspace", "/workspace"
      ]
    }
  }
}
```

El servidor se ejecuta como el usuario indicado y sólo ese directorio del host
se monta para resultados. Las rutas devueltas son rutas **del contenedor**:
`/workspace/workflow.svg` corresponde a `artifacts/workflow.svg` en el host.
`--init` permite que Xvfb complete su arranque y recoge procesos terminados;
`-i` mantiene stdin abierto. No usar `-t`, porque una terminal altera `stdio`.
El runtime no necesita red. No hay instalación automática en la configuración
de ningún cliente ni servicio permanente.

Con una instalación nativa del fork y el paquete instalado en un venv:

```sh
xvfb-run -a dia-mcp --workspace /ruta/de/salida --dia-binary /opt/dia/bin/dia
```

El intérprete embebido de Dia carga un arranque dedicado; no necesita instalar
el SDK MCP dentro de PyDia. `import dia` desde el venv externo no es el mecanismo
de integración.

## Flujo mínimo

1. `get_capabilities` enumera tipos, puertos y límites.
2. `create_document(name="Flujo")` devuelve `document.id`.
3. `create_object(document_id=..., text="Inicio", x=1, y=1)` devuelve `object_id`.
4. Crear otro objeto con `x=8, y=1`.
5. `connect_objects(document_id=..., source=..., target=...)` crea una línea
   con flecha y extremos realmente conectados. `auto` elige puertos enfrentados.
6. `inspect_document` muestra IDs, revisión y geometría resuelta por Dia.
7. `export_diagram(document_id=..., filename="flujo.svg", format="svg")`.
   Repetir con `flujo.dia`/`dia` o `flujo.png`/`png`.
8. `close_document` libera el estado después de exportar.

`move_object` permite cambiar la distribución y recalcula las conexiones. Las
dimensiones y coordenadas usan centímetros; el ajuste de texto de Dia puede
ampliar la figura. Consultar los límites reales en `geometry`, no inferirlos
sólo de `width`/`height` solicitados.

La [API interna](../docs/modernization/api.md) permite el mismo flujo sin MCP.
[examples/workflow.py](examples/workflow.py) contiene un ejemplo ejecutable.

## Galería de ejemplos complejos

Con la imagen ya construida, `task mcp:showcase` genera esta galería mediante
la API pública `Operations`, sin añadir tipos ni saltarse sus límites:

| Archivo | Figuras | Conectores | Qué muestra |
| --- | ---: | ---: | --- |
| `01-servicios.dia` | 26 | 29 | Gateway, servicios, almacenes, eventos y consumidores |
| `02-pedidos.dia` | 26 | 31 | Decisiones, revisión manual, reintentos y excepciones |
| `03-malla-100.dia` | 100 | 200 | Malla con conexiones horizontales, verticales y diagonales; límite del MVP |

Los resultados quedan en `artifacts/showcase/`, con SVG, PNG, JSON del estado y
un manifiesto de tamaños, hashes y tiempos por ejecución. El script verifica que
las figuras no se superpongan. En la ejecución del 19 de septiembre de 2026 se
comprobaron 55, 57 y 300 objetos nativos, con 58, 62 y 400 extremos conectados.
La generación completa con exportación tardó aproximadamente 7, 7 y 41 segundos
en este equipo; no es una garantía ni un benchmark de otros entornos.

Abrir los tres `.dia` en el editor conserva figuras y conexiones editables.
**Ctrl+E** ajusta el diagrama a la ventana. El gráfico de pedidos es vertical:
aumentar el zoom para leer cómodamente y desplazarse por sus decisiones.
Esta primera galería utiliza tres figuras de flujo y conectores rectos. La
ampliación 0.2 añade los tipos técnicos y conectores de la siguiente sección.

No se sobrescriben archivos existentes. Para otra ejecución, usar
`task mcp:showcase SHOWCASE_DIR=/ruta/absoluta/nueva`; para retomar un solo
ejemplo, [showcase.py](examples/showcase.py) admite
`--only services`, `--only orders` o `--only mesh`. No hace falta reconstruir la
imagen por editar el generador: la tarea monta los ejemplos de sólo lectura.

## UML, electricidad y neumática

Después de reconstruir la imagen con `task mcp:build`, ejecutar:

```sh
task mcp:engineering
# Para repetir conservando las salidas anteriores:
task mcp:engineering ENGINEERING_DIR=/ruta/absoluta/nueva
```

Genera `.dia`, SVG, PNG y JSON de los tres ejemplos en `artifacts/engineering/`:

| Archivo | Nodos | Conectores | Contenido |
| --- | ---: | ---: | --- |
| `04-uml-pedidos` | 6 | 7 | Clases, atributos, métodos con parámetros, herencia y asociaciones |
| `05-mando-electrico` | 7 | 8 | Marcha/paro, retención, bobina, señalización, alimentación y retorno |
| `06-circuito-neumatico` | 5 | 5 | Cilindro de doble efecto, distribuidor 5/2, presión y escapes |

[engineering.py](examples/engineering.py) usa la API pública, incluyendo edición
posterior de una clase UML. Admite `--only uml|electrical|pneumatic` para retomar
un ejemplo. Los esquemas técnicos son ilustrativos; este módulo no realiza
simulación, cálculo eléctrico/neumático ni comprobación de normas de diseño.

`create_object` acepta `properties` estructuradas para `UML - Class`:
atributos, operaciones, parámetros, visibilidad, ámbito de clase y estereotipo.
`update_object` reemplaza los campos suministrados de forma transaccional.
`connect_objects` añade `type`, etiquetas UML y selección de terminales por
`source_connection`/`target_connection`; obtener sus índices mediante
`inspect_document`. Los símbolos técnicos admiten inversión horizontal/vertical.
Consultar [el contrato y sus ejemplos](../docs/modernization/api.md) y
[la implementación paso a paso](../docs/modernization/technical-diagrams.md).

## Límites del MVP

- Catálogo explícito de 13 tipos: tres de flujo, clase UML, cinco eléctricos
  y cuatro neumáticos. Conectores rectos, ortogonales, generalización y
  asociación UML; `get_capabilities` publica tipos exactos y esquemas JSON.
  No incluye todo el catálogo de Dia, curvas, conexiones a conectores, lazos
  al mismo objeto, estilos arbitrarios ni selección GUI.
- El enrutamiento ortogonal nativo respeta las direcciones de los terminales,
  pero no garantiza evitar objetos, etiquetas ni cruces. Revisar la distribución.
- Las etiquetas de símbolos sin texto nativo son objetos `Standard - Text`
  auxiliares. La API los mueve junto al símbolo; en el editor son objetos
  independientes, que pueden seleccionarse conjuntamente.
- Estado en memoria por sesión, máximo 32 documentos, 100 nodos y 200 conexiones
  por documento. Exportar antes de cerrar el cliente. Todavía no importa archivos
  `.dia` arbitrarios al servicio ni restaura una sesión; el editor sí abre los
  archivos exportados.
- Reconstrucción completa por edición, serializada y con timeout predeterminado
  de 30 segundos. Adecuado para el MVP acotado, pendiente medir escalabilidad.
- PNG acotado a 8192 píxeles por lado y 20 millones de píxeles antes de renderizar.
  Para diagramas mayores usar SVG o `.dia`.
- Los nombres de exportación son basenames, nunca rutas. Se preservan archivos
  existentes salvo `overwrite=true`. El directorio de trabajo debe pertenecer
  al usuario y no ser administrado por escritores locales no confiables.
- El aislamiento de procesos contiene fallos de estado; por sí solo no es una
  sandbox del motor C. No se exponen `eval`, shell, importación de scripts ni
  carga de plug-ins solicitada por clientes.

## Contribuir a este fork

Seguir [la guía del fork](../docs/modernization/contributing.md). Upstream
GNOME/dia no acepta contribuciones generadas con IA; este trabajo experimental
se mantiene en `jcrtexidor/dia`, con su origen documentado y licencia GPL.
