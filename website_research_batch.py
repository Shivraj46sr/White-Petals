
import csv
from pathlib import Path

INPUT = Path("company_research_queue.csv")
OUTPUT = Path("website_research_batch_001.csv")
BATCH_SIZE = 50

FIELDS = [
    "Company Name",
    "Industry / Category",
    "Search Link",
    "Official Website",
    "Public Business Email",
    "Public Phone",
    "Business Address",
    "Evidence URL",
    "Verification Status",
    "Notes",
]

def main():
    if not INPUT.exists():
        print(f"File not found: {INPUT}")
        print("Keep this script in your WhitepetalsAI folder.")
        return

    with INPUT.open(
        "r", newline="", encoding="utf-8-sig"
    ) as file:
        rows = list(csv.DictReader(file))

    # Research promising categories first.
    priority_order = {
        "High - research first": 0,
        "Medium - verify business": 1,
        "Low - review category": 2,
    }

    rows.sort(key=lambda row: (
        priority_order.get(row.get("Priority", ""), 3),
        row.get("Company Name", "").casefold()
    ))

    batch = rows[:BATCH_SIZE]

    with OUTPUT.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()

        for row in batch:
            writer.writerow({
                "Company Name": row.get("Company Name", ""),
                "Industry / Category": row.get(
                    "Industry / Category", ""
                ),
                "Search Link": row.get("Search Link", ""),
                "Official Website": "",
                "Public Business Email": "",
                "Public Phone": "",
                "Business Address": "",
                "Evidence URL": "",
                "Verification Status": "Not checked",
                "Notes": "",
            })

    print("Website research batch created!")
    print("Companies in this batch:", len(batch))
    print("Output file:", OUTPUT.resolve())
    print("Original database and research queue are unchanged.")

if __name__ == "__main__":
    main()