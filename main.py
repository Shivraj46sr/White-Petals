
import argparse
import csv
import os
import re
import tempfile
import time
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
REQUEST_TIMEOUT_SECONDS = 90
MAX_REQUEST_RETRIES = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRY_DELAY_SECONDS = 30
DEFAULT_CITY = "Bengaluru"
DEFAULT_CATEGORIES = [
    "technology",
    "company_office",
    "event_management",
    "corporate_travel",
    "consulting",
    "industrial",
    "bank",
    "insurance",
    "education",
    "professional_organization",
    "event_venue",
    "retail",
]
CATEGORY_TAGS = {
    "office": ("office", None),
    "technology": ("office", "it"),
    "company_office": ("office", "company"),
    "startup": ("office", "company"),
    "corporate_office": ("office", "company"),
    "event_management": ("office", "event_management"),
    "corporate_travel": ("office", "travel_agent"),
    "consulting": ("office", "consulting"),
    "training": ("office", "educational_institution"),
    "industrial_company": ("office", "company"),
    "industrial": ("industrial", None),
    "landuse=industrial": ("landuse", "industrial"),
    "manufacturing": ("industrial", None),
    "bank": ("amenity", "bank"),
    "finance": ("office", "financial"),
    "insurance": ("office", "insurance"),
    "education": ("office", "educational_institution"),
    "professional_organization": ("office", "association"),
    "event_venue": ("amenity", "events_venue"),
    "retail": ("shop", None),
    "shop": ("shop", None),
    "hotel": ("tourism", "hotel"),
    "event": ("amenity", "events_venue"),
}
LOCATION_ALIASES = {
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "mysore": "Mysuru",
    "mysuru": "Mysuru",
    "bombay": "Mumbai",
    "madras": "Chennai",
    "calcutta": "Kolkata",
}
STATE_ALIASES = {
    "andhra pradesh": "Andhra Pradesh",
    "arunachal pradesh": "Arunachal Pradesh",
    "assam": "Assam",
    "bihar": "Bihar",
    "chhattisgarh": "Chhattisgarh",
    "goa": "Goa",
    "gujarat": "Gujarat",
    "haryana": "Haryana",
    "himachal pradesh": "Himachal Pradesh",
    "jharkhand": "Jharkhand",
    "karnataka": "Karnataka",
    "kerala": "Kerala",
    "madhya pradesh": "Madhya Pradesh",
    "maharashtra": "Maharashtra",
    "manipur": "Manipur",
    "meghalaya": "Meghalaya",
    "mizoram": "Mizoram",
    "nagaland": "Nagaland",
    "odisha": "Odisha",
    "punjab": "Punjab",
    "rajasthan": "Rajasthan",
    "sikkim": "Sikkim",
    "tamil nadu": "Tamil Nadu",
    "telangana": "Telangana",
    "tripura": "Tripura",
    "uttar pradesh": "Uttar Pradesh",
    "uttarakhand": "Uttarakhand",
    "west bengal": "West Bengal",
    "andaman and nicobar islands": "Andaman and Nicobar Islands",
    "chandigarh": "Chandigarh",
    "dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "delhi": "Delhi",
    "jammu and kashmir": "Jammu and Kashmir",
    "ladakh": "Ladakh",
    "lakshadweep": "Lakshadweep",
    "puducherry": "Puducherry",
}
CATEGORY_LABELS = {
    "technology": "Technology / IT offices",
    "company_office": "Company / corporate offices",
    "event_management": "Event management",
    "corporate_travel": "Corporate travel agencies",
    "consulting": "Consulting and training",
    "industrial": "Industrial and manufacturing sites",
    "bank": "Banks",
    "finance": "Financial services",
    "insurance": "Insurance",
    "education": "Educational institutions",
    "professional_organization": "Professional organizations",
    "event_venue": "Event venues",
    "retail": "Retail businesses",
    "hotel": "Hotels",
}
COMPANY_CATEGORIES = (
    "Technology / IT",
    "Startup",
    "Corporate office / business park",
    "Event management",
    "Corporate travel",
    "Training / consulting",
    "Manufacturing / industrial",
    "Banking / financial services",
    "Insurance",
    "Education",
    "Professional organization",
    "Retail / hospitality",
    "Other",
)

LEAD_FIELDS = [
    "Date Added",
    "Company Name",
    "Company Category",
    "Industry",
    "City",
    "State",
    "Contact Person",
    "Job Title",
    "Email",
    "Phone",
    "Website",
    "Service Interested",
    "Event Date",
    "Guest Count",
    "Lead Source",
    "Source URL",
    "Lead Status",
    "Data Completeness",
    "Recommended Next Action",
    "Estimated Value (₹)",
    "Last Contacted",
    "Next Follow-up",
    "Notes",
]


def normalize_search_locations(location_input):
    locations = [
        re.sub(r"\s+", " ", item).strip()
        for item in re.split(r"[,;\n]+", location_input or "")
        if item.strip()
    ]
    if not locations:
        raise ValueError("Enter at least one city, district, or state.")
    if len(locations) > 5:
        raise ValueError("Search up to 5 locations at a time to avoid overloading the public map service.")

    normalized = []
    seen = set()
    for location in locations:
        if len(location) > 100 or any(ord(char) < 32 for char in location):
            raise ValueError("Each location must be 100 characters or fewer.")
        canonical = LOCATION_ALIASES.get(location.casefold(), location)
        canonical = STATE_ALIASES.get(canonical.casefold(), canonical)
        key = canonical.casefold()
        if key not in seen:
            seen.add(key)
            normalized.append(canonical)
    return normalized


def build_overpass_query(city_name, categories):
    locations = normalize_search_locations(city_name)
    category_filters = []
    seen_selectors = set()
    for category in dict.fromkeys(categories):
        if category not in CATEGORY_TAGS:
            raise ValueError(f"Unsupported category: {category}")
        key, value = CATEGORY_TAGS[category]
        selector = f'["{key}"]' if value is None else f'["{key}"="{value}"]'
        if selector in seen_selectors:
            continue
        seen_selectors.add(selector)
        category_filters.append(f"nwr{selector}(area.a);")

    area_names = []
    for location in locations:
        aliases = [location]
        if location == "Bengaluru":
            aliases.append("Bangalore")
        elif location == "Mysuru":
            aliases.append("Mysore")
        for alias in aliases:
            escaped = re.sub(r"([.^$*+?{}\[\]\\|()])", r"\\\1", alias)
            if escaped not in area_names:
                area_names.append(escaped)
    safe_area_pattern = "|".join(area_names).replace("\\", "\\\\").replace('"', '\\"')
    joined_filters = "\n  ".join(category_filters)
    return f"""
[out:json][timeout:60];
area["name"~"^({safe_area_pattern})$",i]["boundary"="administrative"]->.a;
(
  {joined_filters}
);
out center tags;
""".strip()


def normalize_name(raw_name):
    if not raw_name:
        return ""
    return re.sub(r"\s+", " ", raw_name).strip()


def detect_industry(tags):
    for key in ["office", "industrial", "shop", "retail", "amenity", "landuse"]:
        if tags.get(key):
            return tags.get(key)
    return "Business"


def detect_company_category(tags, industry="", company_name=""):
    office = (tags.get("office") or "").casefold()
    amenity = (tags.get("amenity") or "").casefold()
    tourism = (tags.get("tourism") or "").casefold()
    shop = (tags.get("shop") or "").casefold()
    industrial = (tags.get("industrial") or "").casefold()
    landuse = (tags.get("landuse") or "").casefold()
    source_text = f"{industry} {company_name} {office} {amenity} {tourism} {shop} {industrial} {landuse}".casefold()

    if office in ("it", "software"):
        return "Technology / IT"
    if office == "event_management":
        return "Event management"
    if office in ("travel_agent", "tourism"):
        return "Corporate travel"
    if office in ("consulting", "training"):
        return "Training / consulting"
    if office in ("financial", "bank"):
        return "Banking / financial services"
    if office == "insurance":
        return "Insurance"
    if office in ("educational_institution", "school", "university", "college"):
        return "Education"
    if office in ("association", "ngo"):
        return "Professional organization"
    if amenity == "bank":
        return "Banking / financial services"
    if amenity == "events_venue":
        return "Event management"
    if industrial or landuse == "industrial":
        return "Manufacturing / industrial"
    if tourism == "hotel" or shop:
        return "Retail / hospitality"

    text_categories = (
        (("software", "technology", "information technology", " it "), "Technology / IT"),
        (("startup", "start-up"), "Startup"),
        (("event management", "event organiser", "event organizer"), "Event management"),
        (("travel agency", "corporate travel", "travel management"), "Corporate travel"),
        (("consulting", "consultancy", "training company"), "Training / consulting"),
        (("manufacturing", "industrial", "factory"), "Manufacturing / industrial"),
        (("bank", "financial services", "finance"), "Banking / financial services"),
        (("insurance",), "Insurance"),
        (("school", "university", "college", "educational institution"), "Education"),
        (("association", "professional organization", "chamber of commerce"), "Professional organization"),
        (("retail", "hotel", "hospitality", "resort"), "Retail / hospitality"),
        (("office", "business park", "corporate"), "Corporate office / business park"),
    )
    padded_text = f" {source_text} "
    for keywords, category in text_categories:
        if any(keyword in padded_text for keyword in keywords):
            return category
    if office == "company":
        return "Corporate office / business park"
    return "Other"


def parse_contact_info(tags):
    email = ""
    phone = ""

    if tags.get("email"):
        email = tags["email"].split(";")[0].strip()
    if tags.get("contact:email"):
        email = tags["contact:email"].split(";")[0].strip()

    if tags.get("phone"):
        phone = tags["phone"].split(";")[0].strip()
    if tags.get("contact:phone"):
        phone = tags["contact:phone"].split(";")[0].strip()

    return email, phone


def retry_delay(response, retry_number):
    retry_after = response.headers.get("Retry-After", "")
    try:
        delay = float(retry_after)
    except (TypeError, ValueError):
        try:
            retry_date = parsedate_to_datetime(retry_after)
            delay = max(0, (retry_date - datetime.now(retry_date.tzinfo)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            delay = 2 ** (retry_number - 1)
    return min(max(delay, 0), MAX_RETRY_DELAY_SECONDS)


def request_location_listings(location, query):
    for attempt in range(MAX_REQUEST_RETRIES + 1):
        try:
            response = requests.post(
                OVERPASS_URL,
                data={"data": query},
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": "WhitePetalsLeadCollector/1.0"},
            )
        except requests.RequestException as error:
            if attempt == MAX_REQUEST_RETRIES:
                raise RuntimeError(
                    f"Could not retrieve public listings for {location}: {error}"
                ) from error
            time.sleep(min(2 ** attempt, MAX_RETRY_DELAY_SECONDS))
            continue

        if response.status_code in RETRYABLE_STATUS_CODES:
            if attempt == MAX_REQUEST_RETRIES:
                try:
                    response.raise_for_status()
                except requests.RequestException as error:
                    raise RuntimeError(
                        f"Could not retrieve public listings for {location}: {error}"
                    ) from error
                raise RuntimeError(
                    f"The public map service is temporarily unavailable for {location} "
                    f"(HTTP {response.status_code})."
                )
            time.sleep(retry_delay(response, attempt + 1))
            continue

        try:
            response.raise_for_status()
            data = response.json()
        except ValueError as error:
            raise RuntimeError(
                f"The public map service returned invalid JSON for {location}."
            ) from error
        except requests.RequestException as error:
            raise RuntimeError(
                f"Could not retrieve public listings for {location}: {error}"
            ) from error

        if not isinstance(data, dict) or not isinstance(data.get("elements", []), list):
            raise RuntimeError(
                f"The public map service returned an unexpected response for {location}."
            )
        return data.get("elements", [])

    raise RuntimeError(f"Could not retrieve public listings for {location}.")


def fetch_businesses(city_name, categories):
    locations = normalize_search_locations(city_name)
    elements_by_id = {}
    for location_index, location in enumerate(locations):
        if location_index:
            time.sleep(1)
        query = build_overpass_query(location, categories)
        for item in request_location_listings(location, query):
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["_search_location"] = location
            key = (item.get("type"), item.get("id"))
            if key not in elements_by_id:
                elements_by_id[key] = item
    return list(elements_by_id.values())


def build_lead_record(item):
    tags = item.get("tags", {})
    company_name = normalize_name(tags.get("name", ""))
    if not company_name:
        return None

    email, phone = parse_contact_info(tags)
    industry = detect_industry(tags)
    company_category = detect_company_category(tags, industry, company_name)
    website = (
        tags.get("contact:website")
        or tags.get("website")
        or tags.get("url")
        or ""
    ).strip()
    if website and not website.startswith(("http://", "https://")):
        website = f"https://{website}"
    location = (
        tags.get("addr:city")
        or tags.get("addr:town")
        or tags.get("addr:municipality")
        or tags.get("addr:district")
        or ""
    )
    state = tags.get("addr:state") or ""
    search_location = item.get("_search_location", "")
    if not state:
        state = STATE_ALIASES.get(search_location.casefold(), "")
    if not location and search_location and not state:
        location = search_location

    lead = {
        "Date Added": date.today().isoformat(),
        "Company Name": company_name,
        "Company Category": company_category,
        "Industry": str(industry).title(),
        "City": location,
        "State": state,
        "Contact Person": "",
        "Job Title": "",
        "Email": email,
        "Phone": phone,
        "Website": website,
        "Service Interested": "",
        "Event Date": "",
        "Guest Count": "",
        "Lead Source": "OpenStreetMap",
        "Source URL": (
            f"https://www.openstreetmap.org/{item['type']}/{item['id']}"
            if item.get("type") and item.get("id")
            else ""
        ),
        "Lead Status": "New",
        "Data Completeness": "",
        "Recommended Next Action": "",
        "Estimated Value (₹)": "",
        "Last Contacted": "",
        "Next Follow-up": "",
        "Notes": "Public map listing; verify details before contacting",
    }
    completeness, next_action = assess_data_completeness(lead)
    lead["Data Completeness"] = completeness
    lead["Recommended Next Action"] = next_action
    return lead


def assess_data_completeness(lead):
    score = sum((
        bool(lead.get("Source URL")),
        bool(lead.get("Website")),
        bool(lead.get("Email") or lead.get("Phone")),
        bool(lead.get("City") or lead.get("State")),
    ))
    if not lead.get("Source URL"):
        next_action = "Find and verify the original public listing"
    elif not lead.get("Website"):
        next_action = "Research the official website and verify the business"
    elif not lead.get("Email") and not lead.get("Phone"):
        next_action = "Research an authorized public business contact"
    else:
        next_action = "Verify business fit, contact details, and permission before outreach"
    return f"{score}/4", next_action


def export_csv(leads, file_path):
    destination = Path(file_path)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8-sig",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            writer = csv.DictWriter(file, fieldnames=LEAD_FIELDS)
            writer.writeheader()
            writer.writerows(leads)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def main():
    parser = argparse.ArgumentParser(description="White Petals Resort lead collector")
    parser.add_argument(
        "--city",
        default=DEFAULT_CITY,
        help="City, district, or state to search; separate multiple locations with commas",
    )
    parser.add_argument(
        "--output",
        default="corporate_leads.csv",
        help="CSV file path for the extracted leads",
    )
    parser.add_argument(
        "--category",
        action="append",
        dest="categories",
        default=None,
        help="Business category to search. Repeat as needed. Example: --category office --category industrial",
    )
    args = parser.parse_args()

    categories = args.categories or DEFAULT_CATEGORIES

    print("White Petals Resort - Corporate Lead Collector")
    print(f"Searching for public businesses in {args.city}...")

    try:
        elements = fetch_businesses(args.city, categories)
    except (RuntimeError, ValueError) as error:
        print(error)
        print("Please check your internet connection and try again.")
        return

    leads = []
    seen = set()

    for item in elements:
        lead = build_lead_record(item)
        if not lead:
            continue

        company_key = (
            lead["Company Name"].casefold(),
            (lead.get("City") or "").casefold(),
            (lead.get("State") or "").casefold(),
        )
        if company_key in seen:
            continue

        seen.add(company_key)
        leads.append(lead)

    if leads:
        try:
            export_csv(leads, args.output)
        except OSError as error:
            print(f"Could not write CSV output to {args.output}: {error}")
            return
        print(f"Done! Saved {len(leads)} businesses to {args.output}")
        print("Open this CSV in Excel or import it into Google Sheets.")
    else:
        print("No named businesses found in this search.")
        print("Try again later or use another permitted public directory.")


if __name__ == "__main__":
    main()
