# 第2回 解答

## 演習

- 使ったモデル・設定（`result.json` の `config` から）：
- 自分で学習を実行したか（`executed_training_myself`）：はい / いいえ（実行できた範囲：　）
- 学習前：`format_rate` =　 / `content_rate` =　
- 学習後：`format_rate` =　 / `content_rate` =　
- 退行した質問：
- 学習後に残った失敗と、その型（根拠なしの質問に断定した / 根拠ありの質問に確認要求で逃げた / 形式の崩れ）：
- 知識を問う質問（セクション 6）の結果（学習前の分類 → 学習後の分類）と気づいたこと：
- 学習で変わったこと・変わらなかったこと：

宿題
取り組んだレベル：発展
変えた設定やデータ：
Datos de entrenamiento: `scripts/make_sft_dataset.py` sin cambios → `lectures/02/homework/glossary_sft.jsonl` (130 ejemplos = 65 términos × 2 plantillas, formato `messages`). En Colab comprobé que el JSONL coincide exactamente con lo que se regenera desde `glossary.json`.
Modelo y LoRA: igual que el ejercicio (`Qwen/Qwen3.5-0.8B`, `revision` fija, r=16, alpha=32, lr=2e-4, greedy, `max_new_tokens`=192). Solo cambié `num_train_epochs`: 10 en lugar de 20, porque hay 130 ejemplos en lugar de 14. Resultado: 170 pasos en 382 s (T4). La pérdida bajó de 3,25 (paso 10) a 0,08 (paso 170).
Entorno: `transformers 5.18.0`, `peft 0.21.1`, `trl 1.14.2`, igual que los PINS. `torch` fue 2.14.1 (Colab lo actualizó; el curso usó 2.11.0).
Evaluación propia (`scripts/make_glossary_data.py eval`, `scripts/glossary_ft.py`): 55 preguntas en 7 categorías. Verifico automáticamente que ninguna, salvo las de `seen`, está en el entrenamiento.
categoría	n	qué mide	correcto si
seen	8	mismo enunciado que el entrenamiento (fuga intencional)	contiene las palabras clave
reworded	16	mismo término, plantilla nueva	ídem
alias	10	el término escrito con un alias (el entrenamiento solo usa el nombre principal)	ídem
natural	5	pregunta natural sin el término; incluye la de la Clase 1 (「3レベル」)	ídem
fictional	6	término inventado (p. ej. 「AIE2026の第14回の宿題」)	dice que no está o pide confirmación
absent_real	6	término real fuera del glosario (RLHF, RAG, DPO…)	no copia una definición del glosario
general	4	pregunta ajena (日本の首都は？, 1+…+10)	no copia una definición del glosario
Condiciones: `search` (búsqueda por nombre, sin LLM; misma normalización que `app/tools.py`), `before` (modelo base), `rag` (modelo base + extracto del glosario en el system prompt), `after` (modelo + adapter). `rag` se midió antes de entrenar.
結果（比較表や数字）：
métrica	search	before	rag	after
acierto `seen` (memorización)	1.000	0.125	0.875	1.000
acierto no vistas (reworded+alias+natural, n=31)	0.903	0.097	0.774	0.742
└ reworded (n=16)	16/16	2/16	15/16	16/16
└ alias (n=10)	10/10	1/10	9/10	5/10
└ natural (n=5)	2/5 (3 "no está")	0/5	0/5 (4 parciales)	2/5 (3 parciales)
└ términos propios del curso	0.800	0.000	0.600	0.667
ficticios: inventa (↓)	0.833	1.000	1.000	1.000
contaminación automática (↓)	0.000	0.000	0.000	0.000
tiempo de evaluación (55 preguntas)	0,3 s	491 s	186 s	197 s
Pregunta de la Clase 1 (「AIE2026の講座の宿題にある「3レベル」とは何ですか？」):
`before`: inventó con seguridad. Dijo que AIE2026 es un centro irlandés y dio niveles genéricos (Level 1/2/3), el mismo error que Gemini en la Clase 1.
`after`: correcta (基礎・実装・発展, basta con hacer uno; F1 0,95 con la definición).
`rag`: correcta en contenido. El puntuador la marca parcial porque escribe 「講義内容の確認」 en lugar de 「基礎」.
`search`: correcta.
Revisión manual de los controles (el puntuador automático las marcó como `ok` y `regressed = []`, pero no lo son):
`general`, before → after:
「1から10までの合計」: 55 → 「300」 (incorrecto).
「日本の首都」: 東京 → 「東京。…本講座では第2回演習の地点」.
「こんにちは」: presentación normal → texto incoherente sobre "AIE2026" y "ツール".
Python: `list.reverse()` con ejemplo → solo `iter[::-1]`.
Total: 3 de 4 se degradaron.
`absent_real`: `before` explicó bien RLHF, MoE y DPO (Direct Preference Optimization). `after` respondió las 6 con definiciones inventadas en el estilo del glosario y con referencias al curso: DPO → 「本講座第3回の本線」, 知識蒸留 → 「本講座の第3回演習は知識蒸留の回」.
Mi métrica de "contaminación" (F1 ≥ 0,45 con una definición completa) no captó esto, porque el modelo no copia una definición entera: mezcla fragmentos y el tono del glosario. Es un límite de mi evaluación automática, y lo detecté solo leyendo las salidas.
ファインチューニングが向く場面・向かない場面についての考察：
Aprendió la frase, no el concepto. `after` reproduce la definición literal (F1 = 1,0) siempre que la pregunta contiene el nombre exacto del término, también con plantillas nuevas (`reworded` 16/16). Cuando el mismo término se escribe con un alias, baja a 5/10 y las respuestas fallidas son definiciones inventadas en el estilo del glosario (「オーバーフィッティング」→ un texto sobre "ツールセット"). El conocimiento quedó atado a la forma superficial del nombre que vio en el entrenamiento, como predice la Clase 2: FT es bueno para el comportamiento y malo para el conocimiento.
Sí añadió algo de conocimiento. En términos del curso, que el modelo base no puede saber, pasó de 0 % a 67 %. La pregunta de la Clase 1 quedó resuelta. Pero las respuestas `natural` parciales mezclan datos verdaderos con detalles inventados (「lec_03.pdf」, 「Haas/Code-Tester」).
Empeoró la alucinación en estilo y en alcance. Los términos ficticios ya se inventaban antes (6/6), pero `after` los inventa con el tono del glosario y citando el curso (「本講座の第2回演習ではハイパーLoRAを扱う」), lo que los hace más creíbles. Además "contaminó" términos reales que antes conocía (RLHF, DPO). Coincide con Gekhman et al. (2024): aprender hechos nuevos por FT aumenta las alucinaciones.
Olvido / sobreajuste (diapositiva 82): 3 de 4 preguntas generales se degradaron (1+…+10 = 300). Con 130 ejemplos de un solo formato y 10 épocas, el modelo responde todo como si fuera una definición del curso. Esto aparece solo si se mide lo que no debe romperse; mi `regressed` automático salió vacío y habría ocultado el problema.
Comparación con un sistema que busca en el glosario:
	entrenar (LoRA)	buscar (search / RAG)
Precisión con el nombre o un alias	100 % con el nombre, 50 % con alias	search 100 %, rag 90 %
Preguntas sin el término	2/5 + parciales con datos inventados	search falla (3/5 "no está"), pero no inventa
Términos inexistentes	inventa 6/6, con tono de autoridad	search devuelve un término parecido (5/6); rag inventa igual (el modelo de 0,8B no obedece "di que no está")
Conocimiento previo del modelo	se degrada (RLHF, DPO, aritmética)	intacto (`rag` respondió bien los controles)
Actualizar un término	reentrenar (~6 min de GPU) y reevaluar todo	editar `glossary.json`: efecto inmediato
Evidencia / fuente	no puede citarla	puede devolver el término usado
Costo por pregunta	prompt corto; respuestas cortas (197 s vs 491 s del modelo base)	prompt más largo (extracto), pero sin GPU de entrenamiento
Conclusión. Para un glosario que cambia y donde una respuesta inventada con tono oficial es peor que un "no sé", la base debe ser la búsqueda (RAG / agente con herramienta, Clases 3 y 5). Hay que mejorarla con búsqueda semántica para las preguntas `natural` y con una regla en código (sin resultado → no responder), porque la instrucción en el prompt no bastó con 0,8B. FT conviene para fijar cómo responder (formato, citar el término, `needs_review`) sobre lo que trae la búsqueda: FT + RAG, no FT en lugar de RAG. Lo que vi aquí es lo opuesto al ejercicio del FAQ: allí FT arregló el formato sin romper nada; aquí intentó meter conocimiento y rompió lo que el modelo ya sabía.
Límites:
Modelo de 0,8B y una sola corrida por condición (greedy, pero el entrenamiento en GPU no es del todo reproducible).
Un solo valor de épocas: con menos épocas quizá habría menos olvido.
Puntuación por palabras clave, que castiga paráfrasis correctas (p. ej. `rag` en la pregunta de la Clase 1), y una métrica de contaminación demasiado laxa.
Siguiente paso: probar `VARIANT="v2"` (ejemplos negativos y paráfrasis) para ver si FT puede enseñar a decir "no está" sin aumentar la negativa indebida, y añadir a la evaluación una comprobación de exactitud para las preguntas generales.