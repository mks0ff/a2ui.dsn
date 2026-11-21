on my macOS ⇒
```bash
# run backend
source .venv/bin/activate
source .env
python -m uvicorn dsn_agent.api:app --host 127.0.0.1 --port 8000
# build frontend
npm ci
npm run build
# run frontend
npm run dev
```
