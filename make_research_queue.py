
import csv
import sqlite3
from pathlib import Path
from urllib.parse import quote_plus

DB = Path("white_petals_sales.db")
OUTPUT = Path("company_research_queue.csv")

# Broad categories that may indicate a corporate prospect.
# These are leads to review, not confirmed buyers.
PREFERRED = {
    "company", "it", "coworking", "financial", "insurance",
    "telecommunication", "research", "industrial", "commercial",
    "engineering", "technology", "software", "consulting",
    "manufacturing", "logistics", "pharmaceutical"
}

EXCLUDE = {
    "government", "educational_institution", "depot",
    "religious", "place_of_worship"
}

def main():
    if not DB.exists():
        print("Database not found:", DB.resolve())
        return

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT company_name, industry, address, area, city, state,
               phone, email, website, source, source_url
        FROM companies
        ORDER BY company_name
    """).fetchall()

    fields = [
        "Company Name", "Industry / Category", "Address",
        "Area", "City", "State", "Phone", "Email", "Website",
        "Source", "Source URL", "Research Search",
        "Search Link", "Priority", "Research Status"
    ]

    output_rows = []
    seen = set()

    for row in rows:
        name = (row["company_name"] or "").strip()
        industry = (row["industry"] or "").strip()
        category = industry.casefold()

        if not name:
            continue

        key = (
            name.casefold(),
            (row["city"] or "").casefold(),
            (row["state"] or "").casefold(),
        )
        if key in seen:
            continue
        seen.add(key)

        # Category labels can be vague; do not treat them as verified.
        if category in EXCLUDE:
            priority = "Low - review category"
        elif category in PREFERRED:
            priority = "High - research first"
        else:
            priority = "Medium - verify business"

        location = ", ".join(
            value for value in (row["city"] or "", row["state"] or "") if value
        )
        query = f'"{name}" {location + " " if location else ""}official website contact'

        output_rows.append({
            "Company Name": name,
            "Industry / Category": industry,
            "Address": row["address"] or "",
            "Area": row["area"] or "",
            "City": row["city"] or "",
            "State": row["state"] or "",
            "Phone": row["phone"] or "",
            "Email": row["email"] or "",
            "Website": row["website"] or "",
            "Source": row["source"] or "",
            "Source URL": row["source_url"] or "",
            "Research Search": query,
            "Search Link": (
                "https://www.google.com/search?q="
                + quote_plus(query)
            ),
            "Priority": priority,
            "Research Status": "Not researched"
        })

    order = {
        "High - research first": 0,
        "Medium - verify business": 1,
        "Low - review category": 2
    }
    output_rows.sort(
        key=lambda r: (order[r["Priority"]], r["Company Name"].casefold())
    )

    with OUTPUT.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)

    print("Research queue created!")
    print("Unique company names:", len(output_rows))
    print("File:", OUTPUT.resolve())
    print("Search links help research; they do not verify results.")

    conn.close()

if __name__ == "__main__":
    main()