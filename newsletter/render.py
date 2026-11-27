"""Write the page: one static HTML file with the data embedded, plus the data as JSON."""

import json
import sqlite3

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config, views


def run(conn: sqlite3.Connection) -> None:
    data = views.build(conn)
    env = Environment(loader=FileSystemLoader(config.ROOT / "newsletter" / "templates"),
                      autoescape=select_autoescape())
    page = env.get_template("brief.html").render(data=data)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    (config.OUTPUT_DIR / "index.html").write_text(page)
    (config.OUTPUT_DIR / "data.json").write_text(json.dumps(data))
    print(f"render: {len(data['storylines'])} storylines -> {config.OUTPUT_DIR / 'index.html'}")
