#!/usr/bin/env python3
"""
Creates sample_data/contacts.csv, dated relative to today so the follow-up job
always has something to do when you run the demo.

    python make_sample_contacts.py
"""

import csv
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent

CONTACTS = [
    # name, email, company, topic, days_since_last_touch, stage, opted_out
    ("Jane Alvarez", "jane@acme.example", "Acme Logistics", "weekly reporting", 0, "new", ""),
    ("Marcus Reed", "marcus@northgate.example", "Northgate Retail", "invoice matching", 4, "contacted", ""),
    ("Priya Nair", "priya@orchard.example", "Orchard Health", "patient intake forms", 8, "contacted", ""),
    ("Tom Becker", "tom@blueharbor.example", "Blue Harbor", "shipment tracking", 1, "new", ""),
    ("Sofia Rossi", "sofia@atlasfreight.example", "Atlas Freight", "carrier rate collection", 12, "contacted", ""),
    ("David Kim", "david@lumen.example", "Lumen Retail", "stock sync", 6, "new", ""),
    ("Grace Okafor", "grace@harborvale.example", "Harbor & Vale", "already a customer", 3, "customer", ""),
    ("Ivan Petrov", "ivan@sequoia.example", "Sequoia Labs", "unsubscribed", 2, "new", "yes"),
]


def main() -> None:
    today = date.today()
    rows = []
    for name, email, company, topic, days, stage, opted_out in CONTACTS:
        rows.append({
            "contact_id": f"C{100 + len(rows)}",
            "name": name,
            "email": email,
            "company": company,
            "topic": topic,
            "last_touch": (today - timedelta(days=days)).isoformat(),
            "stage": stage,
            "opted_out": opted_out,
        })
    path = HERE / "contacts.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} contacts to {path}")


if __name__ == "__main__":
    main()
