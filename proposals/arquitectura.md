# Arquitectura técnica del MVP Text-to-SQL

Este documento es el respaldo técnico del MVP descrito en [mvp.md](mvp.md). Su objetivo es conservar las decisiones de arquitectura necesarias para implementar el asistente como una capacidad integrada a plataformas existentes del Centro para el Futuro de las Ciudades, sin cargar el documento ejecutivo con detalles de infraestructura.

## 1. Alcance técnico y entorno de datos

El MVP implementa un flujo agéntico que traduce consultas en lenguaje natural a sentencias SQL para DuckDB ejecutado en memoria. El sistema está diseñado para usuarios no técnicos de plataformas existentes del Centro, pero mantiene un ciclo de validación sintáctica, validación de seguridad y autocorrección antes de ejecutar cualquier consulta física.

A nivel operativo, el sistema interactúa con un modelo de datos relacional y geoespacial que consolida variables sociodemográficas, censales, ingresos per cápita e índices de accesibilidad urbana a empleo y servicios esenciales producidos o curados por el Centro. La capa agéntica queda desacoplada de la capa de datos: DuckDB no expone tablas base al asistente, sino vistas analíticas de solo lectura definidas para cada plataforma o proyecto. El resultado final entregado al backend consiste en una respuesta narrativa y un objeto de datos tabular estructurado.

## 2. Flujo agéntico protegido

El flujo se estructura como un grafo de trabajo con retroalimentación activa:

* Extracción de área y contexto: delimita la frontera geográfica especificada por el usuario y recupera las subdivisiones espaciales necesarias desde el backend.
* Contexto de plataforma y proyecto: identifica desde qué plataforma del Centro llega la solicitud y qué conjunto de vistas, indicadores y reglas metodológicas aplica.
* Generación del SQL candidato: el LLM interpreta la pregunta, el esquema expuesto y el glosario de dominio para proponer una consulta analítica.
* Validación sintáctica: la consulta se analiza con un parser SQL, como sqlglot. Si falla, el error se devuelve al agente generador para un ciclo de autocorrección.
* Interceptor de seguridad: se valida que la consulta sea de lectura, que opere solo sobre vistas permitidas y que no use funciones bloqueadas.
* Ejecución aislada y síntesis: una consulta aprobada se ejecuta en DuckDB y los resultados se pasan a un modelo de síntesis para generar una respuesta narrativa en español.

El ciclo de autocorrección tendrá un límite estricto de 3 reintentos antes de abortar de forma segura.

## 3. DuckDB, vistas y guardrails

La seguridad se apoya en tres capas principales:

* Principio de mínimo privilegio: el LLM solo recibe acceso a vistas analíticas de lectura. Las tablas base permanecen fuera del contexto del asistente.
* Aislamiento por proyecto: cada plataforma debe exponer únicamente las vistas, indicadores y reglas que correspondan a su caso de uso.
* Auditoría del árbol de sintaxis: el interceptor analiza la estructura lógica de la consulta y rechaza cualquier raíz que no corresponda a una consulta SELECT permitida.
* Bloqueo anti-exfiltración: se vetan comandos y funciones asociados a exportación, lectura de archivos locales, nubes externas o extensiones de red no autorizadas.

Ejemplos de operaciones bloqueadas:

* Escrituras o modificaciones: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`.
* Exportación: `COPY TO` u operaciones equivalentes.
* Acceso a archivos o red: `read_csv`, `read_parquet`, `httpfs` u otras funciones no autorizadas.

El objetivo técnico es impedir que una consulta generada por el modelo tenga contacto con datos o capacidades fuera del perímetro autorizado antes de llegar al motor DuckDB.

## 4. Modelos de inferencia intercambiables

La arquitectura permite conectar distintos proveedores mediante una fábrica de modelos:

* Modelos comerciales: APIs propietarias de alto rendimiento, como OpenAI o Anthropic, usadas como línea base de precisión y validación.
* Modelos de código abierto: familia Qwen 2.5-Coder en variantes Instruct de 7B o 32B, evaluada por su desempeño en tareas Text-to-SQL y por su potencial de reducción de costos.

Modalidades previstas para modelos abiertos:

* Hugging Face Serverless API para una puesta en marcha rápida.
* Dedicated Endpoints para producción con cómputo dedicado.
* Servidores locales con vLLM u Ollama para escenarios que requieran procesamiento on-premise.

Para el MVP se recomienda operar con un modelo principal y un modelo comercial de referencia, evitando implementar todas las modalidades al mismo tiempo.

## 5. Contexto de dominio, prompts y esquema

Para mejorar la comprensión de conceptos regionales, el sistema inyecta contexto controlado al modelo:

* Esquema de vistas comentado: el DDL expuesto al LLM incluye descripciones de columnas, unidades, formatos y significado de indicadores.
* Glosario semántico: el prompt contiene un diccionario de conceptos de dominio que traduce términos de usuario a filtros o rangos permitidos.
* Contexto metodológico del Centro: cada integración puede incluir reglas analíticas, definiciones de indicadores y advertencias interpretativas específicas del proyecto.
* Reglas de respuesta: el modelo de síntesis debe explicar resultados apoyándose en los datos devueltos, sin inventar conclusiones no sustentadas.

Ejemplo conceptual: una expresión como "alta vulnerabilidad" debe mapearse a rangos definidos en el glosario, no a interpretaciones libres del modelo.

## 6. Telemetría, logging y auditoría

Cada solicitud debe generar un identificador de traza que agrupe:

* Pregunta original.
* Plataforma y proyecto de origen.
* Proveedor de inferencia seleccionado.
* SQL candidato y errores de validación, si existen.
* Intentos de autocorrección.
* SQL final ejecutado.
* Evento cartográfico publicado, cuando aplique.
* Tiempo de respuesta.
* Código de error, cuando aplique.

Los logs deben estructurarse en JSON para facilitar auditoría, depuración y medición del desempeño del MVP.


## 7. Métricas de éxito del MVP

Se establecen tres métricas clave y medibles para validar la viabilidad de la arquitectura antes de su paso a producción:

* Precisión de la inferencia: Ejecución automatizada sobre el Golden Dataset de 50 preguntas complejas de dominio regional. El modelo open-source (Qwen 2.5-Coder) debe alcanzar una precisión de ejecución $\ge 85\%$ en la coincidencia exacta de los resultados tabulares devueltos frente a la solución humana experta y el benchmark comercial (LLMs comerciales).
* Tasa de autocorrección: Eficiencia del bucle circular en LangGraph $\ge 80\%$ en la resolución autónoma de excepciones sintácticas levantadas por el linter o DuckDB, aplicando un límite estricto de hasta 3 reintentos antes de disparar una respuesta controlada.
* Efectividad del bloqueo: Tolerancia cero a vulnerabilidades. Efectividad del 100% en la interceptación y denegación de consultas maliciosas (ej. inyecciones SQL) u operaciones prohibidas detectadas a nivel de AST por sqlglot antes de ser enviadas a la memoria de DuckDB.
* Tiempo de respuesta: Monitoreo del ciclo completo del grafo para mantener una latencia media por debajo de los 10 segundos en condiciones estándar de red e inferencia.