import html
import json


def render(report, format="json"):
    if format == "json":
        return json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
    rows = [(r["name"], r["used"], r["capacity"], r["budget"], r.get("growth", "—"), r["span"])
            for r in report["regions"]]
    if format == "markdown":
        cell = lambda x: str(x).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
        result = ["# Firmware size review", "", "Policy: " + ("PASS" if report["ok"] else "FAIL"), "",
                  "| Region | Used | Capacity | Budget | Growth | Span |", "|---|---:|---:|---:|---:|---:|"]
        result.extend("| " + " | ".join(map(cell, row)) + " |" for row in rows)
        result.extend(["", "Violations: " + cell(json.dumps(report["violations"]))])
        return "\n".join(result) + "\n"
    esc = lambda value: html.escape(str(value), quote=True)
    body = ["<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>",
            "<title>Firmware size review</title><style>body{font:16px system-ui;margin:2rem;color:#172b4d}"
            "table{border-collapse:collapse;width:100%}td,th{padding:.6rem;border:1px solid #ccc;text-align:left}"
            "th{background:#edf2f7}pre,td{white-space:pre-wrap;overflow-wrap:anywhere}h1{color:#124559}</style>",
            "<h1>Firmware size review</h1><p>Policy: <strong>" + ("PASS" if report["ok"] else "FAIL") +
            "</strong></p><p>" + esc(report["file"]) + "</p><p>All sizes are bytes. Used is the union of occupied address ranges; span includes gaps.</p>",
            "<table><tr><th>Region</th><th>Used</th><th>Capacity</th><th>Budget</th><th>Growth</th><th>Span</th></tr>"]
    body.extend("<tr>" + "".join("<td>" + esc(x) + "</td>" for x in row) + "</tr>" for row in rows)
    body.append("</table>")
    for region in report["regions"]:
        body.append("<h2>" + esc(region["name"]) + "</h2><h3>Largest allocations</h3><table><tr><th>Section</th><th>Placement</th><th>Size</th><th>Map line</th></tr>")
        for entry in region["allocations"][:20]:
            body.append("<tr>" + "".join("<td>" + esc(entry[k]) + "</td>" for k in ("section", "kind", "size", "line")) + "</tr>")
        body.append("</table>")
        if "contributions" in region:
            body.append("<h3>Largest section changes</h3><table><tr><th>Section</th><th>Placement</th><th>Before</th><th>After</th><th>Growth</th></tr>")
            for entry in region["contributions"][:20]:
                body.append("<tr>" + "".join("<td>" + esc(entry[k]) + "</td>" for k in ("section", "kind", "before", "after", "growth")) + "</tr>")
            body.append("</table>")
    body.append("<h2>Policy findings</h2><pre>" + esc(json.dumps(report["violations"], indent=2)) + "</pre><h2>Interpretation limits</h2><ul>")
    body.extend("<li>" + esc(x) + "</li>" for x in report["limitations"])
    body.append("</ul></html>\n")
    return "".join(body)
