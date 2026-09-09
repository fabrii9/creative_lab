# Creative Lab AI para Odoo 19

MVP instalable para gestionar todo el ciclo de un creativo:

1. Brief y archivos fuente.
2. Hipótesis de marketing.
3. Creativos y versiones ramificadas e inmutables.
4. Ejecuciones auditadas de agentes mediante `llm_connector`.
5. Simulador visual sin credenciales para probar el flujo completo.
6. Aprobación y exportación con limpieza de metadatos.
7. Publicación real y segura en Meta Ads, siempre pausada al crear.
8. Sincronización acumulada y diaria de métricas por anuncio.

## Instalación

Copiar `creative_lab` al `addons_path`, comprobar que el módulo técnico
`llm_connector` está instalado, actualizar la lista de aplicaciones e instalar
**Creative Lab AI**.

Para usuarios no administradores, asignar el privilegio **Creative Lab** como
**Creador**, **Aprobador**, **Publicador de Meta**, **Activador de Meta** o
**Administrador**. Sólo el activador puede iniciar o detener gasto real.

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

El simulador crea un PNG determinista que permite validar UI, linaje,
aprobaciones y descargas sin consumir una API. Al ser una imagen raster,
las versiones simuladas también sirven como fuente para retocarlas o
revisarlas con proveedores reales (las versiones SVG generadas por
versiones viejas del módulo no la admiten: hay que generar una base nueva).

El asistente y la pestaña **Mensaje** del creativo tienen un botón
**Sugerir con IA** que completa en una sola ejecución todos los campos de
texto que estén vacíos (prompt y "Evitar" en el asistente; titular, texto
principal y llamado a la acción en el creativo), usando el contexto del
brief, la hipótesis y el creativo. Lo que ya escribiste no se toca: para
regenerar un campo, borralo y volvé a pulsar el botón. Cada sugerencia
queda auditada como una ejecución de agente más. Desde **Ajustes > Creative
Lab > Sugerencias con IA** se pueden editar las instrucciones globales de
estilo que recibe el agente en cada botón (prompts de imagen, copy del
creativo y copy del anuncio Meta), sin tocar código.

El asistente de generación incluye **Generar también en cuadrado y
vertical** (activado por defecto): además del formato del creativo, genera
la misma pieza en 1:1 y 9:16 como creativos hermanos con el mismo prompt y
copy, para que los formatos no se desalineen. Los hermanos se reutilizan
en corridas siguientes. Cada formato es una ejecución de agente con su
propio costo; desmarcá la opción para generar un solo formato.

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

`gpt-image-2` usa la relación de aspecto del creativo para elegir el tamaño de
salida. La familia `gpt-image*` permite configurar calidad automática, baja,
media o alta; los modelos con tamaños legacy conservan el valor del perfil.

Los perfiles reales requieren tarifas o un costo fijo conservador y respetan
el máximo configurado antes de llamar al proveedor. Las respuestas JSON se
validan contra la forma o el subconjunto de JSON Schema guardado en el agente.

Como la versión integrada de `llm_connector` no publica aún una API de imagen,
las capacidades visuales faltantes quedan aisladas en un adaptador propio que
reutiliza sus credenciales y configuración; el resto usa su API pública.

Las credenciales nunca se copian a los registros de Creative Lab: se leen del
registro `llm.provider` en el momento de ejecutar.

## Meta Ads

Creative Lab usa la Marketing API fijada por conexión (por defecto `v26.0`).
Cada conexión permite elegir entre dos orígenes de credenciales:

- **Variables de entorno**, recomendado para máxima separación de secretos. El
  token debe existir dentro del contenedor, por defecto como
  `CREATIVE_LAB_META_ACCESS_TOKEN`.
- **Guardadas en Odoo**, cargadas mediante un asistente exclusivo para
  administradores. Nunca se vuelven a mostrar en la interfaz, pero se almacenan
  en la base de datos y quedan incluidas en sus backups.

Se recomienda un token de System User con los activos asignados y permisos
`ads_management`, `ads_read`, `pages_manage_ads`, `pages_read_engagement` y
`pages_show_list`. El App Secret es opcional y habilita `appsecret_proof`.

Configuración:

1. Abrir **Creative Lab > Configuración > Conexiones Meta Ads**.
2. Indicar Ad Account ID, Page ID, Instagram User ID opcional y el número de
   WhatsApp internacional vinculado a esa página.
3. Elegir el origen de credenciales. Para guardarlas en Odoo, guardar primero
   la conexión, pulsar **Cargar credenciales** y pegar el Access Token y el App
   Secret opcional; al confirmar, ese origen queda seleccionado automáticamente.
   El botón **Borrar credenciales** las elimina. Para no perder
   la capacidad de detener gasto, el sistema bloquea el borrado y el cambio a
   otra fuente si hay campañas activas, activaciones en cola o conciliaciones de
   entrega. En esos estados sólo admite rotar hacia un token nuevo que pueda
   validar previamente los permisos de gestión, la cuenta y la página
   configuradas. **Probar conexión** también verifica que estén concedidos
   `ads_management`, `ads_read`, `pages_manage_ads` y
   `pages_read_engagement`; `pages_show_list` sigue recomendado para administrar
   o descubrir páginas desde Meta. También exige que el usuario del token tenga
   la tarea `ADVERTISE` o `MANAGE` sobre la cuenta publicitaria.
4. Configurar topes de presupuesto, probar la conexión y recién entonces
   habilitar **Permitir crear en pausa**.
5. Crear una publicación con versión aprobada y una exportación PNG/JPEG con
   metadatos eliminados. Completar copy, targeting, presupuesto y fecha final.
   El targeting inicial declara audiencia manual (`advantage_audience: 0`);
   revisarlo explícitamente antes de preparar.
6. **Preparar** y luego **Crear pausada en Meta**. La imagen, campaña, conjunto,
   creativo y anuncio se crean explícitamente en `PAUSED`.
7. Revisar la jerarquía en Ads Manager. La activación es un botón separado,
   requiere el grupo Activador, una fecha final, topes válidos y que la conexión
   tenga habilitada la activación. El botón crea una orden durable; un worker la
   procesa en menos de un minuto y activa la campaña al final, después de volver
   a verificar en Meta presupuesto, fecha, segmentación, destino y relaciones.

Si una escritura queda sin respuesta concluyente, Creative Lab bloquea el
reintento y exige **Conciliar con Meta**. Para cambios de entrega consulta
campaña, conjunto y anuncio; ante estados mixtos conserva el bloqueo y ofrece
una pausa de seguridad al rol Activador.

Cada publicación usa una clave aleatoria e inmutable en los nombres remotos.
Antes de crear cada objeto, Odoo busca esa clave y recupera únicamente una
coincidencia pausada con las relaciones esperadas. Esto permite retomar el
flujo sin duplicar objetos si un worker se interrumpe después de que Meta
aceptó una escritura.

La sincronización manual o cada 30 minutos consulta el estado del anuncio y
Ads Insights. Guarda gasto, impresiones, alcance, clics, CTR, CPC, CPM,
frecuencia, acciones crudas y conversaciones atribuidas por Meta, además de una
serie diaria móvil de 28 días. Las conversaciones de Meta no se confunden con
los resultados confirmados por WhatsApp/CRM.

Las llamadas siguen el flujo oficial de Meta:

- https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/messaging-ads/click-to-whatsapp
- https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights

## Modo simple (operador único)

En **Ajustes > Creative Lab** el administrador puede activar **Modo simple
(operador único)** para trabajar sin circuito de aprobación cuando una sola
persona opera todo el flujo. El modo queda apagado por defecto y al activarlo:

- Las versiones nuevas (generadas o importadas) se aprueban automáticamente
  con el usuario actual como aprobador, y el creativo queda aprobado al
  instante, listo para exportar.
- El asistente **Generar / retocar** oculta los agentes de simulación si hay
  al menos un agente real disponible, y el agente sugerido por defecto deja
  de ser el simulado.
- En la publicación, **Preparar** y **Crear pausada en Meta** se fusionan en
  un solo botón **Crear en Meta (pausada)**, con las mismas validaciones de
  siempre. La activación del gasto sigue siendo un paso separado.

Independientemente del modo, los formularios de brief, creativo y publicación
muestran un cartel con el próximo paso sugerido según el estado del registro.

## Atribución WhatsApp

Con el módulo oficial `whatsapp` instalado (dependencia de Creative Lab),
cada mensaje entrante que Meta marca con `referral` (anuncios
click-to-WhatsApp) guarda `source_id`, `source_url` y `ctwa_clid` en el
mensaje. Si el `source_id` coincide con el anuncio de una publicación, se
crea automáticamente un resultado **Conversación iniciada** confirmado,
vinculado al contacto del canal y al lead/oportunidad del CRM si existe.
El mismo mensaje nunca se atribuye dos veces, y la publicación registra el
evento en su historial.

## Pendiente posterior

La clasificación automática de las conversaciones (lead, calificado, venta)
con un agente sigue fuera de este incremento.
