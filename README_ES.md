# NerdMiners_Public_Pool_Stats Bot
---
- 🇺🇸 [English](https://github.com/function0xMarki/NerdMiners_Public_Pool_Stats/blob/main/README.md) | 🇪🇸 [Español](https://github.com/function0xMarki/NerdMiners_Public_Pool_Stats/blob/main/README_ES.md)
---

Bot de Telegram que monitoriza tus NerdMiners de Bitcoin en [public-pool.io](https://web.public-pool.io) y envía estadísticas y alertas inteligentes a un grupo de Telegram.

## Características

- **Monitorización de mineros**: Hashrate *(instantáneo + media 24h)*, mejor dificultad *(sesión + histórico)*, tiempo de actividad, estado online/offline
- **Estadísticas del pool**: Hashrate total, cantidad de mineros, tu porcentaje de contribución
- **Estadísticas de la red Bitcoin**: Altura del bloque actual, dificultad, hashrate de la red
- **Alertas inteligentes**: Desconexión detectada, hashrate bajo *(vs media 24h)*, nuevos récords personales, mineros nuevos/desaparecidos, bloque encontrado por el pool
- **TOP 3 BD**: Registra el top 10 de las mejores dificultades alcanzadas a lo largo de todas las sesiones, mostrando el top 3 en el mensaje de estadísticas
- **Mensaje fijado auto-actualizado**: Un único mensaje de estadísticas se mantiene fijado y actualizado en el grupo; las notificaciones de fijado se eliminan automáticamente para mantener el chat limpio
- **Identificación de workers**: Gestiona automáticamente múltiples mineros con el mismo nombre en la API *(ej: los NerdMiners antiguos que todos reportan como "worker" sin posibilidad de personalizarse)*
- **Almacenamiento SQLite**: Historial eficiente de 90 días para promedios de hashrate y seguimiento de sesiones *(modo WAL para fiabilidad)*
- **Backups automáticos**: Copias de seguridad cada 24h de la base de datos con retención de 30 días.

## Requisitos previos

- Python 3.10 o superior
- pip *(gestor de paquetes de Python)*
- Una cuenta de Telegram
- Una dirección de Bitcoin minando en [public-pool.io](https://public-pool.io)

## Configuración del Bot de Telegram

Sigue estos pasos cuidadosamente para crear y configurar tu bot de Telegram.

### 1. Crear el Bot

1. Abre Telegram y busca **@BotFather**
2. Envía el comando `/newbot`
3. Elige un **nombre** para tu bot *(ej: "NerdMiners Monitor")*
4. Elige un **nombre de usuario** para tu bot *(debe terminar en `bot`, ej: `my_nerdminers_bot`)*
5. BotFather te dará un **Bot Token** — guárdalo, lo necesitarás después
> **Documentación oficial**: [Telegram Bot API - BotFather](https://core.telegram.org/bots#botfather)

### 2. Crear un Grupo de Telegram

1. Abre Telegram y crea un **nuevo grupo**
2. Dale un nombre *(ej: "NerdMiners Monitoring")*
3. Telegram te obliga a añadir a algún miembro *(puedes eliminarlo después)*

### 3. Añadir el Bot al Grupo

1. Abre la configuración del grupo
2. Selecciona **Añadir Miembros**
3. Busca tu bot por su nombre de usuario
4. Añade el bot al grupo
5. Ve a configuración del grupo → **Administradores** → **Añadir Administrador**
6. Selecciona tu bot y habilita **como mínimo** estos permisos:
   - **Enviar Mensajes**
   - **Eliminar Mensajes** ← Necesario para eliminar mensajes de estadísticas antiguos y limpiar notificaciones de fijado
   - **Fijar Mensajes** ← Necesario para que el bot mantenga el mensaje de estadísticas fijado en la parte superior del grupo

### 4. Obtener el CHAT_ID

El bot necesita el Chat ID del grupo para saber dónde enviar los mensajes.

**Método 1 — Usando la API de Telegram** (recomendado):

1. Envía cualquier mensaje en el grupo *(ej: "hola")*
2. Pulsa con el botón derecho del ratón y selecciona "Enlace al mensaje"
3. Pega la URL que acaba de copiarse y tendrá una estructura similar a esta:
- `https://t.me/c/3892682082/1`
4. El ID del tu grupo será el primer grupo de números, y deberás añadirle `-100`
- Según este ejemplo `-100`+`3892682082` = `-1003892682082`

### 5. Desactivar "Permitir Grupos" en BotFather

Este es un paso de seguridad importante. Después de añadir el bot a tu grupo:

1. Abre **@BotFather** de nuevo
2. Envía `/mybots`
3. Selecciona tu bot
4. Ve a **Bot Settings** → **Allow Groups?**
5. Selecciona **Disable**

Esto evita que cualquier otra persona pueda añadir tu bot a otros grupos. El bot seguirá funcionando en los grupos donde ya sea miembro.

> **Importante**: El bot ignora todos los mensajes directos. Solo opera en el grupo de Telegram configurado.

## Instalación

### 1. Clonar el Repositorio

```bash
git clone <url-del-repositorio>
cd NerdMiners_Public_Pool_Stats
```

### 2. Configurar el Bot

Ejecuta el script de configuración:

```bash
chmod +x First_Setup.sh
./First_Setup.sh
```

El script creará `.env` a partir de la plantilla `.env.example` en la primera ejecución.

```bash
nano .env
```

Establece las tres variables:

```
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
CHAT_ID=-1001234567890
BTC_ADDRESS=bc1q...
```

Después ejecuta el script de configuración otra vez.
El Script de configuración revisará que todas las variables están insertadas y comenzará el proceso de configuración del entorno de Bot, y se instalarán automáticamente las dependencias necesarias.
En caso de que te falte algún programa como Python o pip, te lo dirá, mostrándote el comando para que puedas instalarlo.

```bash
./First_Setup.sh
```

### 3. Personalizar Nombres de Workers *(Opcional)*

Edita `config.py` para establecer nombres personalizados para tus mineros sobre como se muestran los nombres en los mensajes de Telegram:
De esta manera puedes asignar un nombre más descriptivo a tu minero relacionado por el nombre del worker que aparece en Public-Pool.
Ten en cuenta que deberás asignar un nombre diferente a cada worker en la configuración del mismo.

```python
NAME_SUBSTITUTIONS = '{"nerdoctaxe_1": "NerdMiner Octaxe Gamma Casa", "nerdoctaxe_2": "NerdMiner Octaxe Gamma Trabajo", "worker": "NerdMiner v2 Salón", "worker_2": "NerdMiner v2 Oficina"}'
```
> **Importante**: El valor debe ser una **cadena JSON en una sola línea** — no la dividas en varias líneas. Este formato permite que el sistema de auto-actualización preserve tus nombres durante las actualizaciones.
*Para los NerdMiners antiguos que todos reportan como `worker` en la API, el bot asigna IDs incrementales (`worker_1`, `worker_2`, ...). Ejecuta el bot una vez y revisa el log para descubrir los IDs asignados.*

### 4. Configurar Tarea Cron

El bot está diseñado para ejecutarse periódicamente mediante cron — **no** es un servicio de ejecución continua.
Cada ejecución obtiene los datos más recientes, actualiza el mensaje fijado de estadísticas, envía las alertas que correspondan y finaliza.

Al final del script de configuración `First_Setup.sh`, se te mostrará un comando que deberás ejecutar para crear el cron dentro del crontab el sistema.


> **Importante — Frecuencia de ejecución**:
> - **Frecuencia máxima recomendada: cada 30 minutos** (`*/30 * * * *`).
> - Ejecutar con mayor frecuencia *(ej: cada 5 o 10 minutos)* **no se recomienda** porque la API de public-pool.io podría aplicar límites de tasa de consulta *(rate limits)* que bloquearían temporalmente tus peticiones.
> - Ejecutar con menor frecuencia *(ej: cada hora)* es perfectamente válido y seguirá proporcionando una monitorización útil.

## Configuración

Los valores sensibles están en `.env`:

| Variable | Descripción |
|----------|-------------|
| `BOT_TOKEN` | Token del Bot de Telegram de @BotFather |
| `CHAT_ID` | Chat ID del grupo de Telegram (número negativo) |
| `BTC_ADDRESS` | Tu dirección de Bitcoin de minería en public-pool.io |

Los ajustes configurables están en `config.py`:

| Ajuste | Descripción | Por defecto |
|--------|-------------|-------------|
| `API_BASE_URL` | URL base de la API de public-pool.io | `https://public-pool.io:40557/api` |
| `OFFLINE_TIMEOUT_MINUTES` | Minutos de inactividad para considerar un minero offline | `5` |
| `HASHRATE_DROP_PERCENT` | Porcentaje de caída del hashrate vs media 24h para activar alerta | `30` |
| `HASHRATE_ALERT_STRIKES` | Ejecuciones consecutivas con caída de hashrate necesarias antes de alertar. Con cron cada 30 min, `2` = la caída debe persistir ≥30 min | `2` |
| `HASHRATE_ALERT_COOLDOWN_HOURS` | Horas antes de reenviar una alerta LOW HASHRATE para el mismo minero. Se reinicia automáticamente cuando el hashrate se recupera | `4` |
| `NOTIFY_SESSION_BD_RECORD` | `False`: solo avisa cuando un minero supera su **mejor dificultad histórica**. `True`: avisa en cada nuevo récord de sesión, aunque no supere el récord histórico | `False` |
| `MESSAGE_EDIT_LIMIT_HOURS` | Horas antes de recrear el mensaje de estadísticas *(ver nota abajo)* | `45` |
| `DATA_RETENTION_DAYS` | Días de retención del historial de hashrate en la base de datos | `90` |
| `BACKUP_RETENTION_DAYS` | Días de retención de las copias de seguridad | `30` |
| `NAME_SUBSTITUTIONS` | Nombres personalizados para los mineros *(cadena JSON en una sola línea)* | `'{}'` |
| `LOG_LEVEL` | Nivel de detalle del log: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `WARNING` |

### SOBRE `MESSAGE_EDIT_LIMIT_HOURS`
*El bot mantiene un único mensaje fijado en Telegram que se edita en cada ejecución.*
*Cuando el mensaje alcanza la antigüedad de `MESSAGE_EDIT_LIMIT_HOURS`, el bot lo elimina y envía uno nuevo (que se fija automáticamente).*

> **Importante**: Telegram impone un **límite de 48 horas** para los bots — los mensajes con más de 48 horas de antigüedad **no pueden ser editados ni eliminados** a través de la Bot API. El valor por defecto de **45 horas** proporciona un margen de seguridad de 3 horas. **No establezcas este valor por encima de 45**, o el bot podría no ser capaz de eliminar el mensaje antiguo, resultando en mensajes fijados duplicados en el grupo.

## Alertas

| Alerta | Disparador |
|--------|------------|
| DISCONNECTION DETECTED | El ID de sesión del minero cambió *(nuevo `startTime`)*. Incluye duración de la sesión anterior, tiempo estimado de inactividad y hora de reconexión |
| MINER OFFLINE | Sin actividad durante más de `OFFLINE_TIMEOUT_MINUTES` minutos |
| LOW HASHRATE | El hashrate cayó más de `HASHRATE_DROP_PERCENT`% por debajo de la media de 24h durante `HASHRATE_ALERT_STRIKES` ejecuciones consecutivas. Cooldown de `HASHRATE_ALERT_COOLDOWN_HOURS`h entre alertas; se reinicia al recuperarse |
| NEW PERSONAL RECORD | El minero alcanzó una nueva mejor dificultad de sesión *"BD"* *(también marca récords históricos)* |
| NEW MINER DETECTED | Apareció un minero previamente desconocido |
| MINER DISAPPEARED | Un minero conocido ya no es visible en el pool |
| YOUR MINER FOUND A BLOCK | Uno de TUS mineros encontró un bloque de Bitcoin *(identificado por tu BTC_ADDRESS)* |
| BLOCK FOUND BY THE POOL | Otro minero en public-pool.io encontró un bloque de Bitcoin |

## Cómo Funciona

1. **Auto-actualización**: Comprueba el repositorio remoto para nuevas versiones y las aplica automáticamente, preservando tu configuración
2. **Inicialización de BD**: Crea las tablas SQLite si no existen
3. **Backup**: Crea una copia con marca de tiempo de la base de datos *(se omite si ya existe una con menos de 24h)*
4. **Obtener datos**: Consulta la API de public-pool.io para tus mineros, estadísticas del pool y de la red
5. **Identificar workers**: Mapea los workers de la API a IDs internos estables *(gestiona nombres duplicados)*
6. **Comprobar alertas**: Compara el estado actual con el guardado, detecta cambios, registra sesiones
7. **Enviar alertas**: Las alertas activadas se envían como mensajes individuales al grupo
8. **Actualizar estadísticas**: Construye el mensaje de estadísticas, edita el mensaje fijado existente *(o crea uno nuevo si es demasiado antiguo)*
9. **Purga**: Elimina muestras de hashrate más antiguas que `DATA_RETENTION_DAYS`

## Estructura del Proyecto

```
NerdMiners_Public_Pool_Stats/
├── .env                        # Secretos: BOT_TOKEN, CHAT_ID, BTC_ADDRESS (no está en git)
├── .env.example                # Plantilla para .env
├── config.py                   # Ajustes configurables del bot y nombres de workers
├── database.py                 # Capa de persistencia SQLite (modo WAL, claves foráneas)
├── NerdMiners_Bot.py           # Script principal del bot (punto de entrada)
├── First_Setup.sh              # Script de configuración inicial
├── Update.sh                   # Script de auto-actualización (llamado por NerdMiners_Bot.py en cada ejecución)
├── requirements.txt            # Dependencias de Python
├── DB.db                       # Base de datos SQLite (auto-generada)
├── Logs/                       # Directorio de logs (auto-generado)
│   └── NerdMiners_Public_Pool_Stats_Bot.log
└── Backup/                     # Copias de seguridad de la BD (auto-generadas, retención 30 días)
    └── NerdMiners_Public_Pool_Stats_MMDDYYYY_HHMMSS.db
```

## Endpoints de la API

URL base: `https://public-pool.io:40557/api`

| Endpoint | Descripción |
|----------|-------------|
| `/api/client/{dirección}` | Workers de una dirección Bitcoin (hashrate, mejor dificultad, sesiones) |
| `/api/pool` | Estadísticas globales del pool (hashrate total, mineros, bloques encontrados) |
| `/api/network` | Estadísticas de la red Bitcoin (altura de bloque, dificultad, hashrate) |

## Licencia

[MIT](https://github.com/function0xMarki/NerdMiners_Public_Pool_Stats/blob/main/LICENSE)
