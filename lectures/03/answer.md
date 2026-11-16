# 第3回 解答

## 演習

- 第1回（素のLLM）とエージェントの回答の違い：
  - Pregunta: 「AIE2026の講座の宿題にある「3レベル」とは何ですか？」
  - **Clase 1 (`app.ask`, LLM sin herramientas)**: no conocía el curso e inventó niveles genéricos con seguridad (el mismo error que vi en la Clase 2 con el modelo base).
  - **Clase 3 (`app.agent`)**: respuesta correcta y coherente con `homework-levels` de `data/glossary.json`: 基礎（講義内容の確認）・実装（自分でコードを書く）・発展（調査や試行）; basta con hacer uno; termina indicando 第1回.
  - La diferencia no es el modelo (es el mismo Gemini), sino que el harness le da una herramienta para **consultar** antes de responder (Clase 2: el conocimiento se pasa en la entrada, no en los pesos).

- `--trace` で見えたツール呼び出し（ツール名と引数）：
  - 「LoRAとQLoRAの違いは？」:
    ```
    [tool call]   search_glossary({'query': 'LoRA'})
    [tool call]   search_glossary({'query': 'QLoRA'})
    [tool return] search_glossary -> [{"term": "LoRA", "lecture": 2, ...
    [tool return] search_glossary -> [{"term": "QLoRA", "lecture": 2, ...
    [usage] RunUsage(input_tokens=1882, output_tokens=220, requests=2, tool_calls=2)
    ```
    Busca un término por llamada, como dice el docstring (「query には調べたい用語を1つだけ入れる」), y pide las dos búsquedas **en la misma respuesta** (en lote): como ninguna necesita el resultado de la otra, no hace falta una vuelta extra del bucle.
  - 「第2回の内容から確認問題を1問出して」: `make_quiz({'lecture': 2})` → `{"question": "「事前学習」の意味は？", "answer": "..."}`.

- 1つの質問での LLM 呼び出し回数（`requests`）：
  - **2** en los dos casos con herramienta: 1.ª llamada = el modelo pide la(s) herramienta(s); 2.ª = redacta la respuesta con el resultado. Con lote, 2 búsquedas siguen costando 2 llamadas (no 3).

- 追加したツールと、docstring に書いた説明：
  - `make_quiz(lecture: int) -> str`: 「指定した回（1始まりの整数）の用語を1つ選び、確認問題とその答えを返す。「第2回の確認問題を出して」のように、復習用の問題を求められたときに使う。」
  - Si el número de sesión no tiene términos (p. ej. 0) devuelve un mensaje con las sesiones disponibles, en vez de fallar (`pytest` lo prueba con `lecture=0`).
  - También añadí a `INSTRUCTIONS`: 「確認問題を求められたら make_quiz を使う。」
  - Observación: la herramienta devolvió la respuesta, pero el modelo **no la mostró** y ofreció ayudar a comprobarla: siguió la instrucción 「宿題の答えそのものは書かず、考え方のヒントで導く」.

## 宿題

- 取り組んだレベル：**実装**

- やったこと：
  - **`save_learning_log(title, content, lecture)`** en `app/tools.py`: guarda un Markdown con frontmatter (`id`, `title`, `lecture`, `created_at`) en `learning_log/` (está en `.gitignore`).
    - **La ruta la decide el código, no el modelo**: nombre `fecha_slug_id.md`; el slug elimina `/`, `..`, espacios, etc., y se comprueba que el archivo quede dentro de `learning_log/` (Clase 3, Parte 9: los argumentos los escribe el modelo y no son confiables).
    - **Validación**: título 1–80 caracteres, cuerpo 1–2000, `lecture` 0–13. Si falla devuelve `{"saved": false, "reason": ...}` para que el modelo lo corrija o lo informe, en vez de romper el bucle (Parte 8).
    - **Idempotencia**: `id` = hash de los argumentos; si ya existe, devuelve `already_exists` y no duplica. Escritura en modo `"x"` (creación exclusiva) (Partes 4 y 7: herramientas no idempotentes).
  - **Registro con aprobación** en `app/agent.py`: `agent.tool_plain(tools.save_learning_log, requires_approval=True)` y `output_type=[str, DeferredToolRequests]`. En `INSTRUCTIONS`: usarla solo si se pide guardar explícitamente y no decir que se guardó si no se aprobó.
  - **Bucle de aprobación en el CLI** (`run_with_approval`): `run_sync` → si `result.output` es `DeferredToolRequests`, preguntar por cada `approvals` → reanudar con `message_history=result.all_messages()` + `DeferredToolResults` → repetir.
    - Antes de preguntar se muestra **la ruta y el contenido exactos** que se escribirán (misma función `prepare_learning_log` que usa la herramienta).
    - **Por defecto No**: solo `y`/`yes`/`はい` aprueban; Ctrl-C/Ctrl-D y entornos sin terminal rechazan; argumentos inválidos se rechazan sin preguntar. El rechazo se envía como `ToolDenied(motivo)` para que el modelo lo sepa.
    - **Máximo 3 rondas** de aprobación por pregunta, contadas por el harness (Parte 7: la parada fuera del modelo).
    - **`[verify]`**: compara `learning_log/` antes y después y muestra los archivos realmente creados, sin fiarse de lo que diga el modelo (Parte 7: comprobar por el estado).
  - **Tests** `tests/test_learning_log.py` (22, sin API key, con `TestModel` y carpeta temporal): no se ejecuta antes de aprobar, aprobado → archivo, rechazado → nada y el modelo recibe el motivo, idempotencia, títulos con `../` `/tmp` `\`, argumentos inválidos, default No, Ctrl-C/Ctrl-D, sin terminal, límite de rondas.

- 結果：
  - `uv run pytest -q` → **33 passed** (11 originales + 22 nuevos). `--list-tools` → 4 herramientas, `save_learning_log` con su docstring.
  - **Aprobado** (`y`):
    ```
    [承認待ち] ツール save_learning_log を実行しようとしています。
    保存先: learning_log/2026-11-16_承認が必要なツールとDeferredToolRequests_3f364bc9a190.md
    ...
    実行してよいですか？ [y/N]: y
    学習の記録を保存しました。（第3回）
    [verify] 新しく保存されたファイル: learning_log/2026-11-16_承認が必要なツールとDeferredToolRequests_3f364bc9a190.md
    [approval rounds] 1
    [tool call]   save_learning_log({'lecture': 3, 'content': '今日学んだこと：承認が必要なツールは実行前に止まり、DeferredToolRequests が返る。', 'title': '承認が必要なツールとDeferredToolRequests'})
    [tool return] save_learning_log -> {"saved": true, "path": "learning_log/...3f364bc9a190.md", "id": "3f364bc9a190"}
    [usage] RunUsage(input_tokens=1502, output_tokens=69, requests=2, tool_calls=1)
    ```
  - **Misma petición, rechazada** (`N`):
    ```
    保存先: learning_log/2026-11-16_承認が必要なツールの動作についての学び_65af61633f93.md
    実行してよいですか？ [y/N]: N
    学習の記録の保存について、利用者の承認が得られなかったため、保存は行われませんでした。（関係する回：第3回）
    [verify] learning_log/ に新しいファイルはありません
    [tool return] save_learning_log -> 利用者が実行を拒否しました。保存などの操作は行われていません。
    [usage] RunUsage(input_tokens=1449, output_tokens=82, requests=2)
    ```
  - **Mismos argumentos exactos, llamada directa** (sin LLM): `{"saved": false, "already_exists": true, "path": "learning_log/...3f364bc9a190.md"}`. `ls learning_log/` → 1 archivo.

    | caso | ¿pidió aprobación? | archivo creado (`[verify]`) | `requests` | `tool_calls` | qué dijo el modelo |
    |---|---|---|---|---|---|
    | guardar, aprobado | sí | sí (1) | 2 | 1 | 「保存しました」 (coincide con el disco) |
    | misma petición, rechazado | sí | no | 2 | — | 「保存は行われませんでした」 (honesto) |
    | mismos argumentos exactos (directo) | — | no (`already_exists`) | 0 | — | — |
    | pregunta normal (LoRA/QLoRA) | no | — | 2 | 2 | no llamó a `save_learning_log` ✅ |

- 気づき・疑問：
  - **La misma petición produjo argumentos distintos**, y por tanto otro `id`: 1.ª vez título 「承認が必要なツールとDeferredToolRequests」 (`3f364bc9a190`), 2.ª vez 「承認が必要なツールの動作についての学び」 (`65af61633f93`). Si hubiera aprobado la segunda, habría **dos archivos** con el mismo aprendizaje. Mi idempotencia (hash de argumentos) protege contra **reintentos del harness con la misma llamada** (lo comprobé: `already_exists`), que es el caso de la Clase 3 (correo enviado dos veces tras un corte), pero **no** contra peticiones repetidas del usuario, porque cada vez pasan por el modelo, que reformula (Clase 2, propiedad ①). Para eso haría falta otra clave: p. ej. el texto original del usuario, o comparar por similitud con los registros existentes y mostrarlo en la aprobación.
  - **Aprobar no es gratis**: tanto aprobado como rechazado costaron `requests=2`; la ejecución se detiene y hay que reanudar reenviando todo el historial (como el chat de la Clase 1). `tool_calls` solo cuenta herramientas **ejecutadas**: en el caso rechazado no aparece.
  - **Lo que se guarda lo escribe el modelo, no yo**: añadió 「今日学んだこと：」 al contenido y cambió el título entre ejecuciones. Por eso es importante que la aprobación muestre el texto exacto: si solo preguntara "¿guardar? [y/N]", aprobaría algo que no he leído y la aprobación sería una formalidad (Parte 4).
  - **El modelo fue honesto tras el rechazo**, pero no dependo de eso: `[verify]` mira la carpeta. En la Clase 2 un modelo pequeño no obedecía "di que no está", así que la comprobación va en código (Parte 7: estado, no palabras).
  - **En LoRA/QLoRA el modelo añadió información que no está en el glosario** (「通常は16ビットなどの高精度で」). No es incorrecto, pero muestra que "buscar antes de responder" no impide completar con conocimiento propio; el `INSTRUCTIONS` de esta clase no lo prohíbe (el de la Clase 5 sí: 「知識だけで穴埋めしない」).
  - Detalle: `created_at` sale en UTC (`+00:00`) porque Codespaces corre en UTC.
  - **Duda**: si en el futuro una herramienta **lee** `learning_log/` como memoria, el contenido escrito por el modelo (que puede venir de páginas o documentos) volvería a entrar al contexto como instrucciones. ¿Habría que marcarlo como dato o revisarlo antes (Parte 9, MINJA)?
