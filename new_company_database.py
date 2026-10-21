import argparse
import csv
from datetime import date
from pathlib import Path

from main import (
    DEFAULT_CATEGORIES,
    build_lead_record,
    fetch_businesses,
    normalize_search_locations,
)

FIELDS = [
    "Date Collected",
    "Company / Business Name",
    "Business Category",
    "Industry / Type",
    "Address",
    "Area / Locality",
    "City",
    "State",
    "PIN Code",
    "Phone",
    "Email",
    "Official Website",
    "Opening Hours",
    "Latitude",
    "Longitude",
    "Source",
    "Source Record URL",
    "Data Verification Status",
    "Data Completeness",
    "Recommended Next Action",
    "Corporate Sales Fit",
    "Notes",
]


def get_location(item):
    if "lat" in item and "lon" in item:
        return item["lat"], item["lon"]
    center = item.get("center", {})
    return center.get("lat", ""), center.get("lon", "")


def main():
    parser = argparse.ArgumentParser(
        description="Collect public OpenStreetMap business listings by location."
    )
    parser.add_argument(
        "--city",
        default="Bengaluru",
        help="City, district, or state; separate up to five locations with commas",
    )
    parser.add_argument(
        "--output",
        default="company_database.csv",
        help="CSV output file (default: company_database.csv)",
    )
    parser.add_argument(
        "--category",
        action="append",
        dest="categories",
        help="Category key to search; repeat as needed",
    )
    args = parser.parse_args()

    try:
        locations = normalize_search_locations(args.city)
        elements = fetch_businesses(args.city, args.categories or DEFAULT_CATEGORIES)
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))

    records = []
    seen = set()
    for item in elements:
        lead = build_lead_record(item)
        if not lead:
            continue
        tags = item.get("tags", {})
        name = lead["Company Name"]
        city = lead["City"]
        state = lead["State"]
        latitude, longitude = get_location(item)
        duplicate_key = (
            name.casefold(),
            city.casefold(),
            state.casefold(),
            str(latitude)[:10],
            str(longitude)[:10],
        )
        if duplicate_key in seen:
            continue
        seen.add(duplicate_key)

        street_parts = [tags.get("addr:housenumber", ""), tags.get("addr:street", "")]
        category = (
            tags.get("office")
            or tags.get("industrial")
            or tags.get("amenity")
            or tags.get("building")
            or tags.get("landuse")
            or "Business / premises"
        )
        industry = tags.get("industry") or category
        fit = (
            "Potential corporate prospect - verify"
            if any(word in f"{name} {category} {industry}".casefold()
                   for word in ("office", "industrial", "bank", "company"))
            else "Needs manual review"
        )
        records.append({
            "Date Collected": date.today().isoformat(),
            "Company / Business Name": name,
            "Business Category": lead["Company Category"],
            "Industry / Type": industry,
            "Address": " ".join(part for part in street_parts if part),
            "Area / Locality": tags.get("addr:suburb", ""),
            "City": city,
            "State": state,
            "PIN Code": tags.get("addr:postcode", ""),
            "Phone": lead["Phone"],
            "Email": lead["Email"],
            "Official Website": lead["Website"],
            "Opening Hours": tags.get("opening_hours", ""),
            "Latitude": latitude,
            "Longitude": longitude,
            "Source": "OpenStreetMap",
            "Source Record URL": lead["Source URL"],
            "Data Verification Status": "Not independently verified",
            "Data Completeness": lead["Data Completeness"],
            "Recommended Next Action": lead["Recommended Next Action"],
            "Corporate Sales Fit": fit,
            "Notes": "Public map listing; verify details before contacting",
        })

    output = Path(args.output)
    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)

    print(f"Search locations: {', '.join(locations)}")
    print("Records collected:", len(records))
    print("Output file:", output.resolve())
    print("Source: OpenStreetMap; records are not independently verified.")


if __name__ == "__main__":
    main()
