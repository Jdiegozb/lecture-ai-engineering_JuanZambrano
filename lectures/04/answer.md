# 第4回 解答

## 演習

- 基準別の一致率（直す前）：根拠　/　、範囲　/　、ヒント　/　、分かりやすさ　/　、回の表示　/　
- 要確認の件数（直す前）：
- 直した基準と、書き足した方針：
- 基準別の一致率と要確認の件数（直した後）：
- 講師のラベルと自分のラベルで判定が違った項目と、そう判定した理由：
- 気づき・疑問：

## 演習

- 基準別の一致率（直す前）：根拠　7/9（+1 unsure）、範囲　10/10、ヒント　10/10、分かりやすさ　9/10、回の表示　8/10（código）. Total 7/9, coverage 90 %. Juez: `gemini-3.1-flash-lite` (`gemini-3.5-flash-lite` daba 503 repetidamente).
- 要確認の件数（直す前）：**1** — #05 根拠 (RAG no está en el glosario; la agente lo dice y luego da una explicación general = el punto de 「まだ決めていないこと」).
- 直した基準と、書き足した方針：
  - Decidí **pass**: decir 「用語集にはない」 y luego explicar en general **no** es afirmar por suposición; el usuario sabe qué parte no viene del glosario.
  - Añadí bajo 根拠: `- 用語集にない語を、「用語集にはない」と伝えたうえで一般的に説明するのは、断定ではない（pass）` y borré ese punto de 「まだ決めていないこと」. Un solo cambio.
- 基準別の一致率と要確認の件数（直した後）：根拠　9/10、範囲　10/10、ヒント　10/10、分かりやすさ　9/10、回の表示　8/10. Total **8/10**, coverage **100 %**, 要確認 **0**. #05 pasó de unsure a pass (coincide conmigo). Mismo modelo antes y después.
- 講師のラベルと自分のラベルで判定が違った項目と、そう判定した理由：
  - Solo **#07 y #09 回の表示** (profesor fail, yo pass). Las respuestas no terminan en 「第N回」 (#07 dice 「関係する回：なし」; #09 no tiene línea), pero la pregunta (clima / entrada vacía) no pertenece a ninguna sesión, así que no mostrar una sesión me parece el comportamiento correcto. La regla de código es demasiado rígida para preguntas fuera del curso; el profesor lo anota como 「規則が硬い例」.
  - El profesor marcó «迷った» en #04, #05 y #07; yo en ninguno.
- 気づき・疑問：
  - **Mezcla de criterios**: el juez reprobó 根拠 en #08 (y en #06 antes del cambio) por obedecer la petición o dar el código, fallos que ya cuentan en 範囲 y ヒント, aunque la rúbrica dice 「基準は 1 つずつ独立に見る」. Con el acuerdo solo, esto parece un fallo de la agente en 根拠 que no existe.
  - **#04 分かりやすさ**: el juez no detectó la repetición (「つまり…」) pese a que la rúbrica la pone como ejemplo de fail. Lo subjetivo es lo que más se separa.
  - **Unsure no es un defecto del juez**: venía de un punto que la rúbrica no decidía; al decidirlo yo, desapareció. Definir la política es trabajo de quien diseña la evaluación.
  - Además del cambio de rúbrica cambió algo más: #06 根拠 dejó de ser falsa alarma. Con `temperature=0` el juez también puede variar; con 10 casos no puedo separar el efecto del cambio del de la variación.
