# URL shortener

A small Flask service that creates short URL codes backed by Redis.

Used as a second service deployed by Pulse v2 to demonstrate the
platform's deploy/promote/rollback features.

## Endpoints

- `GET /health` — health check, returns 200 with Redis status (or 503 if Redis unreachable)
- `POST /shorten` — body `{"url": "https://..."}` returns `{"short": "abc1234", "url": "..."}`
- `GET /<code>` — 302 redirect to the long URL, or 404 if not found

## Configuration

Reads from environment variables:

- `REDIS_HOST` (default: `localhost`)
- `REDIS_PORT` (default: `6379`)

## Deployment

Kubernetes manifests for this service live in `kubernetes/url-shortener/`.

Local development against k3s:

```bash
# Build and import the image into k3s
sudo docker build -t url-shortener:dev services/url-shortener/
sudo docker save url-shortener:dev | sudo k3s ctr images import -

# Deploy
kubectl apply -f kubernetes/url-shortener/

# Verify
kubectl get all -n url-shortener
curl http://localhost:30800/health
```

To remove:

```bash
kubectl delete namespace url-shortener
```