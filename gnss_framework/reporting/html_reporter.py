"""HTML reporter – generates a self-contained test results dashboard.

The output is a single HTML file with embedded CSS and vanilla JavaScript.
No external dependencies are required to open it.  The JS renders the
summary chart and result table entirely client-side, making the file
portable and suitable for attaching to CI/CD artefacts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from gnss_framework.reporting.json_reporter import JSONReporter
from gnss_framework.reporting.models import TestSuiteResult


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GNSS Test Report – {suite_name}</title>
<style>
  :root {{
    --green: #22c55e; --red: #ef4444; --yellow: #eab308;
    --blue: #3b82f6; --gray: #6b7280; --bg: #0f172a; --surface: #1e293b;
    --text: #f1f5f9; --muted: #94a3b8; --border: #334155;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg);
          color: var(--text); padding: 2rem; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
  .meta {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 2rem; }}
  .cards {{ display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 2rem; }}
  .card {{ background: var(--surface); border: 1px solid var(--border);
           border-radius: 0.5rem; padding: 1rem 1.5rem; min-width: 130px; }}
  .card .value {{ font-size: 2rem; font-weight: 700; }}
  .card .label {{ color: var(--muted); font-size: 0.8rem; margin-top: 0.25rem; }}
  .pass {{ color: var(--green); }} .fail {{ color: var(--red); }}
  .error {{ color: var(--yellow); }} .skip {{ color: var(--gray); }}
  .bar-wrap {{ background: var(--surface); border: 1px solid var(--border);
              border-radius: 0.5rem; padding: 1rem 1.5rem; margin-bottom: 2rem; }}
  .bar-wrap h2 {{ font-size: 1rem; margin-bottom: 0.75rem; }}
  .progress {{ height: 1.25rem; border-radius: 0.25rem; overflow: hidden;
               display: flex; background: var(--border); }}
  .progress span {{ display: block; height: 100%; transition: width 0.4s; }}
  table {{ width: 100%; border-collapse: collapse;
           background: var(--surface); border-radius: 0.5rem; overflow: hidden;
           border: 1px solid var(--border); }}
  thead {{ background: #0f172a; }}
  th, td {{ padding: 0.6rem 1rem; text-align: left; font-size: 0.875rem;
            border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 600; }}
  tr:last-child td {{ border-bottom: none; }}
  .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 9999px;
            font-size: 0.75rem; font-weight: 600; }}
  .badge-pass {{ background: #14532d; color: var(--green); }}
  .badge-fail {{ background: #7f1d1d; color: var(--red); }}
  .badge-error {{ background: #713f12; color: var(--yellow); }}
  .badge-skip {{ background: #1f2937; color: var(--gray); }}
  .msg {{ color: var(--muted); font-size: 0.8rem; max-width: 400px;
          white-space: pre-wrap; word-break: break-all; }}
  input#search {{ background: var(--surface); border: 1px solid var(--border);
                 color: var(--text); border-radius: 0.375rem; padding: 0.5rem 0.75rem;
                 width: 100%; max-width: 320px; margin-bottom: 1rem; font-size: 0.875rem; }}
  input#search:focus {{ outline: 2px solid var(--blue); }}
</style>
</head>
<body>
<h1>GNSS Test Report – {suite_name}</h1>
<p class="meta">Generated {generated_at} &nbsp;|&nbsp; Duration: {duration_s}s</p>

<div class="cards">
  <div class="card"><div class="value">{total}</div><div class="label">Total</div></div>
  <div class="card"><div class="value pass">{passed}</div><div class="label">Passed</div></div>
  <div class="card"><div class="value fail">{failed}</div><div class="label">Failed</div></div>
  <div class="card"><div class="value error">{errors}</div><div class="label">Errors</div></div>
  <div class="card"><div class="value skip">{skipped}</div><div class="label">Skipped</div></div>
  <div class="card"><div class="value pass">{pass_rate}%</div><div class="label">Pass Rate</div></div>
</div>

<div class="bar-wrap">
  <h2>Result Distribution</h2>
  <div class="progress" id="bar"></div>
</div>

<input id="search" type="text" placeholder="Filter tests…" oninput="filterTable(this.value)">
<table id="results-table">
<thead>
  <tr><th>#</th><th>Test Name</th><th>Status</th><th>Duration (s)</th><th>Message</th></tr>
</thead>
<tbody id="table-body"></tbody>
</table>

<script>
const DATA = {data_json};

(function() {{
  const body = document.getElementById('table-body');
  DATA.results.forEach((r, i) => {{
    const tr = document.createElement('tr');
    tr.dataset.name = r.name.toLowerCase();
    tr.innerHTML = `
      <td>${{i + 1}}</td>
      <td>${{escHtml(r.name)}}</td>
      <td><span class="badge badge-${{r.status}}">${{r.status}}</span></td>
      <td>${{r.duration_s.toFixed(4)}}</td>
      <td class="msg">${{escHtml(r.message || '')}}</td>`;
    body.appendChild(tr);
  }});

  // Progress bar
  const t = DATA.summary.total || 1;
  const bar = document.getElementById('bar');
  [
    ['passed', 'var(--green)'],
    ['failed', 'var(--red)'],
    ['errors', 'var(--yellow)'],
    ['skipped', 'var(--gray)'],
  ].forEach(([key, color]) => {{
    const pct = (DATA.summary[key] / t * 100).toFixed(1);
    if (pct > 0) {{
      const s = document.createElement('span');
      s.style.width = pct + '%';
      s.style.background = color;
      s.title = `${{key}}: ${{DATA.summary[key]}}`;
      bar.appendChild(s);
    }}
  }});
}})();

function filterTable(q) {{
  const rows = document.querySelectorAll('#table-body tr');
  rows.forEach(r => {{
    r.style.display = r.dataset.name.includes(q.toLowerCase()) ? '' : 'none';
  }});
}}

function escHtml(s) {{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}
</script>
</body>
</html>
"""


class HTMLReporter:
    """Generate a self-contained HTML dashboard from a ``TestSuiteResult``.

    Args:
        output_dir: Directory where the report is written.
    """

    def __init__(self, output_dir: str | Path = "reports") -> None:
        self._output_dir = Path(output_dir)

    def write(self, suite: TestSuiteResult, filename: str | None = None) -> Path:
        """Render the HTML template and write it to disk.

        Returns the path of the written file.
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)

        if filename is None:
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            filename = f"{suite.suite_name.replace(' ', '_')}_{ts}.html"

        payload = JSONReporter._build_payload(suite)
        html = _HTML_TEMPLATE.format(
            suite_name=suite.suite_name,
            generated_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            duration_s=round(suite.total_duration_s, 2),
            total=suite.total,
            passed=suite.passed,
            failed=suite.failed,
            errors=suite.errors,
            skipped=suite.skipped,
            pass_rate=round(suite.pass_rate, 1),
            data_json=json.dumps(payload),
        )

        path = self._output_dir / filename
        path.write_text(html, encoding="utf-8")
        return path
