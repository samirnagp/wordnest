# WordNest – Word template download site

A responsive website plus a small FastAPI backend.
It ships with 9 ready Word templates: 3 bank letters, 2 resumes, 2 reports and 2 invoices (one GST invoice for India).

```
main.py               backend (catalog API, tracked downloads, admin upload)
public/               the website  (index.html, catalog.json, templates/*.docx, previews/*.jpg)
tools/                generate_templates.js  (rebuilds the .docx files)
Dockerfile, docker-compose.yml, .env.example
```

## Three ways to run it

### A. Static only (free, no backend): GitHub Pages or Cloudflare Pages
Upload the **contents of `public/`** to your repo (index.html, catalog.json, templates/, previews/).
The page notices there is no API and falls back to `catalog.json`.
Downloads work; download counters and the admin API are not available.

### B. Full stack with Docker (website + API in one container)
    cp .env.example .env        # set ADMIN_TOKEN
    docker compose up -d --build
    open http://localhost:8000

### C. Without Docker
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Any host that runs Docker works (Render, Cloud Run, Railway, a VPS, or your PC with a Cloudflare tunnel).
Set `ALLOWED_ORIGINS` if the website is hosted somewhere other than the backend.

## If the website and backend are on different addresses
Edit `const API=""` near the bottom of `public/index.html`:

    const API="https://api.yourdomain.com";

and set `ALLOWED_ORIGINS=https://your-site.example` on the backend (no path, no trailing slash).

## API
| Method | Path | Purpose |
|---|---|---|
| GET | /api/templates?category=&q=&sort=popular\|new\|name | List templates with download counts |
| GET | /api/templates/{id} | One template |
| GET | /api/categories | Categories with counts |
| GET | /api/download/{id} | Download the .docx (counts the download) |
| POST | /api/admin/templates | Add a template (admin) |
| DELETE | /api/admin/templates/{id} | Remove a template (admin) |
| GET | /health | Health check |
Interactive docs: `/docs`

## Adding templates
**With the API** (set ADMIN_TOKEN first):

    curl -X POST http://localhost:8000/api/admin/templates \
      -H "X-Admin-Token: YOUR_TOKEN" \
      -F "title=Offer Letter" -F "category=Other" \
      -F "description=Job offer letter with salary and joining date." \
      -F "tags=offer,hr,letter" \
      -F "file=@offer-letter.docx" -F "preview=@offer-letter.jpg"

Categories: Bank Letters, Resumes, Reports, Invoices, Other.
The preview image is optional (JPG, about 640 px wide); create one by exporting page 1 of the document.

**By hand:** drop the .docx into `public/templates/`, a JPG into `public/previews/`, and add an entry to `public/catalog.json`.

**Rebuild the built-in ones:** edit `tools/generate_templates.js`, run `npm install docx` and `node tools/generate_templates.js`.

## Production checklist
- Set a long random `ADMIN_TOKEN`, or leave it empty to disable the admin API.
- Set `ALLOWED_ORIGINS` to your real website address.
- Put the container behind HTTPS (Caddy, Cloudflare, or your host's built-in HTTPS).
- Back up the `data/` volume (counters) and `public/` (catalog and files).
- The built-in 429 rate limit is per IP. For heavy traffic add Cloudflare in front.
