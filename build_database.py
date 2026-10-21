
import csv
import sqlite3
from pathlib import Path
from datetime import date

DB_FILE = Path("white_petals_sales.db")

INPUT_FILES = [
    Path("corporate_leads.csv"),
    Path("company_database.csv"),
    Path("bengaluru_company_database.csv"),
]

def get_value(row, *names):
    for name in names:
        value = row.get(name, "")
        if value and str(value).strip():
            return str(value).strip()
    return ""

def main():
    connection = sqlite3.connect(DB_FILE)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            industry TEXT,
            address TEXT,
            area TEXT,
            city TEXT,
            state TEXT DEFAULT '',
            phone TEXT,
            email TEXT,
            website TEXT,
            source TEXT,
            source_url TEXT,
            verification_status TEXT DEFAULT 'Needs verification',
            lead_score INTEGER DEFAULT 0,
            lead_priority TEXT DEFAULT 'Needs review',
            sales_status TEXT DEFAULT 'New',
            next_follow_up TEXT,
            notes TEXT,
            UNIQUE(company_name, address)
        )
    """)

    added = 0
    duplicates = 0
    files_read = 0

    for path in INPUT_FILES:
        if not path.exists():
            print(f"Skipping missing file: {path}")
            continue

        files_read += 1
        print(f"Importing {path}...")

        with path.open(
            "r", newline="", encoding="utf-8-sig"
        ) as file:
            for row in csv.DictReader(file):
                name = get_value(
                    row, "Company Name",
                    "Company / Business Name"
                )

                if not name:
                    continue

                address = get_value(row, "Address")
                area = get_value(row, "Area / Locality")
                city = get_value(row, "City") or (
                    "" if get_value(row, "State") else "Bengaluru"
                )
                state = get_value(row, "State")

                industry = get_value(
                    row, "Industry", "Industry / Type",
                    "Business Category"
                )

                phone = get_value(row, "Phone")
                email = get_value(row, "Email")
                website = get_value(
                    row, "Official Website", "Website"
                )
                source = get_value(row, "Source", "Lead Source")
                source_url = get_value(
                    row, "Source Record URL"
                )

                # Simple initial score, not a confirmed buying signal.
                text = f"{name} {industry}".casefold()
                keywords = [
                    "software", "technology", "consulting",
                    "manufacturing", "pharma", "engineering",
                    "finance", "logistics", "biotech"
                ]
                score = sum(word in text for word in keywords) * 2

                if website:
                    score += 1
                if phone or email:
                    score += 1

                priority = (
                    "High - review first" if score >= 4
                    else "Medium - review" if score >= 2
                    else "Needs research"
                )

                try:
                    cursor = connection.execute("""
                        INSERT INTO companies (
                            company_name, industry, address, area,
                            city, state, phone, email, website, source,
                            source_url, verification_status,
                            lead_score, lead_priority, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        name, industry, address, area, city, state,
                        phone, email, website, source, source_url,
                        "Needs verification", score, priority,
                        f"Imported on {date.today().isoformat()}"
                    ))

                    if cursor.rowcount:
                        added += 1

                except sqlite3.IntegrityError:
                    duplicates += 1

        connection.commit()

    total = connection.execute(
        "SELECT COUNT(*) FROM companies"
    ).fetchone()[0]

    print("\nWhite Petals Resort database is ready.")
    print(f"Input files processed: {files_read}")
    print(f"New records added: {added}")
    print(f"Duplicate records skipped: {duplicates}")
    print(f"Total companies in database: {total}")
    print(f"Database file: {DB_FILE.resolve()}")

    connection.close()

if __name__ == "__main__":
    main()