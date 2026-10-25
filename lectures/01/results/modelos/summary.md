# Resumen de la medición (modelos)

Fecha: 2026-10-25 22:59 UTC · repeticiones: 3

| modelo | pregunta | T | ok/n | lat. mediana (s) | lat. min–max (s) | entrada | salida | pensamiento | total | tok/s | caracteres |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | lora | default | 3/3 | 3.22 | 2.69–3.77 | 7 | 646.3 | 0 | 653.3 | 203.4 | 1235.3 |
| gemini-3.5-flash | lora | default | 3/3 | 11.46 | 11.23–47.10 | 7 | 637.7 | 1036.7 | 1681.3 | 107.8 | 1231 |
| gemini-3.1-flash-lite | lora | default | 2/3 | 5.49 | 2.97–8.02 | 7 | 689.5 | 0 | 696.5 | 157.6 | 1314.5 |
| gemini-3.5-flash-lite | curso | default | 3/3 | 2.47 | 2.27–2.47 | 21 | 510.7 | 0 | 531.7 | 212.5 | 983.3 |
| gemini-3.5-flash | curso | default | 2/3 | 13.31 | 13.29–13.34 | 21 | 573.5 | 1302 | 1896.5 | 140.8 | 1089 |
| gemini-3.1-flash-lite | curso | default | 3/3 | 27.37 | 4.06–52.41 | 21 | 650.3 | 0 | 671.3 | 65.4 | 1244 |
| gemini-3.5-flash-lite | largo | default | 3/3 | 4.09 | 3.49–4.53 | 15 | 1181 | 0 | 1196 | 294.1 | 2310.3 |
| gemini-3.5-flash | largo | default | 3/3 | 18.27 | 17.58–23.92 | 15 | 1870 | 1423.3 | 3308.3 | 167.4 | 3788 |
| gemini-3.1-flash-lite | largo | default | 3/3 | 13.85 | 3.62–32.46 | 15 | 914.3 | 0 | 929.3 | 111.0 | 1812.3 |

## Relación con la cuota gratuita

- Llamadas realizadas: 27 (ok: 25, respuestas 429: 0)
- Pausa entre llamadas: 5 s → ritmo máximo ≈ 12 llamadas/min (sin contar la latencia)
- Tokens por llamada: media 1284, máximo 3557

(Pasa --rpm/--tpm/--rpd con los límites de tu cuenta para que se calcule el margen.)
