"""
scripts/build_static.py — Pre-bake the dashboard into static HTML + JSON for
GitHub Pages.

Pages serves only static files, so this script:

  1. Runs the database bootstrap (init + imports + county catalog + JSON read).
  2. Spins up the Flask app in test-client mode and asks each /api/* route
     for its JSON, dumping the responses into docs/data/.
  3. Pre-generates a per-pathway JSON file (docs/data/jobs/<id>.json) for
     every pathway so the dashboard can deep-link without a query string.
  4. Renders templates/index.html and templates/programs.html with relative
     asset URLs and a `window.P2P_STATIC_BASE` flag the frontend uses to
     decide whether to fetch from /api/* (Flask mode) or from
     data/*.json (Pages mode).
  5. Copies the static/ tree into docs/static/.

The Pages workflow runs this script on a daily cron AND on every push to
main, then publishes docs/ as the Pages site.

Run locally:
    python scripts/build_static.py
    # serve docs/ over a local HTTP server to verify:
    cd docs && python -m http.server 8080
"""

import json
import os
import re
import shutil
import sys
from urllib.parse import quote

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")
DATA_DIR = os.path.join(DOCS_DIR, "data")
JOBS_DIR = os.path.join(DATA_DIR, "jobs")
POSITIONS_DIR = os.path.join(DATA_DIR, "positions")


def ensure_clean(path):
    """Remove path's contents (keeping .git-style hidden files at the top level)."""
    if not os.path.exists(path):
        os.makedirs(path)
        return
    for entry in os.listdir(path):
        if entry.startswith("."):
            continue
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            shutil.rmtree(full)
        else:
            os.remove(full)


def write_response_json(client, url, dest):
    """Hit a Flask endpoint with the test client, write the body to disk."""
    resp = client.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"  {url} -> HTTP {resp.status_code}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(resp.get_data(as_text=True))
        if not resp.get_data(as_text=True).endswith("\n"):
            f.write("\n")


def rewrite_index_for_static(html, static_base="."):
    """Adjust index.html so it works when served from GitHub Pages."""
    # Asset URLs that were rewritten by url_for() come out absolute (/static/...).
    # On Pages we want relative paths (./static/...) so the dashboard works
    # regardless of the repo slug or any custom domain.
    html = html.replace('href="/static/', f'href="{static_base}/static/')
    html = html.replace('src="/static/',  f'src="{static_base}/static/')

    # The /programs link in the header is a Flask url_for; rewrite it.
    html = html.replace('href="/programs"', f'href="{static_base}/programs/index.html"')

    # Inject the static-mode flag before app.js loads so the JS picks the
    # right data source.
    flag_script = (
        f'<script>\n'
        f'  window.P2P_STATIC_BASE = {json.dumps(static_base)};\n'
        f'</script>\n    '
    )
    html = re.sub(
        r'(<script src="[^"]*/static/js/app\.js"[^>]*></script>)',
        flag_script + r'\1',
        html,
        count=1,
    )
    return html


def rewrite_programs_for_static(html, static_base=".."):
    """The /programs page is server-rendered. On Pages it becomes a static
    snapshot of today's data — fine for a browse page."""
    html = html.replace('href="/static/', f'href="{static_base}/static/')
    html = html.replace('src="/static/',  f'src="{static_base}/static/')
    html = html.replace('href="/"',       f'href="{static_base}/index.html"')
    return html


def main():
    print("[build_static] Bootstrapping the database ...")
    from database.bootstrap import bootstrap
    bootstrap()

    print("[build_static] Cleaning docs/ ...")
    ensure_clean(DOCS_DIR)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("[build_static] Copying static/ -> docs/static/ ...")
    shutil.copytree(
        os.path.join(PROJECT_ROOT, "static"),
        os.path.join(DOCS_DIR, "static"),
    )

    print("[build_static] Spinning up Flask test client ...")
    from app import create_app
    app = create_app()

    with app.test_client() as client:
        # 1. Top-level API responses.
        for url, target in [
            ("/api/schools/full",    "schools-full.json"),
            ("/api/schools",         "schools.json"),
            ("/api/programs",        "programs.json"),
            ("/api/pathways",        "pathways.json"),
            ("/api/careers",         "careers.json"),
            ("/api/refresh-status",  "refresh-status.json"),
        ]:
            dest = os.path.join(DATA_DIR, target)
            print(f"  baking {url} -> data/{target}")
            write_response_json(client, url, dest)

        # 2. Per-pathway positions (mirror /api/jobs?pathway_id=N).
        pathways = json.loads(client.get("/api/pathways").get_data(as_text=True))
        print(f"  baking /api/jobs for {len(pathways)} pathways -> data/jobs/<id>.json")
        for pw in pathways:
            write_response_json(
                client,
                f"/api/jobs?pathway_id={pw['id']}",
                os.path.join(JOBS_DIR, f"{pw['id']}.json"),
            )

        # 3. Per-school pathway lookup (mirror /api/schools/<id>/pathways).
        schools = json.loads(client.get("/api/schools").get_data(as_text=True))
        print(f"  baking /api/schools/<id>/pathways for {len(schools)} schools")
        for s in schools:
            write_response_json(
                client,
                f"/api/schools/{s['id']}/pathways",
                os.path.join(DATA_DIR, "schools", f"{s['id']}-pathways.json"),
            )

        # 4. Per-program detail (mirror /api/programs/<id>).
        programs = json.loads(client.get("/api/programs").get_data(as_text=True))
        print(f"  baking /api/programs/<id> for {len(programs)} programs")
        for p in programs:
            write_response_json(
                client,
                f"/api/programs/{p['id']}",
                os.path.join(DATA_DIR, "programs", f"{p['id']}.json"),
            )

        # 5. Per-position detail (mirror /api/positions/<id>).
        position_ids = []
        for p in programs:
            prog_resp = client.get(f"/api/programs/{p['id']}")
            for pos in json.loads(prog_resp.get_data(as_text=True))["positions"]:
                position_ids.append(pos["id"])
        print(f"  baking /api/positions/<id> for {len(position_ids)} positions")
        for pid in position_ids:
            write_response_json(
                client,
                f"/api/positions/{pid}",
                os.path.join(POSITIONS_DIR, f"{pid}.json"),
            )

        # 6. Render index.html.
        print("  rendering templates/index.html -> docs/index.html")
        index_html = client.get("/").get_data(as_text=True)
        index_html = rewrite_index_for_static(index_html, static_base=".")
        with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
            f.write(index_html)

        # 7. Render programs page as a static snapshot.
        print("  rendering templates/programs.html -> docs/programs/index.html")
        programs_html = client.get("/programs").get_data(as_text=True)
        programs_html = rewrite_programs_for_static(programs_html, static_base="..")
        os.makedirs(os.path.join(DOCS_DIR, "programs"), exist_ok=True)
        with open(os.path.join(DOCS_DIR, "programs", "index.html"), "w", encoding="utf-8") as f:
            f.write(programs_html)

        # 8. A small redirect at /programs.html for nicer URLs (Pages serves
        #    /programs/ as a directory; some users will type /programs.html).
        with open(os.path.join(DOCS_DIR, "programs.html"), "w", encoding="utf-8") as f:
            f.write(
                '<!DOCTYPE html><html><head>'
                '<meta http-equiv="refresh" content="0; url=./programs/">'
                '<link rel="canonical" href="./programs/">'
                '</head></html>\n'
            )

        # 9. A .nojekyll marker so Pages doesn't try to Jekyll-process the
        #    static files (which would mangle files starting with underscores).
        with open(os.path.join(DOCS_DIR, ".nojekyll"), "w") as f:
            f.write("")

    print("[build_static] Done.")
    print(f"  Total files: {sum(len(files) for _, _, files in os.walk(DOCS_DIR))}")


if __name__ == "__main__":
    main()
