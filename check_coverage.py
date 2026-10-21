
import sqlite3

db = sqlite3.connect("white_petals_sales.db")

checks = [
    ("Company name", "company_name"),
    ("Industry", "industry"),
    ("Address", "address"),
    ("Area", "area"),
    ("Phone", "phone"),
    ("Email", "email"),
    ("Website", "website"),
    ("Source URL", "source_url"),
]

total = db.execute(
    "SELECT COUNT(*) FROM companies"
).fetchone()[0]

print(f"Total records: {total}\n")

for label, column in checks:
    count = db.execute(
        f"""
        SELECT COUNT(*) FROM companies
        WHERE "{column}" IS NOT NULL
          AND TRIM("{column}") != ''
        """
    ).fetchone()[0]

    print(f"{label}: {count}/{total}")

print("\nIndustry/category breakdown:")
for industry, count in db.execute("""
    SELECT industry, COUNT(*)
    FROM companies
    GROUP BY industry
    ORDER BY COUNT(*) DESC
    LIMIT 15
"""):
    print(f"{industry or '(blank)'}: {count}")

db.close()