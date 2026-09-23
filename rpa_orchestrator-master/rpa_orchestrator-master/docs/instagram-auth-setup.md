# Autenticación Instagram ↔ RPA Orchestrator

Hay **tres credenciales distintas** en juego. No se reutiliza ninguna: cada una
cubre una dirección de confianza diferente.

| Credencial | Quién la usa | Para qué |
|---|---|---|
| `BOT_TOKENS` (token de worker) | Django → Orchestrator | Registrar el adaptador en el WebSocket y crear ejecuciones autónomas |
| `INSTAGRAM_BACKEND_TOKEN` | Orchestrator → Django | Consultar el catálogo de Instagram |
| `DASHBOARD_USER` / `DASHBOARD_PASS` | Operador → Orchestrator | Entrar al dashboard y a `/api/v1/instagram/*` |

La contraseña del dashboard **no** es un token de integración y no va en
ninguno de los dos `.env` del lado de Instagram.

## A. Adaptador Django → Orchestrator

El adaptador Django se registra con el bot key:

```text
instagram-backend-01
```

El orquestador acepta tokens de worker a través de `BOT_TOKENS`.

En el `.env` del Orchestrator:

```env
BOT_TOKENS={"GENERATED_BOT_TOKEN":"instagram-backend-01"}
```

> `BOT_TOKENS` es un único JSON con **todos** los workers. Si el entorno ya
> tiene otros bots registrados (por ejemplo `saaf-backlinks-01`), agregá la
> entrada nueva al JSON existente; reemplazarlo deja a esos bots sin poder
> autenticarse.

El mismo token generado va en el backend Django como:

```env
ORCHESTRATOR_BOT_TOKEN=GENERATED_BOT_TOKEN
ORCHESTRATOR_BOT_KEY=instagram-backend-01
```

Ese token también sirve para `POST /api/v1/executions/standalone/instagram`,
que acepta Basic del dashboard **o** `Authorization: Bearer <token de worker>`.

Generá los valores con:

```bash
python scripts/generate_instagram_integration_tokens.py
```

## B. Orchestrator → catálogo Django

El orquestador tiene dos settings propios:

```env
INSTAGRAM_BACKEND_URL=http://<host-django>:<puerto>
INSTAGRAM_BACKEND_TOKEN=GENERATED_CATALOG_TOKEN
```

`INSTAGRAM_BACKEND_TOKEN` **no** es el token de worker: autentica las llamadas
que hace el orquestador hacia el backend Django. Django debe aceptarlo con el
setting que exponga su adaptador y el valor tiene que ser idéntico de los dos
lados. Si falta cualquiera de los dos settings, `/api/v1/instagram/catalog`
responde `503` en vez de salir a una URL por defecto.

## Reglas

- Nunca commitear un `.env` con valores reales ni secretos generados.
- No copiar literalmente los placeholders del `.env.example`.
- Usar valores aleatorios distintos para el token de worker y el de catálogo.
- `ORCHESTRATOR_API_TOKEN` **no** es un setting de este repositorio; no lo
  inventes del lado del Orchestrator.

## Verificación rápida

1. Levantar el Orchestrator.
2. Levantar Django con el adaptador de Instagram habilitado.
3. Confirmar que el adaptador se registra como `instagram-backend-01`.
4. Confirmar que `GET /api/v1/instagram/catalog` responde `200`.
5. Recién ahí, lanzar una ejecución real de Instagram.
