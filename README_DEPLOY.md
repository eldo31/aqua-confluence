# Aqua Confluence — Pack d'hébergement (structure avec `src/`)

Placez ces fichiers **à la racine** de votre repo :
- `Procfile` → lance gunicorn sur `src.main:app`
- `render.yaml` → config Render (plan gratuit) + ffmpeg via apt
- `apt.txt` → indique à Render d'installer `ffmpeg`

## Flask (routes UI)
Dans `src/main.py`, ajoutez/garantissez :
```py
from flask import send_from_directory

@app.get("/")
def root():
    return send_from_directory("src", "index.html")

@app.get("/app.js")
def js():
    return send_from_directory("src", "app.js")
```

Si vous avez `src/assets/` :
```py
@app.get("/assets/<path:path>")
def assets(path):
    return send_from_directory("src/assets", path)
```

## Requirements
Votre `requirements.txt` doit contenir au minimum :
```
Flask>=3.0.0
pydub>=0.25.1
gunicorn>=21.2.0
python-dotenv>=1.0.1
```

## Déploiement Render
1) Connecter le repo GitHub sur Render (Create Web Service)  
2) Build: `pip install -r requirements.txt` (automatique)  
3) Start: `gunicorn -w 1 -b 0.0.0.0:$PORT src.main:app` (fourni)  
4) Tester `/health` puis l'UI

## Déploiement Railway
1) Import GitHub → ajouter variable d'env `NIXPACKS_PKGS=ffmpeg`  
2) Lancement via `Procfile` détecté
