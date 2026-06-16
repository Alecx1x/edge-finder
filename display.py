"""All terminal rendering via `rich`. Nothing here touches the network."""
import sys

# Windows consoles default to cp1252 and crash on box-drawing / arrow glyphs.
# Force UTF-8 on the underlying streams before rich grabs them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.markup import escape

console = Console()

TIER_STYLE = {"Low": "dim", "Medium": "yellow", "High": "green", "Strong": "bold green"}


def banner():
    console.print(
        Panel(
            Align.center(
                Text("PREDICTION MARKET  ·  EDGE FINDER", style="bold cyan")
                + Text("\nMMA · Basketball · Soccer · Tennis", style="dim")
            ),
            border_style="cyan",
        )
    )


def _pct(x):
    return f"{x * 100:5.1f}%"


def _odds(o):
    return f"{'+' if o > 0 else ''}{int(round(o))}"


def render_report(report):
    m = report["matchup"]
    a, b = m["a"], m["b"]
    na, nb = escape(a["name"]), escape(b["name"])

    header = Text()
    header.append(f"{na}", style="bold white")
    header.append("   vs   ", style="dim")
    header.append(f"{nb}", style="bold white")
    sub = f"{escape(m['league'])}  ·  {m.get('bookmaker_count', 0)} books"
    if m.get("commence_time"):
        sub += f"  ·  {m['commence_time']}"
    console.print(Panel(Align.center(header + Text(f"\n{sub}", style="dim")),
                        border_style="cyan", title=f"[bold]{report['sport']}[/bold]"))

    # --- probabilities table -------------------------------------------------
    t = Table(expand=True, header_style="bold")
    t.add_column("Side", style="bold")
    t.add_column("Odds", justify="right")
    t.add_column("Implied", justify="right")
    t.add_column("Model", justify="right")
    t.add_column("Edge", justify="right")
    for side, name in (("a", na), ("b", nb)):
        edge = report["edge"][side]
        es = "green" if edge >= 0.02 else "red" if edge <= -0.02 else "dim"
        t.add_row(
            name,
            _odds(report["matchup"][side]["odds"]),
            _pct(report["implied"][side]),
            _pct(report["model"][side]),
            Text(f"{edge * 100:+5.1f} pts", style=es),
        )
    console.print(t)

    # --- per-variable breakdown ---------------------------------------------
    vt = Table(expand=True, header_style="bold", title="Variable Breakdown")
    vt.add_column("Variable")
    vt.add_column("W", justify="right")
    vt.add_column(f"{na[:14]}", justify="right")
    vt.add_column(f"{nb[:14]}", justify="right")
    vt.add_column("Source", style="dim")
    vt.add_column("Notes", style="dim")
    for r in report["rows"]:
        if r["available"]:
            sa = Text(f"{r['score_a']:.0f}", style="bold")
            sb = Text(f"{r['score_b']:.0f}", style="bold")
            note = f"{r['detail_a']} | {r['detail_b']}"
        else:
            sa = sb = Text("n/a", style="dim")
            note = r["detail_a"] or "unavailable"
        wstyle = "dim" if r["weight"] == 0 else ("yellow" if r["weight"] != 1.0 else "")
        vt.add_row(r["label"], Text(f"{r['weight']:.2f}", style=wstyle),
                   sa, sb, r["source"] or "—", note[:46])
    console.print(vt)

    # --- recommendation ------------------------------------------------------
    rec = report["recommendation"]
    tier_style = TIER_STYLE.get(rec["tier"], "white")
    avail = report["availability"]
    if rec["bet"]:
        label = Text(f"BET  {escape(rec['name'])}", style=f"bold {tier_style}")
        label.append(f"   (+{rec['edge'] * 100:.1f} pts edge)", style=tier_style)
    else:
        label = Text("PASS — no actionable edge", style="bold dim")

    body = Text()
    body.append(label)
    body.append(f"\nConfidence: ", style="dim")
    body.append(rec["tier"], style=f"bold {tier_style}")
    body.append(f"     Data coverage: {avail * 100:.0f}% of weighted variables", style="dim")
    if report["drivers"]:
        body.append("\nDriven by: ", style="dim")
        body.append(", ".join(f"{d['label']}→{escape(d['favors'])}" for d in report["drivers"]))
    if avail < 0.5:
        body.append("\n⚠ Low live-data coverage: model is leaning on the market line. "
                    "Treat edge as soft.", style="yellow")

    console.print(Panel(body, border_style=tier_style, title="Recommendation"))


def render_weights(cfg, variables):
    t = Table(title="Variable Weights (0.0–2.0)", header_style="bold", expand=True)
    t.add_column("#", justify="right", style="cyan")
    t.add_column("Variable")
    t.add_column("Key", style="dim")
    t.add_column("Weight", justify="right")
    for i, v in enumerate(variables, 1):
        w = cfg["weights"].get(v["key"], 1.0)
        ws = "dim" if w == 0 else ("yellow" if w != 1.0 else "green")
        t.add_row(str(i), v["label"], v["key"], Text(f"{w:.2f}", style=ws))
    console.print(t)


def info(msg):
    console.print(f"[cyan]›[/cyan] {escape(msg)}")


def warn(msg):
    console.print(f"[yellow]⚠ {escape(msg)}[/yellow]")


def error(msg):
    console.print(f"[red]✗ {escape(msg)}[/red]")


def success(msg):
    console.print(f"[green]✓ {escape(msg)}[/green]")
