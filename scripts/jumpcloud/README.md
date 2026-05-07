# KLR Endpoint Rename — JumpCloud Deployment Guide

Scripts para renombrar endpoints corporativos a la nomenclatura:

```
KLR-<COUNTRY><OS>-<LAST5SERIAL>
```

Ejemplos:
- `KLR-ARM-XA92F`  (Argentina, macOS)
- `KLR-ARW-XA92F`  (Argentina, Windows)
- `KLR-MXM-Q71QK`  (México, macOS)
- `KLR-DEW-X8XZ1`  (Alemania, Windows)
- `KLR-OTM-X3F9A`  (Otro país, macOS)

---

## Archivos

| Archivo | Plataforma | Propósito |
|---------|-----------|-----------|
| `klr_rename_macos.sh` | macOS | Renombra ComputerName / HostName / LocalHostName vía `scutil`. |
| `klr_rename_windows.ps1` | Windows | Renombra el equipo vía `Rename-Computer -Force`. |
| `klr_schedule_reboot_windows.ps1` | Windows | Programa reinicio a las 22:00 hoy (o mañana si ya pasó). |
| `sync_jc_displayname.py` | Helper local | Reconcilia el campo `displayName` de JumpCloud — el agente nunca lo refresca solo. Toma el hostname canónico desde CrowdStrike (que se actualiza en minutos) y lo PATCHea vía JC API. Útil después de un rename masivo. Uso: `python sync_jc_displayname.py --all-klr [--dry-run]` o por seriales puntuales. |

> **Nota sobre `displayName` en la consola JC**: el rename local (`scutil` / `Rename-Computer`) cambia el `hostname` técnico, que JC re-publica en su próximo inventario (acelerado por el `launchctl kickstart` / `Restart-Service` que los scripts hacen al final). Pero `displayName` — el campo que la búsqueda de la consola usa — se setea al momento del enrollment y **no se refresca jamás solo**. Para eso existe `sync_jc_displayname.py`.

---

## Notas de Despliegue en JumpCloud

### 1. Privilegios requeridos
- **macOS**: Ejecutar como **`root`**.
- **Windows**: Ejecutar como **`SYSTEM`** (o al menos con privilegios de Administrator).

### 2. Frecuencia de ejecución
- **Recomendado: Run Once** (una sola vez).
- Los scripts son idempotentes: si el nombre ya es correcto, salen con código `0` sin tocar nada. Sin embargo, configurarlos como *Run Once* evita ruido innecesario en los logs de JumpCloud.

### 3. Grupo piloto
- Antes de aplicar a toda la flota, ejecutar en un **grupo piloto de 5–10 máquinas por OS**.
- Verificar que:
  - El nombre resultante cumple el formato esperado.
  - No hay colisiones de nombre (últimos 5 del serial).
  - Las máquinas siguen apareciendo en JumpCloud con el nuevo nombre.

### 4. Reboot
- **Windows**: `Rename-Computer` requiere un **reinicio** para que el nombre se propague correctamente en NetBIOS / Active Directory (si aplica).
  - El script `klr_rename_windows.ps1` **no reinicia automáticamente**; solo imprime una advertencia.
  - Usar `klr_schedule_reboot_windows.ps1` para programar el reinicio a las 22:00, o hacerlo manualmente.
- **macOS**: **No requiere reinicio**. `scutil` aplica los cambios inmediatamente. Algunos servicios de red (Bonjour) pueden tardar unos minutos en refrescarse.

### 5. Timeout
- Un timeout de **60 segundos** en JumpCloud Command es suficiente para todos los scripts.

### 6. Carga de scripts
- Subir cada archivo a JumpCloud como **Command > File** (o copiar/pegar el contenido en el campo de script).
- **macOS**: seleccionar *Shell* y asegurar que el shebang (`#!/bin/bash`) sea respetado.
- **Windows**: seleccionar *PowerShell*.

---

## Riesgos y Edge Cases

### Timezone incorrecta o no corporativa
- El país se detecta **exclusivamente por el timezone local del sistema**.
- Si un usuario cambió manualmente el timezone a uno fuera de la lista (ej. `America/New_York`), el script asignará `OT` (Otro).
- **Mitigación**: auditar timezones antes del despliegue masivo, o corregirlos vía MDM/JumpCloud Policies previo al rename.

### Serial number demasiado corto o vacío
- Si el serial tiene menos de 4 caracteres, el script **sale con código de error ≠ 0** y no renombra.
- Esto suele ocurrir en VMs o hardware con firmware roto.
- **Mitigación**: identificar esos endpoints con un script de inventario previo y tratarlos como casos manuales.

### Placeholder serials
- Algunos fabricantes (especialmente clones/white-labels) devuelven placeholders como:
  - `To Be Filled By O.E.M.`
  - `System Serial Number`
  - `Not Available`
- El script de Windows rechaza explícitamente esos valores. El script de macOS los dejará pasar si son > 4 caracteres, pero el resultado (`KLR-XXM-O.E.`) será inútil.
- **Mitigación**: revisar el grupo piloto; los placeholders serán evidentes de inmediato.

### Duplicados por LAST5 del serial
- La probabilidad es muy baja con LAST5 (16M combinaciones para alfanuméricos).
- En la práctica, Apple genera serials donde los últimos 4-5 chars son seriado por modelo/fecha — observamos en prod un caso real de colisión por LAST4 (`C02DN4XQQ05D` y `C02FGKSEQ05D` ambos terminan en `Q05D`). LAST5 elimina ese caso (`XQ05D` vs `EQ05D`).
- Si ocurre, Windows y macOS permiten nombres duplicados en redes no unidas a AD, pero puede causar conflictos de resolución DNS/Bonjour.
- **Mitigación 1**: el helper `rename_batch.py --dry-run` detecta colisiones intra-batch antes de firear el trigger.
- **Mitigación 2**: si LAST5 no alcanza algún día, se puede ampliar a LAST6 (serial estándar Apple es 12 chars, así que LAST6 = primera mitad del año + secuencia).

### Alemania — `W. Europe Standard Time`
- Windows usa el ID `W. Europe Standard Time` para Alemania (no solo `Europe/Berlin`).
- El script mapea **ambos** explícitamente. Si aparece `Romance Standard Time` (usado en España/Francia), caerá en `OT`, que es el comportamiento correcto según el requerimiento.

### Límite de 15 caracteres (NetBIOS)
- El formato `KLR-XXY-AAAA` genera nombres de **11 caracteres**, bien dentro del límite de 15 de NetBIOS.
- El script valida esto y falla si por alguna razón se excede.

### macOS — `LocalHostName` incompatible
- `scutil --set LocalHostName` solo acepta caracteres alfanuméricos y guiones.
- El formato KLR ya cumple esto (no usa underscores ni espacios), por lo que no debería haber rechazo.

### Windows — Reinicio ya pendiente
- `klr_schedule_reboot_windows.ps1` detecta el exit code `1190` de `shutdown.exe` y **no programa un segundo reinicio**.
- Si otro proceso (Windows Update, SCCM, etc.) ya programó un reinicio, el script informa y sale limpiamente.

### Sin conectividad a APIs externas
- Los scripts **no dependen de internet**, geolocalización por IP ni APIs de terceros.
- Todo se resuelve con datos locales: timezone del OS, serial de la BIOS / IOPlatformExpertDevice.
