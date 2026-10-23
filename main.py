"""WordNest backend: template catalog, tracked downloads, admin upload. Also serves the website."""
import hmac, json, os, re, sqlite3, threading, time, uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
PUBLIC = BASE / "public"
FILES = PUBLIC / "templates"
PREVIEWS = PUBLIC / "previews"
CATALOG = PUBLIC / "catalog.json"
DB_PATH = Path(os.getenv("DB_PATH", BASE / "data" / "downloads.db"))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")            # empty = admin API disabled
ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
RATE = int(os.getenv("RATE_LIMIT_PER_MIN", "120"))
CATEGORIES = ["Bank Letters", "Resumes", "Reports", "Invoices", "Other"]
EXTS = {".docx", ".dotx"}

lock = threading.Lock()
for d in (FILES, PREVIEWS, DB_PATH.parent):
    d.mkdir(parents=True, exist_ok=True)

def db():
    c = sqlite3.connect(DB_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS downloads(id TEXT PRIMARY KEY, n INTEGER NOT NULL DEFAULT 0)")
    return c

def load():
    return json.loads(CATALOG.read_text("utf-8")) if CATALOG.exists() else []

def save(items):
    tmp = CATALOG.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), "utf-8")
    tmp.replace(CATALOG)                                # atomic write

def counts():
    with db() as c:
        return dict(c.execute("SELECT id, n FROM downloads").fetchall())

def with_counts(items):
    n = counts()
    return [{**i, "downloads": n.get(i["id"], 0)} for i in items]

app = FastAPI(title="WordNest API", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["*"], expose_headers=["Content-Disposition"])

_hits = defaultdict(deque)
@app.middleware("http")
async def rate_limit(request: Request, call_next):
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else "?"))
    now, q = time.time(), _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE:
        return JSONResponse({"detail": "Too many requests. Please slow down."}, status_code=429,
                            headers={"Access-Control-Allow-Origin": "*"})
    q.append(now)
    return await call_next(request)

@app.get("/health")
def health():
    return {"status": "ok", "templates": len(load())}

@app.get("/api/categories")
def categories():
    items = load()
    return [{"name": c, "count": sum(1 for i in items if i["category"] == c)} for c in CATEGORIES
            if any(i["category"] == c for i in items)]

@app.get("/api/templates")
def templates(category: str = "", q: str = "", sort: str = "popular"):
    items = with_counts(load())
    if category:
        items = [i for i in items if i["category"].lower() == category.lower()]
    if q:
        s = q.lower()
        items = [i for i in items if s in (i["title"] + " " + i["description"] + " " + " ".join(i.get("tags", []))).lower()]
    if sort == "name":
        items.sort(key=lambda i: i["title"].lower())
    elif sort == "new":
        items.sort(key=lambda i: i.get("added", ""), reverse=True)
    else:
        items.sort(key=lambda i: (-i["downloads"], not i.get("featured"), i["title"]))
    return items

def find(tid):
    for i in load():
        if i["id"] == tid:
            return i
    raise HTTPException(404, "Template not found")

@app.get("/api/templates/{tid}")
def one(tid: str):
    return with_counts([find(tid)])[0]

@app.get("/api/download/{tid}")
def download(tid: str):
    item = find(tid)
    path = (PUBLIC / item["file"]).resolve()
    if FILES.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "File missing")
    with lock, db() as c:
        c.execute("INSERT INTO downloads(id,n) VALUES(?,1) ON CONFLICT(id) DO UPDATE SET n=n+1", (tid,))
    return FileResponse(path, filename=path.name,
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        if path.suffix == ".docx" else "application/vnd.openxmlformats-officedocument.wordprocessingml.template")

# ---------- admin (send header  X-Admin-Token: <ADMIN_TOKEN>) ----------
def admin(token: str):
    if not ADMIN_TOKEN:
        raise HTTPException(404, "Admin API is disabled. Set ADMIN_TOKEN to enable it.")
    if not hmac.compare_digest(token or "", ADMIN_TOKEN):
        raise HTTPException(401, "Invalid admin token")

@app.post("/api/admin/templates")
def add(title: str = Form(...), category: str = Form(...), description: str = Form(""), tags: str = Form(""),
        file: UploadFile = File(...), preview: UploadFile | None = File(None),
        x_admin_token: str = Header("")):
    admin(x_admin_token)
    if category not in CATEGORIES:
        raise HTTPException(400, "Category must be one of: " + ", ".join(CATEGORIES))
    ext = Path(file.filename or "").suffix.lower()
    if ext not in EXTS:
        raise HTTPException(415, "Only .docx and .dotx files are allowed")
    data = file.file.read(MAX_MB * 1024 * 1024 + 1)
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {MAX_MB} MB)")
    if not data.startswith(b"PK"):
        raise HTTPException(400, "This does not look like a valid Word file")
    tid = (re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "template")[:50] + "-" + uuid.uuid4().hex[:4]
    (FILES / f"{tid}{ext}").write_bytes(data)
    if preview and (preview.filename or "").lower().endswith((".jpg", ".jpeg")):
        (PREVIEWS / f"{tid}.jpg").write_bytes(preview.file.read(3 * 1024 * 1024))
    item = {"id": tid, "title": title.strip()[:90], "category": category, "description": description.strip()[:300],
            "tags": [t.strip().lower() for t in tags.split(",") if t.strip()][:8], "featured": False,
            "file": f"templates/{tid}{ext}", "pages": 1, "added": time.strftime("%Y-%m-%d")}
    with lock:
        save(load() + [item])
    return item

@app.delete("/api/admin/templates/{tid}")
def remove(tid: str, x_admin_token: str = Header("")):
    admin(x_admin_token)
    item = find(tid)
    with lock:
        save([i for i in load() if i["id"] != tid])
    for p in ((PUBLIC / item["file"]), PREVIEWS / f"{tid}.jpg"):
        p.unlink(missing_ok=True)
    return {"deleted": tid}

# ---------- website (served last so /api/* wins) ----------
app.mount("/", StaticFiles(directory=PUBLIC, html=True), name="site")
