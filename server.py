import json
import os
import random
import string
import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

DB_FILE = Path(__file__).parent / "expenses.json"

CATEGORIES = [
    "Meals",
    "Travel",
    "Software",
    "Office Supplies",
    "Entertainment",
    "Other",
]
HUMAN_STATUSES = ["pending", "approved", "rejected"]

POLICY_TEXT = """Company expense policy — apply these rules yourself before calling this tool:
- Meals: approved if under $75. Flag if $75 or more.
- Travel (flights, hotels, cabs): approved if under $1000. Flag if $1000 or more.
- Software & subscriptions: approved if under $200/month.
- Office supplies: always approved.
- Entertainment or alcohol: always flag, never approve automatically.
- Anything else, or anything ambiguous: flag for manual review.
Decide the category and policy_status yourself using these rules, then call this tool once per expense."""

mcp = FastMCP(
    name="PolicyPilot",
    instructions=(
        "PolicyPilot lets you log a company expense on behalf of the user. "
        "Read the description of what they bought, decide the category and whether "
        "it is within company policy, then call log_expense with your determination. "
        + POLICY_TEXT
    ),
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)



def _load():
    if not DB_FILE.exists():
        return []
    try:
        return json.loads(DB_FILE.read_text())
    except json.JSONDecodeError:
        return []


def _save(expenses):
    DB_FILE.write_text(json.dumps(expenses, indent=2))


def _new_id():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


@mcp.tool()
def log_expense(
    description: str,
    amount: float,
    category: str,
    policy_status: str,
    vendor: str = "",
    flag_reason: str = "",
) -> str:
    """Log a company expense after checking it against policy.

    Args:
        description: What was purchased, in plain language.
        amount: Amount in US dollars.
        category: One of Meals, Travel, Software, Office Supplies, Entertainment, Other.
        policy_status: Your determination, either "approved" or "flagged", based on the
            policy rules in this server's instructions.
        vendor: Vendor or merchant name, if known.
        flag_reason: If flagged, a short reason why. Leave blank if approved.
    """
    if category not in CATEGORIES:
        category = "Other"
    if policy_status not in ("approved", "flagged"):
        policy_status = "flagged"

    expenses = _load()
    entry = {
        "id": _new_id(),
        "description": description,
        "vendor": vendor,
        "amount": amount,
        "category": category,
        "policy_status": policy_status,
        "flag_reason": flag_reason,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        "human_status": "pending",
    }
    expenses.insert(0, entry)
    _save(expenses)

    return (
        f'Logged "{description}" (${amount:g}) as {category}, {policy_status}'
        + (f" — {flag_reason}" if flag_reason else "")
        + ". It's now on the live dashboard for a human to review."
    )


PAGE_STYLE = """
body{font-family:ui-sans-serif,-apple-system,"Segoe UI",sans-serif;margin:0;background:#0b0c10;color:#eaeaea;}
.wrap{max-width:1000px;margin:0 auto;padding:40px 20px;}
h1{font-size:28px;margin-bottom:4px;}
p.sub{color:#9a9a9a;margin-top:0;}
table{width:100%;border-collapse:collapse;margin-top:24px;}
th,td{padding:10px;border-bottom:1px solid #222;text-align:left;font-size:14px;vertical-align:middle;}
th{color:#9a9a9a;font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.05em;}
.badge{padding:3px 8px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap;}
.badge.approved{background:#133d2b;color:#5fd98a;}
.badge.flagged{background:#3d1f13;color:#ffb37a;}
select,button{background:#1a1b20;color:#eaeaea;border:1px solid #333;border-radius:6px;padding:5px 8px;font-size:13px;}
button{cursor:pointer;background:#2f5d50;border:none;margin-left:6px;}
.empty{color:#777;padding:40px 0;text-align:center;}
.reason{color:#9a9a9a;display:block;font-size:11px;margin-top:2px;}
footer{color:#666;font-size:12px;margin-top:40px;}
code{background:#1a1b20;padding:1px 6px;border-radius:4px;}
"""


def _row_html(e):
    cat_options = "".join(
        f'<option value="{c}" {"selected" if c == e["category"] else ""}>{c}</option>'
        for c in CATEGORIES
    )
    status_options = "".join(
        f'<option value="{s}" {"selected" if s == e["human_status"] else ""}>{s}</option>'
        for s in HUMAN_STATUSES
    )
    when = e["created_at"].replace("T", " ").split(".")[0]
    reason = (
        f'<span class="reason">{e["flag_reason"]}</span>'
        if e.get("flag_reason")
        else ""
    )
    return f"""
    <tr>
      <td>{when}</td>
      <td>{e["description"]}</td>
      <td>{e.get("vendor") or "—"}</td>
      <td>${e["amount"]:g}</td>
      <td><span class="badge {e["policy_status"]}">{e["policy_status"]}</span>{reason}</td>
      <td>
        <form method="post" action="/expenses/{e["id"]}/update" style="display:flex;align-items:center;">
          <select name="category">{cat_options}</select>
          <select name="human_status">{status_options}</select>
          <button type="submit">Save</button>
        </form>
      </td>
    </tr>"""


@mcp.custom_route("/", methods=["GET"])
async def dashboard(request: Request) -> HTMLResponse:
    expenses = _load()
    rows = "".join(_row_html(e) for e in expenses)
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No expenses logged yet. Ask Claude to log one through this server\'s <code>log_expense</code> tool.</td></tr>'
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>PolicyPilot</title><style>{PAGE_STYLE}</style></head>
<body><div class="wrap">
  <h1>PolicyPilot</h1>
  <p class="sub">Expenses your team logs through Claude, reviewed and approved here.</p>
  <table>
    <tr><th>When</th><th>What</th><th>Vendor</th><th>Amount</th><th>Policy (Claude's call)</th><th>Category / Review</th></tr>
    {rows}
  </table>
  <footer>Connect this server to Claude at <code>/mcp</code> to log a new expense.</footer>
</div></body></html>"""
    return HTMLResponse(html)


@mcp.custom_route("/expenses/{expense_id}/update", methods=["POST"])
async def update_expense(request: Request):
    expense_id = request.path_params["expense_id"]
    form = await request.form()
    expenses = _load()
    for e in expenses:
        if e["id"] == expense_id:
            e["category"] = form.get("category", e["category"])
            e["human_status"] = form.get("human_status", e["human_status"])
    _save(expenses)
    return RedirectResponse(url="/", status_code=303)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=port)
