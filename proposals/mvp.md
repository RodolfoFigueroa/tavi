# MVP: Asistente inteligente para consultar datos urbanos en lenguaje natural

Este documento presenta el MVP desde una perspectiva institucional y de producto: qué problema resuelve, cómo apoyará a las plataformas existentes del Centro para el Futuro de las Ciudades, qué riesgos controla y cómo se medirá su éxito. El detalle técnico de implementación se conserva en [arquitectura.md](arquitectura.md).

## 1. Resumen ejecutivo

El MVP permite que una persona haga preguntas en español sobre indicadores territoriales, sociales y urbanos, y reciba una respuesta clara basada en datos verificables. La herramienta se implementará en el Centro para el Futuro de las Ciudades y utilizará datos, metodologías analíticas y criterios producidos por el propio Centro.

Su función será apoyar proyectos y plataformas existentes del Centro, incorporando una capa conversacional que ayude a personas no expertas a entender información urbana compleja sin tener que aprender conceptos técnicos o pedir análisis manuales para cada pregunta.

La propuesta combina tres elementos clave para crear valor institucional: acceso más claro a información urbana, controles de seguridad antes de consultar los datos y flexibilidad para operar con modelos comerciales o de código abierto. El objetivo del MVP no es reemplazar los procesos analíticos avanzados del Centro, sino ampliar su alcance mediante una interfaz comprensible, trazable y reutilizable en distintos proyectos.

## 2. Problema y oportunidad

El Centro para el Futuro de las Ciudades produce datos, metodologías e indicadores que ayudan a entender fenómenos urbanos complejos. Sin embargo, cuando esa información llega a plataformas públicas o de consulta general, muchas personas no expertas pueden tener dificultad para interpretar tablas, indicadores o conceptos técnicos.

La oportunidad es crear una capa inteligente entre las plataformas del Centro y sus usuarios finales. Esta capa permitiría que una persona común explore información territorial con preguntas naturales, sin tener que aprender conceptos técnicos, sin conocer la estructura interna de los datos y sin recibir respuestas desconectadas de las metodologías del Centro.

Para el Centro, el valor está en convertir capacidades analíticas existentes en experiencias más accesibles. Esto puede fortalecer proyectos de divulgación, diagnóstico urbano, toma de decisiones, participación ciudadana y comunicación de evidencia.

## 3. Propuesta de valor

El MVP busca demostrar los siguientes beneficios:

1. Acceso más claro: traducir indicadores técnicos a respuestas entendibles para personas no expertas.
2. Entrega de datos puros: conectar las respuestas narrativas con un payload de datos estructurados (JSON) utilizable por las plataformas.
3. Mayor adopción: permitir que usuarios de plataformas existentes consulten datos complejos con preguntas en lenguaje natural.
4. Seguridad operativa: limitar el sistema a consultas de lectura sobre datos autorizados.
5. Trazabilidad: conservar la pregunta, la consulta ejecutada y los resultados para auditoría.
6. Reutilización institucional: crear una capacidad que pueda integrarse en distintos proyectos del Centro sin construir una herramienta aislada para cada caso.

## 4. Cómo funciona

El flujo esperado para el usuario es directo:

1. La persona entra a una plataforma existente del Centro y hace una pregunta en español sobre una zona, indicador o comparación territorial.
2. El sistema identifica el área geográfica, los conceptos relevantes y el proyecto del Centro al que pertenece la consulta.
3. El asistente prepara una consulta controlada sobre las vistas de datos autorizadas para esa plataforma.
4. Antes de consultar la base, el sistema revisa que la solicitud sea segura y que solo lea información permitida.
5. Si la consulta es válida, se ejecuta en DuckDB en memoria y se devuelve una respuesta clara, acompañada con una síntesis de los resultados estadísticos.

Si el sistema detecta una solicitud insegura, ambigua o fuera del alcance del MVP, la bloquea o solicita reformularla sin exponer detalles internos de la base de datos.

## 5. Qué datos puede consultar

El MVP está pensado para trabajar con información territorial y urbana descriptiva previamente preparada por el Centro:

* Indicadores sociodemográficos y censales.
* Datos agregados de económicos y financieros.
* Índices de accesibilidad urbana a empleo y servicios esenciales.

El asistente no consulta las tablas originales del sistema. Solo accede a vistas analíticas de lectura, diseñadas para exponer información útil sin abrir acceso innecesario a la estructura interna de datos o a metodologías que no correspondan al proyecto en curso.

## 6. Seguridad, privacidad y control de riesgos

El enfoque de seguridad del MVP se basa en mitigación por capas:

* Acceso limitado: el asistente solo puede consultar vistas autorizadas y no tiene permisos para modificar datos.
* Revisión previa: cada consulta se revisa antes de ejecutarse para confirmar que sea una lectura permitida.
* Bloqueo de operaciones riesgosas: se rechazan intentos de borrar, modificar, exportar información o acceder a archivos del servidor.
* Respuestas controladas: los errores se comunican con mensajes simples, sin revelar metadatos internos sensibles.
* Auditoría: cada interacción queda asociada a un identificador de traza para revisar qué ocurrió y qué resultado se entregó.

El MVP no asume seguridad perfecta por declaración. La seguridad se validará con una batería inicial de pruebas adversariales, incluyendo solicitudes maliciosas, instrucciones de manipulación de datos y preguntas fuera del alcance permitido.

## 7. Alcance del MVP

**Lo que el MVP *sí* puede hacer:**

* Responder preguntas en español sobre datos urbanos autorizados.
* Convertir preguntas de personas no expertas en consultas verificables.
* Validar seguridad antes de ejecutar consultas.
* Entregar una respuesta narrativa sustentada en resultados verificables.
* Generar estadísticas para comparar el desempeño de modelos comerciales y modelos de código abierto cuando sea necesario para decidir la estrategia de operación.

**Lo que el MVP *no* puede hacer:**

* Editar, cargar o borrar datos desde la interfaz conversacional.
* Integrarse con brokers de mensajería (Redis) o disparar eventos de renderizado cartográfico en tiempo real.
* Ejecutar análisis predictivos o proyecciones.
* Consultar fuentes externas no autorizadas.
* Permitir carga libre de archivos por parte del usuario.

## 8. Ejemplos de uso

**Pregunta:** "¿Qué zonas tienen menor acceso a empleo?"

**Respuesta esperada:** El sistema identifica las zonas con menor índice de accesibilidad laboral dentro del proyecto consultado, las ordena por nivel de rezago y entrega una explicación breve sobre los patrones encontrados.

**Pregunta:** "¿Dónde hay alta vulnerabilidad y bajos ingresos?"

**Respuesta esperada:** El asistente combina indicadores sociales y económicos autorizados por la metodología del Centro para señalar áreas prioritarias, mostrando los criterios usados para clasificar cada zona.

**Pregunta:** "Compara accesibilidad a servicios entre dos zonas."

**Respuesta esperada:** El sistema devuelve una comparación tabular y narrativa de los indicadores disponibles, destacando diferencias relevantes sin inventar información fuera de los datos.

## 9. Métricas de éxito del MVP

El éxito del MVP se evaluará con métricas claras:

* Precisión de la inferencia: El sistema se considerará exitoso si el modelo de código abierto (Qwen 2.5-Coder) logra una precisión de ejecución $\ge 85\%$ en los resultados tabulares devueltos, evaluado contra un conjunto de prueba estático (Golden Dataset) de 50 preguntas complejas redactadas y validadas en comparación con la línea base comercial (LLMs comerciales).
* Tasa de autocorrección: Al menos el 80% de los errores sintácticos menores detectados en el primer intento deben ser resueltos de forma autónoma por el grafo agéntico en su segundo o tercer intento, respetando el límite estricto de 3 reintentos.
* Efectividad del bloqueo: Garantía del 100% de efectividad en el rechazo y bloqueo de consultas maliciosas, destructivas o ajenas a comandos `SELECT` de solo lectura mediante el interceptor del AST antes de que toquen el motor DuckDB.
* Tiempo de respuesta: Duración promedio menor a 10 segundos desde la formulación de la pregunta del usuario hasta la entrega del payload final de respuesta en condiciones normales de operación.

El respaldo técnico de esta propuesta se encuentra en [arquitectura.md](arquitectura.md).
