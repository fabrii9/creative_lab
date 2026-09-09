# Nomenclatura y estándares de trabajo — Creative Lab

Estándar para organizar briefs, hipótesis y creativos de forma escalable.

## La matriz de trabajo

Cada avatar (público) tiene su propio brief. Dentro de cada brief, las
hipótesis combinan **un dolor** con **un estado de conciencia**. Cada
hipótesis tiene sus creativos.

```
Avatar (Brief)
├── Hipótesis 1 = Dolor 1 × Consciente del problema
├── Hipótesis 2 = Dolor 2 × Consciente de la solución
└── Hipótesis 3 = Dolor 3 × Consciente del producto
```

Los **3 deseos masivos** transversales se reparten uno por hipótesis:

- H1 → Dejar de perder plata por desorden.
- H2 → Sentir control sin estar presente.
- H3 → Crecer / delegar sin que explote la operación.

## Nomenclatura

| Nivel | Formato | Ejemplo |
|---|---|---|
| Brief (avatar) | `[emoji] AV# · Avatar — Promesa` | `📦 AV1 · Distribuidora multicanal — Control y stock real` |
| Hipótesis | `[emoji] AV#-H# · Dolor corto` | `📦 AV1-H1 · Stock que no cierra` |
| Creativo | `[emoji] AV#-H#-C# · Variante` | `📦 AV1-H1-C1 · Base` |
| Versión | automático (`nombre · v#`) | `📦 AV1-H1-C1 · Base · v2` |

Reglas:

- **Un emoji por avatar**, siempre el mismo, en todos los niveles.
  Emoji elegido hasta ahora: 📦 distribuidora · 🛠️ rescate Odoo ·
  🪟 cortineros y aberturas.
- Los números no se reusan: si una hipótesis se descarta, su número queda
  libre para siempre (el aprendizaje queda registrado en su campo
  *Aprendizaje* antes de descartarla).
- El creativo base se crea en 1:1; al generar, el asistente crea
  automáticamente el hermano 9:16 con el sufijo `· 9:16` (mismo prompt y
  copy). No crear formatos a mano.
- El dolor en el nombre de la hipótesis es corto y en las palabras del
  mercado, nunca jerga técnica.

## Cómo escalar

- **Avatar nuevo** → próximo número de AV libre (`AV4`), emoji nuevo, brief
  nuevo en el proyecto *Marketing y Publicidad Aftermoves*. Duplicar la
  matriz de 3 hipótesis como punto de partida.
- **Dolor nuevo en un avatar existente** → próximo H libre dentro de ese
  brief (`H4`), con su estado de conciencia explícito.
- **Variante de anuncio** → creativo nuevo con próximo C (`C2`) bajo la
  misma hipótesis. Nunca mezclar hipótesis en un creativo.
- **Iteración de una pieza** → *Crear rama* desde la versión, nunca editar
  versiones existentes (son inmutables).

## Contenido obligatorio por registro

- **Brief**: objetivo, oferta concreta de entrada (diagnóstico / auditoría /
  demo), público con números, dolores, deseos, objeciones, prueba social y
  guía de marca (palabras prohibidas incluidas).
- **Hipótesis**: segmento, dolor, deseo, objeción principal, nivel de
  conciencia, sofisticación, ángulo, hook y por qué debería funcionar.
- **Al cerrar una hipótesis** (ganadora o descartada): cargar el
  *Aprendizaje* — qué dijo el mercado, con números.
