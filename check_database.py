
import sqlite3

connection = sqlite3.connect("white_petals_sales.db")

total = connection.execute(
    "SELECT COUNT(*) FROM companies"
).fetchone()[0]

print("Total companies:", total)

print("\nSample records:")
for row in connection.execute("""
    SELECT company_name, industry, phone, email, website
    FROM companies
    LIMIT 10
"""):
    print(row)

print("\nContact information coverage:")
for label, query in [
    ("With phone", "SELECT COUNT(*) FROM companies WHERE phone != ''"),
    ("With email", "SELECT COUNT(*) FROM companies WHERE email != ''"),
    ("With website", "SELECT COUNT(*) FROM companies WHERE website != ''")
]:
    count = connection.execute(query).fetchone()[0]
    print(f"{label}: {count}")

connection.close()