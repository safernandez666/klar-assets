# Device Normalizer

> **🌐 Language / Idioma:** [English](README.md) | [Español](README.es.md)

Visibilidad del parque de dispositivos a través de JumpCloud (MDM), CrowdStrike (EDR) y Okta (IDP) — unificado en un dashboard seguro.

## Qué hace

Recolecta datos de dispositivos de tres fuentes en paralelo, deduplica por serial/MAC/owner/hostname y normaliza en un inventario unificado de activos para dispositivos desktop/laptop. Los dispositivos móviles se filtran automáticamente.

### Modelo de Estados

| Estado | Significado |
|--------|-------------|
| **FULLY_MANAGED** | JumpCloud + CrowdStrike + Okta + owner asignado |
| **MANAGED** | JumpCloud + CrowdStrike (el baseline operativo) |
| **NO_EDR** | En JumpCloud pero sin CrowdStrike |
| **NO_MDM** | En CrowdStrike pero sin JumpCloud |
| **IDP_ONLY** | Solo en Okta — posible shadow IT |
| **SERVER** | Servidores/VMs con CrowdStrike (no necesitan MDM) |
| **STALE** | Sin actividad en más de 90 días |

### Funcionalidades

- **Dashboard** con cards de estado, gauge de riesgo, pie charts, historial
- **Insights con IA** via OpenAI (Quick Actions con recomendaciones priorizadas)
- **Matching de dispositivos con IA** para registros de baja confianza (correlación cross-source)
- **Búsqueda de activos** con filtros por estado, fuente, OS y búsqueda full-text
- **Vista de personas** — compliance por persona: quién tiene dispositivos managed y quién no
- **Acknowledge** de dispositivos para excluirlos de métricas (contingencia, test)
- **Reporte PDF** con resumen ejecutivo, gráficos, listas de dispositivos y branding personalizado
- **Exportación** a CSV y Excel con estados coloreados
- **Alertas en Slack** después de cada sync: dispositivos nuevos, desapariciones, stale
- **Detección de servidores/VMs** — clasifica automáticamente infraestructura por patrones de hostname
- **Login** con usuario/contraseña (sesiones JWT, preparado para HTTPS)

## Screenshots

### Dashboard
![Dashboard](docs/screenshots/dashboard.jpg)

### Acciones Rápidas (IA)
![Quick Actions](docs/screenshots/quick-actions.jpg)

## Inicio Rápido

### Local

```bash
# Clonar
git clone https://github.com/safernandez666/klar-assets.git
cd klar-assets

# Python
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend && npm install && npm run build && cd ..

# Configurar
cp .env.example .env
# Editar .env con tus API keys

# Ejecutar
python main.py
```

Abrir http://localhost:8080

### Docker

```bash
# Build
docker build -t device-normalizer .

# Ejecutar
docker compose up -d

# Logs
docker compose logs -f
```

### Kubernetes

```bash
# 1. Editar secrets con tus API keys
vim k8s/secret.yaml

# 2. Editar configmap con tu FQDN
vim k8s/configmap.yaml

# 3. Subir imagen a tu registry
docker tag device-normalizer tu-registry/device-normalizer:latest
docker push tu-registry/device-normalizer:latest
# Actualizar imagen en k8s/deployment.yaml

# 4. Deployar
kubectl apply -f k8s/
```

El directorio `k8s/` incluye:

| Archivo | Descripción |
|---------|-------------|
| `namespace.yaml` | Namespace `device-normalizer` |
| `secret.yaml` | API keys, contraseñas (completar antes de aplicar) |
| `configmap.yaml` | Config no secreta (URLs, intervalo de sync) |
| `pvc.yaml` | Volumen persistente de 1Gi para SQLite |
| `deployment.yaml` | Una réplica, estrategia Recreate, límites de recursos, health probes |
| `service.yaml` | Service ClusterIP (puerto 80 → 8080) |
| `ingress.yaml` | Ingress con FQDN + TLS (preparado para cert-manager) |

> **Nota:** SQLite requiere un solo writer, por eso el deployment usa estrategia `Recreate` con 1 réplica. Para setups multi-réplica, considerar migrar a PostgreSQL.

## Configuración

Copiar `.env.example` a `.env` y completar:

| Variable | Requerida | Descripción |
|----------|-----------|-------------|
| `CS_CLIENT_ID` | Sí | CrowdStrike API client ID |
| `CS_CLIENT_SECRET` | Sí | CrowdStrike API client secret |
| `CS_BASE_URL` | Sí | CrowdStrike API base URL |
| `OKTA_DOMAIN` | Sí | Dominio de Okta (ej: example.okta.com) |
| `OKTA_API_TOKEN` | Sí | Token de API de Okta |
| `JC_API_KEY` | Sí | API key de JumpCloud |
| `APP_URL` | No | URL pública (default: http://localhost:8080) |
| `AUTH_USERNAME` | No | Usuario de login (default: admin) |
| `AUTH_PASSWORD` | No | Contraseña de login (vacío = auth deshabilitado) |
| `JWT_SECRET` | No | Clave de firma de sesión (auto-generada si vacía) |
| `OPENAI_API_KEY` | No | Habilita insights con IA y matching de dispositivos |
| `SLACK_WEBHOOK_URL` | No | Habilita alertas en Slack después de cada sync |
| `SYNC_INTERVAL_HOURS` | No | Intervalo de sync automático (default: 6) |
| `SYNC_ON_STARTUP` | No | Sync al iniciar el server (default: true) |
| `WEB_HOST` | No | Dirección de bind (default: 0.0.0.0) |
| `WEB_PORT` | No | Puerto (default: 8080) |

## Notificaciones en Slack

Después de cada sync (cada 6 horas o manual), se envía un mensaje a Slack con formato Block Kit. Configurar `SLACK_WEBHOOK_URL` en `.env` para habilitar.

### Tipos de Mensajes

#### Después de Cada Sync
El reporte estándar incluye:
- **Resumen del fleet** — total de dispositivos, cantidad managed, porcentaje de cobertura
- **Gaps de cobertura** — cuántos dispositivos les falta EDR o MDM
- **Desglose de estados** — cantidad por estado (MANAGED, NO_EDR, etc.)
- **Salud de fuentes** — qué fuentes respondieron OK y cuáles fallaron

#### Dispositivos Nuevos Detectados
Cuando un dispositivo aparece por primera vez:
- **Nuevos riesgosos** (NO_EDR, NO_MDM, IDP_ONLY) se destacan con hostname, owner y estado
- **Nuevos managed** se reportan como cantidad

> :new: **3 Dispositivos Nuevos Sin Cobertura Completa**
> :warning: `MacBook-Pro-New.local` — john@example.com — **NO_EDR**
> :warning: `DESKTOP-XYZ` — sin owner — **NO_MDM**

#### Dispositivos Managed Desaparecieron
Cuando un dispositivo que era MANAGED o FULLY_MANAGED deja de reportar:

> :rotating_light: **2 Dispositivos Managed Desaparecieron**
> :rotating_light: `santiago-macbook.local` — jane@example.com
> :rotating_light: `LAPTOP-ABC` — maria@example.com

#### Dispositivos se Volvieron Stale
Cuando un dispositivo cruza los 90 días de inactividad:

> :hourglass: **1 Dispositivo se Volvió Stale**
> :hourglass: `old-laptop.local` — inactivo hace 91 días

#### Todo en Orden
Cuando nada cambió desde el último sync:

> :white_check_mark: Sin cambios desde el último sync

### Alerta de Prueba

Enviar un mensaje de prueba para verificar el webhook:

```bash
curl -X POST http://localhost:8080/api/slack/test
```

## Endpoints de API

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/devices` | GET | Todos los dispositivos (filtrable por status/source) |
| `/api/summary` | GET | Conteo de estados + risk score |
| `/api/trends` | GET | Cambios vs sync anterior |
| `/api/history` | GET | Snapshots históricos de estados |
| `/api/gaps` | GET | Dispositivos agrupados por gap de cobertura |
| `/api/insights` | GET | Quick actions generados por IA |
| `/api/people` | GET | Vista de compliance por persona |
| `/api/user/{email}/compliance` | GET | Verificar si un usuario tiene dispositivo managed |
| `/api/dual-use` | GET | Usuarios con dispositivos corporativos + personales |
| `/api/export/csv` | GET | Exportación CSV (filtrable) |
| `/api/export/xlsx` | GET | Exportación Excel con estados coloreados |
| `/api/report/full` | GET | Reporte estructurado completo para PDF |
| `/api/sync/trigger` | POST | Disparar sync manual |
| `/api/sync/last` | GET | Detalles del último sync |
| `/api/slack/test` | POST | Enviar alerta de prueba a Slack |
| `/api/devices/{id}/ack` | POST | Acknowledge de dispositivo |
| `/api/devices/{id}/ack` | DELETE | Remover acknowledge |

## Stack Tecnológico

- **Backend**: Python, FastAPI, SQLite, APScheduler
- **Frontend**: React, Vite, Tailwind CSS v4, Recharts, Framer Motion
- **IA**: OpenAI GPT-4o-mini (insights, matching de dispositivos, reportes PDF)
- **Integraciones**: CrowdStrike Falconpy, Okta API, JumpCloud API, Slack Block Kit

## Arquitectura y Documentación

Diagramas SVG interactivos disponibles en [`docs/`](docs/) — click en cualquier imagen para abrir la versión interactiva.

### Arquitectura del Sistema
[![Arquitectura](docs/screenshots/diagram-architecture.png)](docs/architecture.html)

### Flowchart del Pipeline de Sync
[![Flowchart](docs/screenshots/diagram-flowchart.png)](docs/flowchart.html)

### Transiciones de Status de Dispositivos
[![Máquina de Estados](docs/screenshots/diagram-state-machine.png)](docs/state-machine.html)

### Schema de Base de Datos
[![ER Diagram](docs/screenshots/diagram-er.png)](docs/er-diagram.html)

### Stack Tecnológico
[![Layer Stack](docs/screenshots/diagram-layer-stack.png)](docs/layer-stack.html)

### Flujo de Autenticación Okta OIDC
[![Secuencia](docs/screenshots/diagram-sequence.png)](docs/sequence-okta-oidc.html)

### Swimlane del Proceso de Sync
[![Swimlane](docs/screenshots/diagram-swimlane.png)](docs/swimlane.html)

### Timeline del Ciclo de Sync
[![Timeline](docs/screenshots/diagram-timeline.png)](docs/timeline.html)

```
Collectors (paralelo)          Motor de Dedup       AI Matcher         Enricher
┌─────────────┐
│ CrowdStrike │──┐
├─────────────┤  │   ┌──────────────┐   ┌───────────┐   ┌──────────┐
│   Okta      │──┼──▶│ Serial/MAC/  │──▶│  OpenAI   │──▶│ Status   │──▶ SQLite
├─────────────┤  │   │ Owner/Host   │   │ matching  │   │ Gaps     │
│ JumpCloud   │──┘   └──────────────┘   └───────────┘   └──────────┘
└─────────────┘
                                                              │
                              ┌────────────────────────────────┘
                              ▼
                    FastAPI + React Dashboard
                    Alertas Slack │ Reportes PDF
```
