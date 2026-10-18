#!/usr/bin/env python3
"""Discover PIB agriculture, farmer and education releases.
Newly discovered entries are clearly marked for review; this script does not claim
to have read/verified the full notification or translate its detailed terms.
"""
import json, re, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from html import unescape

IST = timezone(timedelta(hours=5, minutes=30))
FEED_PATH = Path("data/alerts.json")
FEEDS = [
    "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
    "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=2&Regid=3",
]
KEYWORDS = {
 "agri": ["agriculture", "farmer", "farmers", "crop", "kisan", "paddy", "rice", "procurement", "minimum support price", "msp", "fertilizer", "fertiliser", "irrigation", "horticulture", "fisheries", "animal husbandry", "drought", "seed", "soil", "pm-kisan", "pm kisan", "crop insurance", "farming", "agri"],
 "edu": ["education", "school", "student", "scholarship", "university", "college", "examination", "exam", "nmmss", "literacy", "education ministry", "academic"]
}
def strip_html(s):
    return re.sub(r"\\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()
def category(title):
    t=title.lower()
    if any(k in t for k in ["scholarship","education","school","student","university","college","exam","nmmss"]): return "Education"
    if any(k in t for k in ["loan","credit"]): return "Loans"
    if any(k in t for k in ["subsidy","subsidies"]): return "Subsidies"
    if any(k in t for k in ["insurance","fasal bima"]): return "Insurance"
    if any(k in t for k in ["land record","land records"]): return "Land"
    if any(k in t for k in ["payment","disburs"]): return "Payments"
    if any(k in t for k in ["scheme","yojana","pm-kisan","pm kisan"]): return "Central schemes"
    return "Crops & MSP"
def date_from_item(item):
    raw = item.findtext("pubDate") or ""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).astimezone(IST).date().isoformat()
    except Exception:
        return datetime.now(IST).date().isoformat()
def main():
    data=json.loads(FEED_PATH.read_text(encoding="utf-8"))
    alerts=data.get("alerts", [])
    known={a.get("url","").rstrip("/") for a in alerts}
    added=0
    for feed_url in FEEDS:
        try:
            req=urllib.request.Request(feed_url, headers={"User-Agent":"TGSchemes-OfficialNoticeMonitor/1.0"})
            with urllib.request.urlopen(req, timeout=25) as resp: raw=resp.read()
            root=ET.fromstring(raw)
            items=root.findall(".//item")
            for item in items:
                title=strip_html(item.findtext("title"))
                link=(item.findtext("link") or "").strip()
                desc=strip_html(item.findtext("description"))
                hay=(title+" "+desc).lower()
                if not title or not link.startswith("https://") or not any(k in hay for group in KEYWORDS.values() for k in group): continue
                key=link.rstrip("/")
                if key in known: continue
                dept="Press Information Bureau (PIB) — department to verify"
                date=date_from_item(item)
                education=category(title)=="Education"
                if education:
                    te=["కొత్త PIB విద్యా సంబంధిత ప్రకటన గుర్తించబడింది. పూర్తి ప్రకటన చదివి అర్హతలు, తేదీలు, ప్రయోజనాలను ధృవీకరించాలి.","ప్రస్తుతం ఇది స్వయంచాలకంగా గుర్తించిన సమాచారం మాత్రమే; దరఖాస్తు ప్రారంభమైందని లేదా ప్రయోజనం ఆమోదించబడిందని భావించవద్దు."]
                    en=["A new PIB education-related release was detected. Read the full release to verify eligibility, dates and benefits.","This is an automatically detected item awaiting review; do not assume an application window or approved benefit."]
                else:
                    te=["కొత్త PIB వ్యవసాయం/రైతులకు సంబంధించిన ప్రకటన గుర్తించబడింది. పూర్తి ప్రకటన చదివి తెలంగాణకు వర్తింపును, అర్హతలు మరియు తేదీలను ధృవీకరించాలి.","ఇది స్వయంచాలకంగా గుర్తించిన సమాచారం మాత్రమే; కొత్త సబ్సిడీ లేదా చెల్లింపు ఆమోదమైందని భావించవద్దు."]
                    en=["A new PIB agriculture/farmer-related release was detected. Review the full release for Telangana applicability, eligibility and dates.","This is an automatically detected item awaiting review; do not assume a new subsidy or payment has been approved."]
                alerts.append({"id":"pib-auto-"+re.sub(r"[^a-z0-9]+","-",title.lower())[:70].strip("-"),"title":title[:180],"titleTe":"","date":date,"addedAt":datetime.now(IST).date().isoformat(),"department":dept,"category":category(title),"state":"Advisory / information","fullText":"scanned","review":"auto","url":link,"pointsTe":te,"pointsEn":en})
                known.add(key); added+=1
        except Exception as exc:
            print("Feed check failed:", feed_url, str(exc))
    data["lastChecked"]=datetime.now(IST).isoformat(timespec="seconds")
    data["alerts"]=sorted(alerts, key=lambda a:(a.get("date",""),a.get("addedAt","")), reverse=True)
    FEED_PATH.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"PIB check finished: {added} new candidate(s); {len(data['alerts'])} total entries.")
if __name__=="__main__": main()
