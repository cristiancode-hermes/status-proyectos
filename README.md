# Status · proyectos

Dashboard en vivo de la infra Hermes / `proyectos.cristiancode.dev`.

**Live:** https://status.proyectos.cristiancode.dev

## Qué muestra

| Sección | Contenido |
|---|---|
| Resumen | KPIs: gateway, sesiones, agentes, tareas, socats, crons, load, uptime |
| Plataformas | Slack (perfil default) + Telegram (perfil `cpp-developer`) y el resto de gateways |
| Crons | Jobs diarios/semanales, filtro por error, última ejecución |
| Trabajo | Árbol de agentes, sesiones, kanban, tools, eventos |
| Red | Forwards socat y procesos observados |
| Sistema | Load, memoria, sparkline, workers |

Búsqueda global (atajo `/`) sobre crons, procesos, sesiones y puertos. Layout con sidebar en escritorio y dock en móvil.

## Stack

- Backend: FastAPI + WebSocket (`server.py`) en `:3333`
- Frontend: `index.html` (HTML/CSS/JS, sin build)
- Proxy: Caddy → `status.proyectos.cristiancode.dev`

## Arranque local

```bash
cd dashboard-realtime
# requiere HERMES_HOME con gateway_state.json y cron/jobs.json
python3 server.py
# abre http://127.0.0.1:3333
```

En producción lo lanza `/opt/data/start-dashboard-realtime.sh`.

## Notas

- El gateway **default** tiene Telegram desactivado a propósito (un solo bot / un solo poll). El chip de Telegram se toma de `profiles/cpp-developer/gateway_state.json`.
- `index.v1.html` es la UI anterior, por si hay que comparar.

## Licencia

Uso interno de Cristian / Hermes.
