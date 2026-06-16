"""Insider-buying tracker — the stock market's "smart money" signal (SEC Form 4).

When a company's own executives/directors buy their stock on the open market with
their own money, it's one of the few genuinely informative public signals — they
know their business better than anyone. (Sells are noisy — people sell for taxes,
houses, diversification — and grants/awards aren't real buys. So we surface and
score OPEN-MARKET BUYS, transaction code 'P', above everything else.)

All free via SEC EDGAR (no key; SEC just asks for a descriptive User-Agent):
  ticker -> CIK (company_tickers.json) -> recent Form 4 filings (submissions API)
  -> each filing's full-submission text -> parse the <ownershipDocument> XML.
"""
import re
import xml.etree.ElementTree as ET

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_TXT = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{accession}.txt"

# SEC requires a UA that identifies the requester.
_UA = {"User-Agent": "Money Lab research tool money-lab@example.com"}

_TICKER_CACHE = {}

CODE_LABEL = {"P": "buy", "S": "sell", "A": "grant", "M": "option exercise",
              "G": "gift", "F": "tax withhold", "C": "conversion"}


def _get_json(url):
    try:
        r = requests.get(url, headers=_UA, timeout=15)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Parsing (testable)
# --------------------------------------------------------------------------- #
def extract_ownership_xml(submission_text):
    """Pull the <ownershipDocument> block out of a full-submission .txt file."""
    m = re.search(r"<ownershipDocument>.*?</ownershipDocument>", submission_text or "", re.DOTALL)
    return m.group(0) if m else None


def _role(rel):
    if rel is None:
        return ""
    parts = []
    if rel.findtext("isOfficer") in ("1", "true"):
        parts.append(rel.findtext("officerTitle") or "Officer")
    if rel.findtext("isDirector") in ("1", "true"):
        parts.append("Director")
    if rel.findtext("isTenPercentOwner") in ("1", "true"):
        parts.append("10% owner")
    return ", ".join(parts)


def parse_form4(xml_text):
    """Parse one Form 4 ownershipDocument -> {owner, role, symbol, transactions[]}."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    owner = root.findtext("reportingOwner/reportingOwnerId/rptOwnerName") or ""
    role = _role(root.find("reportingOwner/reportingOwnerRelationship"))
    symbol = root.findtext("issuer/issuerTradingSymbol") or ""

    txns = []
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = t.findtext("transactionCoding/transactionCode") or ""
        shares = _f(t.findtext("transactionAmounts/transactionShares/value"))
        price = _f(t.findtext("transactionAmounts/transactionPricePerShare/value"))
        ad = t.findtext("transactionAmounts/transactionAcquiredDisposedCode/value") or ""
        date = t.findtext("transactionDate/value") or ""
        if shares is None:
            continue
        value = round(shares * price, 2) if price is not None else None
        txns.append({
            "date": date, "code": code, "label": CODE_LABEL.get(code, code or "?"),
            "acquired": ad == "A", "shares": shares, "price": price, "value": value,
            "is_buy": code == "P", "is_sell": code == "S",
        })
    return {"owner": owner, "role": role, "symbol": symbol, "transactions": txns}


def summarize(transactions):
    """Aggregate flattened transactions into the headline numbers."""
    buys = [t for t in transactions if t["is_buy"] and t.get("value")]
    sells = [t for t in transactions if t["is_sell"] and t.get("value")]
    buy_val = round(sum(t["value"] for t in buys), 2)
    sell_val = round(sum(t["value"] for t in sells), 2)
    return {
        "buy_value": buy_val, "sell_value": sell_val,
        "net_value": round(buy_val - sell_val, 2),
        "n_buys": len(buys), "n_sells": len(sells),
        "n_buyers": len({t["owner"] for t in buys if t.get("owner")}),
    }


# --------------------------------------------------------------------------- #
# Live orchestration
# --------------------------------------------------------------------------- #
def _cik_for(ticker):
    if not _TICKER_CACHE:
        data = _get_json(TICKERS_URL) or {}
        for row in data.values():
            _TICKER_CACHE[str(row.get("ticker", "")).upper()] = (
                str(row.get("cik_str", "")).zfill(10), row.get("title", ""))
    return _TICKER_CACHE.get(ticker.upper())


def insider_activity(ticker, max_filings=25):
    """Recent insider (Form 4) transactions for a ticker. Returns (report, error)."""
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return None, "Enter a ticker."
    hit = _cik_for(ticker)
    if not hit:
        return None, f"Couldn't find a SEC CIK for '{ticker}'."
    cik, company = hit

    subs = _get_json(SUBMISSIONS.format(cik=cik))
    recent = ((subs or {}).get("filings") or {}).get("recent") or {}
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    if not forms:
        return None, "No filings found for this company."

    cik_int = str(int(cik))
    transactions, fetched = [], 0
    for i, form in enumerate(forms):
        if form != "4" or fetched >= max_filings:
            continue
        acc = accessions[i]
        nodash = acc.replace("-", "")
        txt = _get_text(ARCHIVE_TXT.format(cik=cik_int, nodash=nodash, accession=acc))
        fetched += 1
        xml = extract_ownership_xml(txt)
        if not xml:
            continue
        parsed = parse_form4(xml)
        if not parsed:
            continue
        for t in parsed["transactions"]:
            t["owner"], t["role"] = parsed["owner"], parsed["role"]
            transactions.append(t)

    transactions.sort(key=lambda t: t.get("date", ""), reverse=True)
    return {"ticker": ticker, "company": company, "cik": cik,
            "transactions": transactions, "summary": summarize(transactions),
            "filings_scanned": fetched}, None


def _get_text(url):
    try:
        r = requests.get(url, headers=_UA, timeout=15)
        return r.text if r.status_code == 200 else ""
    except requests.RequestException:
        return ""


if __name__ == "__main__":
    import sys
    rep, err = insider_activity(sys.argv[1] if len(sys.argv) > 1 else "NVDA")
    if err:
        print(err)
    else:
        s = rep["summary"]
        print(f"{rep['company']} ({rep['ticker']}): {len(rep['transactions'])} txns; "
              f"buys ${s['buy_value']:,.0f} / sells ${s['sell_value']:,.0f}; {s['n_buyers']} buyers")
        for t in rep["transactions"][:12]:
            print(f"  {t['date']}  {t['label']:<6} {t['shares']:>10,.0f} @ {t['price']}  {t['owner']} ({t['role']})")
