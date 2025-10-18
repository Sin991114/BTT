# Singapore BTT Practice (Static Site)

This is a simple static website to practice Singapore Basic Theory Test (BTT) questions. It serves HTML/CSS/JS, JSON data, and extracted images.

Contents:
- `index.html`, `style.css`, `script.js`
- `questions.json`, `answers.json`
- `assets/images/` (question images)
- `.nojekyll` and a GitHub Actions workflow to auto-deploy to GitHub Pages

## Local preview

- Python: `python -m http.server 8000`
- Open: `http://localhost:8000/index.html`

## Deploy to GitHub Pages (recommended, free)

1) Create a new repo on GitHub (public is fine for Pages):
   - https://github.com/new

2) In this folder, run:

```
git init
git add .
git commit -m "Initial BTT site"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

3) Wait for the GitHub Actions workflow to finish (Actions tab). It deploys to Pages automatically.

4) Visit the site:
   - `https://<you>.github.io/<repo>/`

Notes:
- No build step is required. The workflow uploads the repository root as the Pages artifact.
- JSON and images are cache-busted by the app when fetched.
- If you use a custom domain, set it under the repo’s Settings → Pages → Custom domain.

## Alternative hosts

- Netlify: Drag-and-drop the folder in the dashboard (no build). Publish dir is `/`.
- Vercel: Import repo, framework: “Other”, output `/`.
- Cloudflare Pages: Connect repo, no build, root `/`.

## Regenerate data from PDFs

```
pip install pdfplumber
python extract_btt.py
```

This writes `questions.json`, `answers.json`, and extracts images under `assets/images/`.
