# Ampliación 0.2: UML y esquemas técnicos

Continuación del MVP, 2026-09-19. Se conserva GTK3 y el contrato lógico v1;
el cambio amplía las operaciones independientes de GTK. No implementa la
migración GTK4 ni un simulador de circuitos.

## Recorrido para futuras contribuciones

1. **Auditar fábricas y propiedades reales.** Las hojas `UML`, `Electric` y
   `Pneumatic` enumeran tipos, pero no describen completamente sus setters.
   Revisar `objects/UML`, `objects/custom` y `plug-ins/python/pydia-property.c`.
   Ejecutar las consultas de `properties.keys()`, valores y `connections`
   dentro del intérprete de Dia después de cargar plugins, no con `import dia`
   en el Python del servidor MCP.
2. **Acotar un catálogo verificable.** `native/catalog.py` comparte nombres
   autorizados entre el servidor y el worker de biblioteca estándar. Esta
   entrega expone 13 objetos y cuatro conectores; no anuncia todo el catálogo
   de Dia. Añadir un tipo exige probar creación, dimensiones, texto, terminales,
   movimiento, exportación y recarga.
3. **Separar contrato público y representación C.** `models.py` define clases
   Pydantic para atributos, métodos y parámetros UML. `bridge.py` transforma
   esas estructuras en las tuplas que espera PyDia. El cliente nunca recibe
   acceso a setters arbitrarios ni ejecuta código. Se validan también las
   solicitudes directas del importador antes de llamar a los setters C.
4. **Probar propiedades, no sólo imágenes.** Las operaciones UML tienen un
   enum de herencia: 0 significa abstracta, no normal. Se usa `leaf` (2), el
   valor predeterminado nativo, salvo selección explícita. Las pruebas leen
   atributos, operaciones, parámetros, visibilidad y referencias de conexión
   directamente del `.dia` y después de recargarlo mediante Dia.
5. **Adaptar el flujo al resultado nativo.** `inspect_document` ahora publica
   todos los puntos de conexión, sus posiciones y direcciones. Los terminales
   técnicos se seleccionan por índice; los índices dinámicos UML no son
   seleccionables explícitamente. `update_object` sustituye los campos
   indicados y reconstruye objetos/conexiones antes de publicar la revisión.
6. **Respetar geometría propia de cada símbolo.** Los símbolos técnicos
   conservan proporciones. Las clases UML calculan su altura por contenido.
   Los símbolos sin texto reciben un `Standard - Text` auxiliar, identificado
   con `meta.dia_mcp_parent`; `label_bounds` permite incluirlo en el diseño.
   Son objetos independientes al editarlos manualmente en la GUI.
7. **Corregir defectos nativos que el flujo descubre.** `custom_update_data`
   movía puntos reflejados pero mantenía direcciones calculadas al crear el
   objeto. Ahora deriva las direcciones de los límites originales en cada
   actualización y aplica ambos flips. Conserva puntos interiores, esquinas
   y el punto principal. Las regresiones verifican inversión horizontal,
   vertical, doble, restauración y lectura nativa del archivo exportado.
8. **Validar transporte y transacciones.** Además del flujo Python, el cliente
   de prueba inicia un servidor MCP real por stdio y llama a creación UML,
   actualización, conexión y exportación. Los índices son enteros estrictos:
   `true` no puede convertirse silenciosamente en el terminal 1. Los fallos
   conservan revisión, objetos y geometría anteriores.
9. **Revisar los ejemplos exportados.** `examples/engineering.py` genera UML de
   pedidos, mando eléctrico y neumática mediante la API pública. Exporta Dia,
   SVG, PNG y un JSON con estado, geometría y hashes. Revisar imágenes: el
   enrutador ortogonal no evita todos los cruces ni las etiquetas. Los ejemplos
   son esquemas ilustrativos, sin verificación física o normativa.

## Reproducir

```sh
task mcp:check
task mcp:build
task mcp:test
task mcp:engineering
```

La imagen construye y prueba el motor C y después instala el paquete 0.2.0.
`mcp:test` ejecuta el paquete instalado como usuario no privilegiado y sin red.
Para repetir la galería sin sobrescribirla:

```sh
task mcp:engineering ENGINEERING_DIR=/ruta/absoluta/otra-galeria
```

Para iterar sólo Python sobre una imagen que ya incluya la corrección C:

```sh
docker run --rm --init --network=none --user "$(id -u):$(id -g)" \
  -e DIA_MCP_NATIVE=1 -e PYTHONPATH=/work/src \
  -v "$PWD/mcp:/work:ro" -w /work dia-mcp:ubuntu26 \
  xvfb-run -a python -m pytest -q -p no:cacheprovider tests
```

Usar `--init`: `xvfb-run` puede quedarse esperando señales de arranque si su
shell es PID 1. Los cambios C requieren reconstruir la imagen. El montaje de
fuente Python es para desarrollo; la configuración MCP normal usa el paquete
instalado en la imagen reconstruida.

Regenerar el esquema público después de modificar los modelos, desde `mcp`:

```sh
uv run python - <<'PY'
import json
from pathlib import Path
from dia_mcp.models import Document
Path('../docs/modernization/document.schema.json').write_text(
    json.dumps(Document.model_json_schema(), indent=2) + '\n'
)
PY
```

## Siguiente alcance razonable

Multiplicidades y agregación UML, más símbolos eléctricos/neumáticos, rutas
editables con puntos intermedios, etiquetas agrupadas y edición por lotes.
Mantener tipos explícitos y regresiones nativas; no ampliar el catálogo mediante
un diccionario de propiedades C sin validar.
