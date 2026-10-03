# Fallas generales por cliente durante el Mundial 2026

El proyecto compara las fallas generales asociadas a clientes entre el **11 de junio y el 19 de julio de 2026**, ambos incluidos, y las mismas fechas de **2024 y 2025**. Genera comparaciones por cliente, por día, por periodo completo y por ventana de partido, a escala nacional y por entidad, hub y plaza.

## Organización y dependencias

Utilizo un único `requirements.txt` en la raíz para el análisis, la descarga, el EDA,
la revisión y el kernel del notebook. La estructura vigente es:

```text
main.py
config.json
requirements.txt
scripts/
  descargar_datos.py
src/
  analisis.py
  descarga.py
proyecto/
  proyecto_final_mineria_de_datos.ipynb
  eda.py
  revision.py
  validar_proyecto.py
  recursos/
  historico/
pruebas/
```

Conservo las versiones anteriores de notebooks, utilidades, dependencias y figuras en
`proyecto/historico/`. Son documentación opcional: el análisis, el EDA, la revisión,
el validador y las celdas del notebook actual no importan ni leen esos archivos.
Los archivos de dependencias del histórico no intervienen en la instalación vigente.

## Entradas públicas y descarga automática

`python main.py` descarga con `gdown` los CSV públicos que falten y después ejecuta el análisis. La configuración lee esta estructura:

```text
raw_data/
  region_y_calendario/
    calendario_partidos_2026.csv
    Dataset_Dim_Region.csv
  fallas_clientes/
    remedy_fallas_clientes_filtro_1.csv
    ...
    remedy_fallas_clientes_filtro_64.csv
  fallas_generales/
    Dataset_Fallas_Generales_Historia_2024.csv
    Dataset_Fallas_Generales_Historia_2025.csv
    Dataset_Fallas_Generales_Historia_2026.csv
```

Se descargan **69 archivos** desde las carpetas públicas indicadas en `fuentes_drive` de `config.json`:

- [Región y calendario](https://drive.google.com/drive/folders/19JTsHrBjNzTM80EUv2xZV1psnpmMrU2H): dos CSV.
- [Fallas generales](https://drive.google.com/drive/folders/18zdTVbbvwNwbSc9ahTIlc24zj1-vLsPG): tres CSV, uno por año.
- [Fallas de clientes](https://drive.google.com/drive/folders/1P3LONAgB2aJTMoK1Jyr1dlMkdX7nG3_2): las 64 partes filtradas.

El nombre del calendario en Drive es `calendario_partidos_2026.csv`. El descargador también admite `caldenario_partidos_2026.csv` y lo guarda con el nombre correcto.

El descargador consulta la lista completa antes de transferir archivos, comprueba los nombres esperados y valida los encabezados. Usa `gdown==6.4.1`, cuya consulta de carpetas permite recuperar las 64 partes. No necesita iniciar sesión ni lee las cookies personales del navegador: conserva únicamente la sesión anónima de descarga en `raw_data/.gdown_cookies.txt`, sin usar la caché personal de gdown. Los CSV existentes con encabezados válidos se reutilizan; si están todos, no se consulta Drive. Las transferencias incompletas se reanudan y los errores transitorios se reintentan hasta tres veces. La validación de encabezados no sustituye una comprobación de integridad de todo el contenido.

Las transferencias identifican al cliente como `proyecto-mundial-anomalias/1.0` mediante el parámetro `user_agent` de gdown. En la comprobación real, Drive rechazó con HTTP 403 el navegador Chrome 39 que la librería anuncia por defecto para algunos archivos, aunque eran públicos. Usar el identificador del proyecto permitió descargarlos manteniendo reanudación, reintentos y acceso anónimo.

Si Drive rechaza una transferencia por permisos o cuota, el programa continúa con los otros archivos y al final informa las descargas pendientes. El análisis no comienza hasta disponer de todas las fuentes. Al volver a ejecutar, conserva las descargas terminadas y continúa las pendientes. Si un archivo local tiene un encabezado inválido, revisa o retira ese archivo para descargarlo de nuevo; no se reemplaza automáticamente un CSV existente con contenido inválido.

El análisis exige las 64 partes y las tres particiones por año. Detecta partes faltantes, duplicadas, años adicionales y columnas requeridas ausentes. Comprueba que las fechas de las particiones generales correspondan al año del nombre. Reconoce encabezados sin distinguir mayúsculas y admite coma, barra vertical, punto y coma o tabulador. Las entradas no se modifican durante el análisis.

`modo_fuentes` debe ser `filtrado`. Los CSV públicos ya están filtrados: no hace falta ejecutar un notebook ni acceder a la historia original. La dimensión y el calendario se leen desde `raw_data/region_y_calendario/`; el calendario contiene 104 partidos y determina las ventanas de análisis.

## Comparación y conteos

Se enlazan los CSV de clientes con las fallas generales mediante `WIDMT_INCIDENCIA_REMEDY`, y con la dimensión territorial mediante `WIDDIM_REGION`. Las afectaciones sin falla general correspondiente **se excluyen de los resultados** y se cuantifican en `control_calidad.json`. El análisis usa la fecha de afectación al cliente; la fecha de envío de la falla general sirve para conciliar las horas de ambas fuentes.

- `CLIENTES_DISTINTOS`: clientes afectados distintos dentro del intervalo y territorio.
- `INCIDENCIAS_DISTINTAS`: fallas generales distintas asociadas a esos clientes.
- `MAC_DISTINTAS`: dispositivos distintos con MAC informada.
- `FALLAS_CLIENTE`: combinaciones distintas cliente–incidencia. Un cliente con dos fallas cuenta dos; varias MAC para la misma falla cuentan una sola combinación.
- `FALLAS_PROMEDIO_POR_CLIENTE`: combinaciones cliente–incidencia divididas entre clientes afectados; no mide la tasa sobre todos los clientes activos.

El total nacional se calcula por separado. El total del periodo vuelve a contar clientes y fallas distintos en todo el intervalo: no suma los conteos diarios, territoriales ni de partidos.

Por partido se compara la misma fecha y hora local de 2026 con 2024 y 2025, desde 30 minutos antes hasta 180 minutos después del inicio. No se ajusta al mismo día de la semana, ni se usan mayo o agosto de 2026 como referencia. El fin de cada ventana es exclusivo. Las comparaciones diarias usan días completos; la comparación del periodo incluye los 39 días del torneo y evita duplicaciones por partidos superpuestos.

Los resultados contienen los conteos de cada año, sus diferencias absolutas, las variaciones porcentuales frente a cada año y frente al promedio histórico. La variación es `100 * (valor_2026 - referencia) / referencia`. Si la referencia es cero, el porcentaje queda vacío, y la diferencia absoluta sigue disponible. Un cliente que solo aparece en un año tiene cero fallas registradas en los otros años cuando la cobertura de esos periodos está disponible; esto no demuestra que tuviera servicio activo en esos años.

## Fechas y calidad

El filtro previo conserva del 10 de junio al 20 de julio. El programa selecciona de ese extracto los intervalos locales necesarios en cada año, sin mezclar los años intermedios ni usar los días adicionales como controles.

`FECHA_INCIDENCIA` conserva el timestamp UTC del SQL de clientes; se convierte a `America/Mexico_City`. `FECHA_ENVIO` de fallas generales ya está en hora de México. La auditoría compara una muestra enlazada y detiene la ejecución si más del 1 % difiere por más de un minuto. Se conserva esta interpretación de zonas horarias porque el notebook únicamente filtra las filas.

`control_calidad.json` informa por año los días sin clientes, sin fallas generales o sin cruce; incluye conteos diarios, filas incompletas, incidencias y filas sin falla general correspondiente. Se detiene ante regiones sin correspondencia en la dimensión. Con `exigir_dias_completos: true`, también se detiene ante días sin datos o cruce en cualquiera de los tres años. La presencia de registros cada día es una comprobación de cobertura, no una garantía de que el extracto está completo. Un día sin registros puede ser ausencia de fallas o falta de datos y requiere revisión.

Si se desactiva esa exigencia, las comparaciones con cobertura faltante muestran campos vacíos y `COBERTURA_COMPLETA=False`; no convierten ausencia de datos en cero. El promedio histórico requiere cobertura de ambos años.

## Detección de anomalías

El evaluador KNN utiliza clientes, incidencias y MAC distintos. Cada partido tiene
**dos referencias históricas**, una por año. La configuración vigente tiene
`minimo_ventanas_comparables: 2` y `k_vecinos_distancia: 1`: permite calcular las
clasificaciones, pero no acredita precisión ni significancia estadística. La revisión
documentada del 2 de octubre produjo 6.393 alertas; una nueva ejecución calcula su
propio resultado. La configuración anterior de mínimo seis referencias y k=3 devolvía
`SIN_BASE` porque disponía únicamente de dos controles.

`SIN_BASE` significa referencia insuficiente para el algoritmo, no ausencia de fallas. Los percentiles descriptivos que puedan aparecer con dos controles no constituyen una base suficiente para una alerta estadística. Un aumento frente al histórico tampoco prueba que el Mundial haya causado la falla.

## Ejecución

Requiere Python 3.11 o posterior; verifico la instalación conjunta con Python 3.13.
En Windows, desde la raíz del proyecto, utilizo un entorno virtual de ruta corta.
En este checkout, instalar el kernel en `.venv` produjo un error real de longitud
de rutas en `debugpy`; el entorno siguiente evita ese problema:

```powershell
python -m venv "$env:TEMP\mundial_mineria_venv"
& "$env:TEMP\mundial_mineria_venv\Scripts\python.exe" -m pip install -r requirements.txt
& "$env:TEMP\mundial_mineria_venv\Scripts\python.exe" -m pip check
& "$env:TEMP\mundial_mineria_venv\Scripts\python.exe" main.py
& "$env:TEMP\mundial_mineria_venv\Scripts\python.exe" proyecto/eda.py
& "$env:TEMP\mundial_mineria_venv\Scripts\python.exe" proyecto/revision.py
& "$env:TEMP\mundial_mineria_venv\Scripts\python.exe" proyecto/validar_proyecto.py --exigir-resultados
```

En VS Code selecciono como intérprete y kernel
`%TEMP%\mundial_mineria_venv\Scripts\python.exe`. Así, Code Runner y el notebook
pueden utilizar el entorno donde están instaladas las dependencias; ejecutar con otro
intérprete puede producir errores de módulos ausentes.

En Linux/macOS puedo crear `.venv` con `python3 -m venv .venv`, instalar mediante
`.venv/bin/python -m pip install -r requirements.txt` y ejecutar los mismos scripts
con `.venv/bin/python`.

El EDA genera dos figuras en PNG/SVG, `perfil_eda.json` y `manifiesto_eda.json` en
`proyecto/recursos/`. La revisión recalcula la aritmética, las clasificaciones, la
selección de alertas, la recurrencia por cliente y diez escenarios de sensibilidad;
exporta `resumen_revision.json`, `sensibilidad_detector.csv` y `manifiesto_fuentes.json`
en esa misma carpeta. Lee el CSV por cliente en flujo y no necesita los JSON de
interpretaciones anteriores. Los cálculos no dependen de documentos de requisitos.

Si elimino `raw_data` y `resultados`, ejecuto primero `main.py` para descargarlos y
reconstruirlos. Después puedo ejecutar el EDA y la revisión. El notebook conserva
las cifras e interpretaciones guardadas de la revisión del 2 de octubre; volver a
ejecutar sus celdas recalcula las tablas desde las salidas disponibles, sin actualizar
automáticamente las conclusiones redactadas.

Para descargar los datos sin iniciar el análisis:

```powershell
& "$env:TEMP\mundial_mineria_venv\Scripts\python.exe" scripts/descargar_datos.py
```

Para comprobar los nombres e IDs de los archivos públicos sin transferir los CSV:

```powershell
& "$env:TEMP\mundial_mineria_venv\Scripts\python.exe" scripts/descargar_datos.py --listar
```

`descargar_datos: true` habilita la preparación automática desde `main.py`. Con `false`, el análisis exige que las entradas configuradas ya estén disponibles y no accede a la red. `scripts/descargar_datos.py` funciona de forma independiente de ese indicador y también admite `python -m scripts.descargar_datos`. Las rutas de datos se resuelven respecto a `config.json`, no respecto al directorio desde el que se invoca Python.

`requirements.txt` fija seis dependencias directas: `gdown` para Drive, `tzdata` para
las zonas horarias, `matplotlib` para las figuras, `ipykernel` para ejecutar celdas,
`nbformat` para validar notebooks y `nbclient` para su ejecución automatizada.
Pip instala sus dependencias transitivas, incluido NumPy. SQLite, CSV, JSON y el
evaluador KNN utilizan la biblioteca estándar. No necesito pandas ni scikit-learn
para el flujo vigente.

El procesamiento usa Python y SQLite estándar, lectura por flujo y lotes de 10,000 filas. No carga los CSV completos en RAM. `resultados/_indice_temporal.sqlite` guarda los registros seleccionados; los índices, agrupaciones y conteos distintos requieren espacio en disco. Cada ejecución reconstruye el índice y reemplaza los resultados derivados.

Reserva espacio para los CSV y para el índice SQLite, además de los resultados. La primera descarga requiere conexión y acceso público habilitado en las tres carpetas. La disponibilidad y las cuotas dependen de Google Drive. Si el contenido público cambia, podría cambiar la reproducción; para fijar una versión exacta conviene publicar también un manifiesto de tamaños y hashes.

El análisis reutiliza los conteos por intervalo y las evaluaciones de horarios
simultáneos, conservando los conteos distintos nacionales por separado.

## Resultados

| Archivo en `resultados/` | Contenido |
| --- | --- |
| `fallas_generales_por_cliente.csv` | Una fila por cliente: fallas distintas en 2024, 2025 y 2026, diferencias y variaciones frente a cada año y al promedio histórico. |
| `comparacion_periodo_zona.csv` | Comparación del periodo completo por territorio y nacional. |
| `comparacion_diaria_zona.csv` | Comparación de cada fecha local con la misma fecha histórica. |
| `comparacion_por_partido_zona.csv` | Comparación de cada ventana de partido con la misma fecha/hora en ambos años. |
| `anomalias_por_partido_zona.csv` | La misma comparación por partido, conservando el nombre anterior y las columnas del evaluador. |
| `alertas_ordenadas.csv` | Candidatos KNN que cumplen las reglas vigentes, ordenados por exceso de clientes. |
| `detalle_clientes_alertados.csv` | Identificadores de afectaciones vinculadas a los candidatos; las ventanas pueden repetir observaciones. |
| `control_calidad.json` | Archivos utilizados, cobertura por año, cruces y conciliación temporal. |
| `resumen_ejecucion.json` | Periodo, años comparados, definiciones y conteos de resultados. |

Ejecuta `main.py` para regenerar los resultados desde las entradas configuradas. Los CSV de clientes contienen identificadores y deben manejarse con los mismos permisos que las fuentes.

## Validación

```powershell
& "$env:TEMP\mundial_mineria_venv\Scripts\python.exe" -m unittest discover -s pruebas -v
```

Las pruebas usan archivos sintéticos: las 64 partes filtradas, los tres años, comparación exacta de fechas, conversión UTC y extremos de intervalo, deduplicación de clientes y MAC, varias fallas por cliente, total nacional independiente, histórico incompleto y exclusión de incidencias sin cruce. También verifican que el modo antiguo se rechace antes de abrir datos y mantienen las pruebas del lector de campos largos y del evaluador KNN. Las pruebas de descarga simulan Google Drive y comprueban las 64 partes, archivos faltantes, duplicados, reutilización sin red, encabezados inválidos, fallos de transferencia y reanudación.

La comprobación de entradas valida los encabezados y el calendario; no recorre toda la data ni regenera los resultados reales. `raw_data/`, `resultados/` y `.venv/` quedan excluidos de Git para compartir el código sin incluir datos voluminosos ni resultados derivados.
