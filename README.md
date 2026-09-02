# Creative Lab AI para Odoo 19

MVP instalable para gestionar todo el ciclo de un creativo:

1. Brief y archivos fuente.
2. Hipótesis de marketing.
3. Creativos y versiones ramificadas e inmutables.
4. Ejecuciones auditadas de agentes mediante `llm_connector`.
5. Simulador visual sin credenciales para probar el flujo completo.
6. Aprobación y exportación con limpieza de metadatos.
7. Publicaciones Meta y resultados comerciales registrados manualmente.

## Instalación

Copiar `creative_lab` al `addons_path`, comprobar que el módulo técnico
`llm_connector` está instalado, actualizar la lista de aplicaciones e instalar
**Creative Lab AI**.

Para usuarios no administradores, asignar el privilegio **Creative Lab** como
**Creador**, **Aprobador y publicador** o **Administrador**.

El módulo está diseñado para Odoo.sh u on-premise. No se puede instalar como
módulo Python personalizado en Odoo Online.

## Primera prueba sin API

1. Abrir **Creative Lab > Configuración > Agentes**.
2. Verificar que existe **Generador visual · Simulación**.
3. Crear un brief, completar objetivo, oferta y público, y marcarlo listo.
4. Crear una hipótesis y un creativo.
5. En el creativo, pulsar **Generar / retocar**.
6. Elegir el agente simulado, escribir un prompt y generar.
7. Enviar la versión a revisión, aprobarla y exportarla.

El simulador crea un SVG determinista que permite validar UI, linaje,
aprobaciones y descargas sin consumir una API.

Desde un brief o creativo también se puede pulsar **Ejecutar agente** para
probar agentes de estrategia, copy o revisión. Cada ejecución queda auditada
con su entrada, salida, proveedor, modelo, duración y consumo informado.
Cuando un agente real de tipo análisis recibe una versión PNG, JPEG, WebP o
GIF, la imagen se envía al modelo multimodal junto con el pedido de revisión.

## Proveedores reales

El puente incluido admite:

- Texto mediante la API pública de `llm_connector`.
- Análisis visual OpenAI-compatible y Anthropic mediante su API pública de chat.
- Análisis visual, generación y edición de imágenes con Gemini.
- Generación/edición OpenAI y endpoints OpenAI compatibles cuando el modelo lo soporta.

Como la versión integrada de `llm_connector` no publica aún una API de imagen,
las capacidades visuales faltantes quedan aisladas en un adaptador propio que
reutiliza sus credenciales y configuración; el resto usa su API pública.

Las credenciales nunca se copian a los registros de Creative Lab: se leen del
registro `llm.provider` en el momento de ejecutar.

## Alcance intencional del MVP

La publicación en Meta Ads y la lectura automática de la referencia de anuncios
desde webhooks de WhatsApp quedan modeladas, pero todavía no llaman APIs. Esto
permite validar el modelo de negocio antes de autorizar gasto publicitario.
