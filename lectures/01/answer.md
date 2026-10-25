# 第1回 解答

## 演習

- 講座に固有の質問（宿題の3レベル）へのモデルの回答（要約でよい）：
  `gemini-3.5-flash-lite` respondió con seguridad una estructura **genérica** de 3 niveles: 基礎・入門 / 標準・中級 / 発展・上級, con ejemplos de contenido para cada uno. Recomendó empezar por el nivel 1 o 2 y consultar el material o la comunidad del curso. Cuando hice la pregunta en español, describió otra rúbrica distinta (tipo Bronce/Plata/Oro).
- 用語集の正しい意味と比べて気づいたこと：
  Lo correcto (`data/glossary.json` → `homework-levels`) es **基礎・実装・発展, y basta con hacer uno**. La modelo acertó por casualidad los nombres 基礎 y 発展, pero el nivel del medio es **実装** (modificar código) y no un "nivel intermedio". Además omitió lo esencial: que solo hay que hacer uno; incluso insinuó que podría ser obligatorio hasta el nivel 2. No dijo "no lo sé": completó con conocimiento general y un tono seguro, y la respuesta cambió entre ejecuciones e idiomas. Por eso hace falta darle la fuente (用語集 / RAG / エージェント, Clase 3).
- 表示できたトークン数（入力 / 出力）：
  **入力 21 / 出力 690** (思考 0, 合計 711). Implementado en `app/ask.py` → `format_usage()`. Además muestro los tokens de pensamiento (`thoughts_token_count`): no aparecen en la respuesta, pero sí cuentan para el consumo.

## 宿題

- 取り組んだレベル：**発展**（además 基礎 y 実装）

- やったこと：
  1. **発展** — `scripts/benchmark.py`: mide con `time.perf_counter()` el tiempo de `generate_content` y lee `usage_metadata` (entrada / salida / pensamiento / total). Compara 3 modelos × 3 preguntas de distinta naturaleza (`lora`: general, `curso`: propia del curso, `largo`: explicación larga con fórmulas) × 3 repeticiones = 27 llamadas.
     - Las llamadas se intercalan (repetición → pregunta → modelo) para que la congestión momentánea no favorezca a un modelo. Esto además reparte la carga por modelo frente al RPM.
     - Entre llamadas hay una pausa de 5 s; el 429 se registra y se reintenta una vez, y el resto de errores se registran.
     - Resultados: `lectures/01/results/modelos/` (`calls.csv` = datos crudos, `answers.md` = respuestas, `summary.md` = resumen).
  2. **基礎** — misma pregunta (`curso`) 3 veces con temperature 0 / 1 / 2 en `gemini-3.5-flash-lite` → `lectures/01/results/temperature/`. Añadí `--temperature` a `app/ask.py`, que pasa `types.GenerateContentConfig(temperature=...)`.
  3. **実装** — `uv run python -m app.ask --chat`: conversación con historial usando `client.chats`, mostrando en cada turno los tokens y el número de mensajes del historial.
  4. Pruebas sin API key: `tests/test_benchmark.py`, con un cliente falso que simula un 429 y verifica la intercalación y los archivos generados. Total: 14 tests ok.

- 結果：

  **Modelos** (medianas de 3 repeticiones; tokens = media):

  | modelo | pregunta | ok/n | lat. mediana (s) | lat. min–max (s) | salida | pensamiento | total |
  |---|---|---|---|---|---|---|---|
  | 3.5-flash-lite | lora | 3/3 | 3.22 | 2.69–3.77 | 646 | 0 | 653 |
  | 3.5-flash | lora | 3/3 | 11.46 | 11.23–47.10 | 638 | 1037 | 1681 |
  | 3.1-flash-lite | lora | 2/3 | 5.49 | 2.97–8.02 | 690 | 0 | 697 |
  | 3.5-flash-lite | curso | 3/3 | 2.47 | 2.27–2.47 | 511 | 0 | 532 |
  | 3.5-flash | curso | 2/3 | 13.31 | 13.29–13.34 | 574 | 1302 | 1897 |
  | 3.1-flash-lite | curso | 3/3 | 27.37 | 4.06–52.41 | 650 | 0 | 671 |
  | 3.5-flash-lite | largo | 3/3 | 4.09 | 3.49–4.53 | 1181 | 0 | 1196 |
  | 3.5-flash | largo | 3/3 | 18.27 | 17.58–23.92 | 1870 | 1423 | 3308 |
  | 3.1-flash-lite | largo | 3/3 | 13.85 | 3.62–32.46 | 914 | 0 | 929 |

  27 llamadas: 25 ok, **2 × 503** (servidor saturado) y **0 × 429**.

  **Temperature** (`3.5-flash-lite`, pregunta `curso`, 3 rep. cada una):

  | T | lat. mediana (s) | total tokens (media) | rango total por llamada |
  |---|---|---|---|
  | 0 | 2.67 | 608 | 517–737 |
  | 1 | 2.71 | 653 | 562–700 |
  | 2 | 3.13 | 620 | 428–720 |

  **Cuota gratuita de mi cuenta** (AI Studio, 25/10/2026):

  | modelo (AI Studio) | RPM | TPM | RPD | uso tras las mediciones |
  |---|---|---|---|---|
  | Gemini 3.5 Flash Lite | 15 | 250K | 500 | 21 / 500 |
  | Gemini 3.1 Flash Lite | 15 | 250K | 500 | 9 / 500 |
  | Gemini 3.6 Flash (← `gemini-3.5-flash`) | 5 | 250K | **20** | 9 / 20 |

- 気づき・疑問：
  - **La latencia no la explican solo los tokens.** `3.1-flash-lite` generó pocos tokens (~700) y aun así fue de 3.6 a 52.4 s para preguntas parecidas: es congestión del servidor. `3.5-flash-lite` fue rápido y estable (2.3–4.5 s, ~200–290 tok/s). Con 3 repeticiones, la mediana y el rango dicen más que la media.
  - **El pensamiento es un costo oculto.** En `lora`, `3.5-flash` y `3.5-flash-lite` producen una respuesta visible del mismo tamaño (~640 tokens), pero `3.5-flash` gasta además ~1000 tokens de pensamiento: 2.6× tokens y 3.6× tiempo. El pensamiento supone el 43–69 % del total. En `largo` la respuesta sí fue más extensa (3788 vs 2310 caracteres).
  - **Pregunta del curso:** ningún modelo ni temperatura dio la respuesta correcta. Todos inventaron con seguridad una estructura genérica. Subir de modelo no corrige la falta de conocimiento; lo que ayuda es aportar la fuente.
  - **Temperature:** T=0 **no fue determinista**. Las 3 respuestas cambiaron de redacción y de longitud (517–737 tokens). Con T=2 el texto siguió siendo coherente, sin una degradación visible. Lo que se mantuvo igual en todas fue el contenido inventado. La temperatura cambió la forma, pero no la exactitud.
  - **Cuota gratuita:** con ~1300 tokens por llamada (máx. 3557), el TPM de 250K no limita (cabrían ~190 llamadas/min). Los límites reales son **RPM y RPD**. Lo más estricto es `gemini-3.5-flash`, contado en AI Studio como *Gemini 3.6 Flash*: RPD 20, y este experimento consumió 9 (45 %). Un agente que haga ~4 llamadas por pregunta solo permitiría ~5 preguntas al día con ese modelo, frente a ~125 con `flash-lite` (RPD 500). Con RPM 5, el pensamiento (~13 s por llamada) y un agente encadenado llegarían al límite enseguida. Los errores que vi fueron **503 de disponibilidad**, no 429 de cuota: hace falta reintentar y tener un modelo alternativo. Curiosamente, el que el README sugiere como alternativa fue hoy el más inestable.
  - **Historial (実装):** cada turno reenvía todo el historial, así que los tokens de entrada crecen con la conversación y consumen antes el TPM.
  - **Límites de la medición:** solo 3 repeticiones por combinación, desde una región y una franja horaria (domingo ~18:00 COT). La latencia incluye la red de Codespaces y solo hay una pregunta para el estudio de temperatura.
