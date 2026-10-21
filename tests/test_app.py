import io
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import Mock, patch

import app as webapp
from main import (
    CATEGORY_TAGS, DEFAULT_CATEGORIES, build_lead_record,
    build_overpass_query, export_csv, fetch_businesses,
    normalize_search_locations, request_location_listings,
)


class WhitePetalsAppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = webapp.DB_PATH
        self.original_backup_dir = webapp.BACKUP_DIR
        webapp.DB_PATH = Path(self.temp_dir.name) / "test.db"
        webapp.BACKUP_DIR = Path(self.temp_dir.name) / "backups"
        webapp.init_db()
        webapp.app.config.update(TESTING=True)
        webapp.app.secret_key = "test-secret-key"
        self.environment = patch.dict(os.environ, {"APP_PASSWORD": ""})
        self.environment.start()
        self.client = webapp.app.test_client()
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-csrf-token"

    def tearDown(self):
        self.environment.stop()
        webapp.DB_PATH = self.original_db_path
        webapp.BACKUP_DIR = self.original_backup_dir
        self.temp_dir.cleanup()

    def post(self, url, data=None, **kwargs):
        form = dict(data or {})
        form["csrf_token"] = "test-csrf-token"
        return self.client.post(url, data=form, **kwargs)

    def add_lead(self, **overrides):
        data = {
            "company_name": "Example Technologies",
            "industry": "Technology",
            "website": "https://example.com",
            "city": "Bengaluru",
            "sales_status": "Booking Confirmed",
            "estimated_value": "1000",
            "confirmed_revenue": "750.50",
        }
        data.update(overrides)
        response = self.post("/leads/new", data=data)
        self.assertEqual(response.status_code, 302)
        return 1

    def test_health_and_dashboard_routes(self):
        self.assertEqual(self.client.get("/health").json["status"], "ok")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Overview & leads", response.data)
        self.assertIn(b"Business development pipeline", response.data)
        self.assertIn(b'class="sidebar"', response.data)
        self.assertIn(b"AI agent studio", response.data)
        self.assertIn(b"LOCAL CRM", response.data)

    def test_sign_in_uses_responsive_workspace_shell(self):
        with patch.dict(os.environ, {"APP_PASSWORD": "local-test-password"}):
            response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"login-panel", response.data)
        self.assertIn(b"mobile-brand", response.data)
        self.assertIn(b"Setup & backups", response.data)
        self.assertNotIn(b"Sign out", response.data)

    def test_dashboard_summarizes_active_pipeline_and_research_work(self):
        self.add_lead(
            company_name="Qualified Prospect",
            sales_status="Qualified",
            estimated_value="500",
            confirmed_revenue="",
        )
        self.add_lead(
            company_name="Researching Prospect",
            sales_status="Researching",
            estimated_value="250",
            confirmed_revenue="",
        )
        self.add_lead(
            company_name="Closed Booking",
            sales_status="Booking Confirmed",
            estimated_value="300",
            confirmed_revenue="300",
        )
        self.add_lead(
            company_name="Lost Prospect",
            sales_status="Lost",
            estimated_value="900",
            confirmed_revenue="",
        )
        with webapp.db_transaction() as connection:
            connection.execute(
                "UPDATE companies SET research_status = 'Completed' "
                "WHERE company_name = 'Qualified Prospect'"
            )

        with webapp.app.test_request_context("/"):
            data = webapp.get_dashboard_data()
        self.assertEqual(data["open_pipeline_leads"], 2)
        self.assertEqual(data["open_pipeline_value"], 750)
        self.assertEqual(data["leads_to_research"], 1)
        stage_counts = {stage["name"]: stage["count"] for stage in data["pipeline_stages"]}
        self.assertEqual(stage_counts["Qualified"], 1)
        self.assertNotIn("Lost", stage_counts)

    def test_expanded_company_categories_and_legacy_categories(self):
        for category in (
            "technology", "company_office", "event_management",
            "corporate_travel", "consulting", "industrial", "bank",
            "insurance", "education", "professional_organization",
            "event_venue", "retail",
        ):
            self.assertIn(category, CATEGORY_TAGS)
        self.assertEqual(len(DEFAULT_CATEGORIES), len(set(DEFAULT_CATEGORIES)))
        query = build_overpass_query(
            "Bengaluru", ["technology", "startup", "office", "event_management"]
        )
        self.assertEqual(query.count('["office"="company"]'), 1)
        self.assertIn('["office"="it"]', query)
        self.assertIn('["office"="event_management"]', query)
        technology_lead = build_lead_record(
            {"tags": {"name": "Technology Co", "office": "it"}}
        )
        event_lead = build_lead_record(
            {"tags": {"name": "Event Co", "office": "event_management"}}
        )
        self.assertEqual(technology_lead["Company Category"], "Technology / IT")
        self.assertEqual(event_lead["Company Category"], "Event management")

        with patch.object(webapp, "fetch_businesses", return_value=[]) as fetch:
            response = self.post(
                "/collect",
                data={"city": "Bengaluru", "categories": "technology, event_management"},
            )
        self.assertEqual(response.status_code, 302)
        fetch.assert_called_once_with("Bengaluru", ["technology", "event_management"])

    def test_city_aliases_and_multiple_state_search_locations(self):
        self.assertEqual(
            normalize_search_locations(" Bangalore, Mysore; Karnataka "),
            ["Bengaluru", "Mysuru", "Karnataka"],
        )
        query = build_overpass_query(
            "Bangalore, Mysore, Karnataka", ["technology"]
        )
        self.assertIn('^(Bengaluru|Bangalore|Mysuru|Mysore|Karnataka)$', query)
        self.assertEqual(query.count('["office"="it"]'), 1)
        with self.assertRaises(ValueError):
            normalize_search_locations("Bengaluru," + ", ".join(f"Place {i}" for i in range(10)))
        self.assertEqual(normalize_search_locations("tamil nadu"), ["Tamil Nadu"])

        with patch.object(webapp, "fetch_businesses", return_value=[]) as fetch:
            response = self.post(
                "/collect",
                data={
                    "city": "Bangalore, Mysore, Karnataka",
                    "categories": "technology",
                },
            )
        self.assertEqual(response.status_code, 302)
        fetch.assert_called_once_with(
            "Bengaluru, Mysuru, Karnataka", ["technology"]
        )

    def test_search_location_fills_city_or_state_without_combined_fallback(self):
        city_record = build_lead_record({
            "_search_location": "Mysuru",
            "tags": {"name": "Mysuru Listing", "office": "it"},
        })
        state_record = build_lead_record({
            "_search_location": "Karnataka",
            "tags": {"name": "State Listing", "office": "it"},
        })
        self.assertEqual((city_record["City"], city_record["State"]), ("Mysuru", ""))
        self.assertEqual((state_record["City"], state_record["State"]), ("", "Karnataka"))

        self.assertEqual(
            webapp.save_leads_to_db([city_record, state_record], "Mysuru, Karnataka"),
            (2, 0),
        )
        with webapp.db_transaction() as connection:
            rows = connection.execute(
                "SELECT company_name, city, state FROM companies ORDER BY company_name"
            ).fetchall()
        self.assertEqual(
            [(row["company_name"], row["city"], row["state"]) for row in rows],
            [("Mysuru Listing", "Mysuru", ""), ("State Listing", "", "Karnataka")],
        )

    def test_fetch_businesses_queries_each_location_and_deduplicates_map_elements(self):
        first = Mock()
        first.raise_for_status.return_value = None
        first.json.return_value = {
            "elements": [{"type": "node", "id": 1, "tags": {"name": "One"}}]
        }
        second = Mock()
        second.raise_for_status.return_value = None
        second.json.return_value = {
            "elements": [
                {"type": "node", "id": 1, "tags": {"name": "One"}},
                {"type": "node", "id": 2, "tags": {"name": "Two"}},
            ]
        }
        with patch("main.requests.post", side_effect=[first, second]) as post, \
                patch("main.time.sleep"):
            results = fetch_businesses("Bengaluru, Mysuru", ["technology"])
        self.assertEqual([item["id"] for item in results], [1, 2])
        self.assertEqual([item["_search_location"] for item in results], ["Bengaluru", "Mysuru"])
        self.assertEqual(post.call_count, 2)

    def test_collector_retries_busy_service_and_adds_review_guidance(self):
        busy_response = Mock(status_code=503, headers={"Retry-After": "0"})
        success_response = Mock(status_code=200, headers={})
        success_response.json.return_value = {"elements": [{"id": 1}]}
        with patch("main.requests.post", side_effect=[busy_response, success_response]) as post, \
                patch("main.time.sleep"):
            records = request_location_listings("Mysuru", "query")
        self.assertEqual(records, [{"id": 1}])
        self.assertEqual(post.call_count, 2)

        lead = build_lead_record({
            "type": "node",
            "id": 42,
            "_search_location": "Mysuru",
            "tags": {"name": "Research Needed Co", "office": "company"},
        })
        self.assertEqual(lead["Data Completeness"], "2/4")
        self.assertIn("official website", lead["Recommended Next Action"])

    def test_collector_rejects_invalid_service_json(self):
        response = Mock(status_code=200, headers={})
        response.json.side_effect = ValueError("invalid JSON")
        with patch("main.requests.post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "invalid JSON for Mysuru"):
                request_location_listings("Mysuru", "query")

    def test_collector_csv_export_is_atomic_on_write_error(self):
        output = Path(self.temp_dir.name) / "leads.csv"
        output.write_text("existing file", encoding="utf-8")
        with self.assertRaises(ValueError):
            export_csv([{"unexpected": "column"}], output)
        self.assertEqual(output.read_text(encoding="utf-8"), "existing file")
        self.assertEqual(list(Path(self.temp_dir.name).glob(".leads.csv.*.tmp")), [])

    def test_find_new_leads_adds_then_matches_without_overwriting_crm(self):
        listing = {
            "Company Name": "New Prospect",
            "Industry": "IT",
            "Website": "",
            "Phone": "",
            "Email": "",
            "Lead Source": "OpenStreetMap",
            "Source URL": "https://www.openstreetmap.org/node/123",
        }
        self.assertEqual(webapp.save_leads_to_db([listing], "Bengaluru"), (1, 0))
        with webapp.db_transaction() as connection:
            connection.execute(
                """
                UPDATE companies
                SET phone = 'Verified phone', sales_status = 'Qualified',
                    notes = 'Keep this manual note'
                WHERE company_name = 'New Prospect'
                """
            )
        enriched_listing = dict(listing, Phone="+91 1234567890", Website="example.com")
        self.assertEqual(
            webapp.save_leads_to_db([enriched_listing], "Bengaluru"),
            (0, 1),
        )
        with webapp.db_transaction() as connection:
            lead = connection.execute(
                "SELECT phone, website, sales_status, notes FROM companies "
                "WHERE company_name = 'New Prospect'"
            ).fetchone()
        self.assertEqual(lead["phone"], "Verified phone")
        self.assertEqual(lead["website"], "example.com")
        self.assertEqual(lead["sales_status"], "Qualified")
        self.assertEqual(lead["notes"], "Keep this manual note")

    def test_lead_creation_edit_and_status(self):
        self.add_lead()
        with webapp.db_transaction() as connection:
            row = connection.execute(
                "SELECT company_name, company_category, sales_status, estimated_value, confirmed_revenue "
                "FROM companies"
            ).fetchone()
        self.assertEqual(row["company_name"], "Example Technologies")
        self.assertEqual(row["company_category"], "Technology / IT")
        self.assertEqual(row["sales_status"], "Booking Confirmed")
        self.assertEqual(row["estimated_value"], 1000)
        self.assertEqual(row["confirmed_revenue"], 750.5)
        response = self.client.get("/leads/1")
        self.assertEqual(response.status_code, 200)
        response = self.post(
            "/leads/1/edit",
            data={
                "company_name": "Example Technologies",
                "industry": "Technology",
                "city": "Bengaluru",
                "website": "example.com",
                "sales_status": "Qualified",
                "estimated_value": "1200",
                "confirmed_revenue": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        with webapp.db_transaction() as connection:
            status = connection.execute(
                "SELECT sales_status FROM companies WHERE id = 1"
            ).fetchone()["sales_status"]
        self.assertEqual(status, "Qualified")

    def test_contact_permission_defaults_unknown_and_requires_evidence(self):
        self.add_lead(sales_status="New Lead", estimated_value="", confirmed_revenue="")
        with webapp.db_transaction() as connection:
            lead = connection.execute(
                "SELECT contact_permission, permission_source, permission_recorded_at "
                "FROM companies WHERE id = 1"
            ).fetchone()
        self.assertEqual(
            tuple(lead),
            ("Not recorded", "", ""),
        )
        response = self.post("/leads/new", data={
            "company_name": "Permission Missing Source",
            "sales_status": "New Lead",
            "contact_permission": "Permission recorded",
            "permission_recorded_at": "2026-10-21",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"permission source and date", response.data)

    def test_opt_out_forces_do_not_contact_until_renewed_permission_is_recorded(self):
        self.add_lead(
            company_name="Opted Out Prospect",
            sales_status="Do Not Contact",
            contact_permission="Opted out",
            estimated_value="",
            confirmed_revenue="",
        )
        with webapp.db_transaction() as connection:
            lead = dict(connection.execute(
                "SELECT * FROM companies WHERE id = 1"
            ).fetchone())
        self.assertEqual(lead["contact_permission"], "Opted out")
        values = {field: lead.get(field) or "" for field in webapp.LEAD_FIELDS}
        values["sales_status"] = "Qualified"
        response = self.post("/leads/1/edit", data=values)
        self.assertEqual(response.status_code, 302)
        with webapp.db_transaction() as connection:
            stage = connection.execute(
                "SELECT sales_status FROM companies WHERE id = 1"
            ).fetchone()["sales_status"]
        self.assertEqual(stage, "Do Not Contact")

        values.update({
            "contact_permission": "Permission recorded",
            "permission_source": "Renewed written request",
            "permission_recorded_at": "2026-10-21",
            "sales_status": "Qualified",
        })
        response = self.post("/leads/1/edit", data=values)
        self.assertEqual(response.status_code, 302)
        with webapp.db_transaction() as connection:
            lead = connection.execute(
                "SELECT sales_status, contact_permission, permission_source "
                "FROM companies WHERE id = 1"
            ).fetchone()
        self.assertEqual(lead["sales_status"], "Qualified")
        self.assertEqual(lead["contact_permission"], "Permission recorded")
        self.assertEqual(lead["permission_source"], "Renewed written request")

    def test_do_not_contact_stage_does_not_falsely_claim_opt_out(self):
        self.add_lead(
            company_name="Restricted Prospect",
            sales_status="Do Not Contact",
            estimated_value="",
            confirmed_revenue="",
        )
        with webapp.db_transaction() as connection:
            permission = connection.execute(
                "SELECT contact_permission FROM companies WHERE id = 1"
            ).fetchone()["contact_permission"]
        self.assertEqual(permission, "Not recorded")

    def test_existing_other_category_is_backfilled_from_industry(self):
        with webapp.db_transaction() as connection:
            connection.execute(
                """
                INSERT INTO companies (company_name, company_category, industry, city)
                VALUES ('Legacy Software Co', 'Other', 'IT', 'Bengaluru')
                """
            )
        webapp.init_db()
        with webapp.db_transaction() as connection:
            category = connection.execute(
                "SELECT company_category FROM companies WHERE company_name = 'Legacy Software Co'"
            ).fetchone()["company_category"]
        self.assertEqual(category, "Technology / IT")

    def test_company_category_filter_and_pipeline(self):
        self.add_lead(
            company_name="Event Agency",
            company_category="Event management",
            industry="Event services",
        )
        self.add_lead(
            company_name="Technology Firm",
            company_category="Technology / IT",
            industry="Software",
        )
        dashboard = self.client.get(
            "/?company_category=Event+management"
        )
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Event Agency", dashboard.data)
        self.assertNotIn(b"Technology Firm", dashboard.data)
        pipeline = self.client.get("/bookings?company_category=Technology+%2F+IT")
        self.assertEqual(pipeline.status_code, 200)
        self.assertIn(b"Technology Firm", pipeline.data)
        self.assertNotIn(b"Event Agency", pipeline.data)
        self.assertIn(b"All company categories", pipeline.data)

    def test_pipeline_filters_company_status_city_and_category(self):
        self.add_lead(
            company_name="Mysuru Event Agency",
            company_category="Event management",
            industry="Event services",
            city="Mysuru",
            email="contact@event.example",
            sales_status="Qualified",
        )
        self.add_lead(
            company_name="Bengaluru IT Firm",
            company_category="Technology / IT",
            industry="IT",
            city="Bengaluru",
            phone="+91 9876543210",
            sales_status="New Lead",
        )
        response = self.client.get(
            "/bookings?q=event.example&status=Qualified&city=Mysuru"
            "&company_category=Event+management"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Mysuru Event Agency", response.data)
        self.assertNotIn(b"Bengaluru IT Firm", response.data)
        self.assertIn(b"1 matching records", response.data)

    def test_pipeline_can_filter_by_state(self):
        self.add_lead(
            company_name="Karnataka Company",
            city="Mysuru",
            state="Karnataka",
        )
        self.add_lead(
            company_name="Tamil Nadu Company",
            city="Chennai",
            state="Tamil Nadu",
        )
        response = self.client.get("/bookings?city=Karnataka")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Karnataka Company", response.data)
        self.assertNotIn(b"Tamil Nadu Company", response.data)

    def test_duplicate_import_and_date_validation(self):
        rows = [
            {"Company Name": "Same Co", "City": "Bengaluru", "Lead Status": "New Lead"},
            {"Company Name": "Same Co", "City": "Bengaluru", "Lead Status": "New Lead"},
            {"Company Name": "Same Co", "City": "Mysuru", "Lead Status": "New Lead"},
        ]
        added, duplicates = webapp.import_lead_rows(rows)
        self.assertEqual((added, duplicates), (2, 1))
        with self.assertRaises(ValueError):
            webapp.import_lead_rows(
                [{"Company Name": "Bad date", "Next Follow-up": "tomorrow"}]
            )
        with webapp.db_transaction() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
                2,
            )

    def test_csv_and_xlsx_import_export(self):
        csv_content = (
            b"Company Name,Company Category,Industry,City,State,Lead Status\n"
            b"CSV Company,Technology / IT,IT,Mysuru,Karnataka,New Lead\n"
        )
        response = self.post(
            "/import",
            data={"file": (io.BytesIO(csv_content), "leads.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active.append(["Company Name", "Industry", "Location", "Source URL"])
        workbook.active.append(["Excel Company", "Consulting", "Bengaluru", "https://example.com/source"])
        xlsx_content = io.BytesIO()
        workbook.save(xlsx_content)
        response = self.post(
            "/import",
            data={"file": (io.BytesIO(xlsx_content.getvalue()), "leads.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with webapp.db_transaction() as connection:
            csv_lead = connection.execute(
                "SELECT city, state FROM companies WHERE company_name = 'CSV Company'"
            ).fetchone()
            imported = connection.execute(
                "SELECT source_url, state FROM companies WHERE company_name = 'Excel Company'"
            ).fetchone()
        self.assertEqual((csv_lead["city"], csv_lead["state"]), ("Mysuru", "Karnataka"))
        self.assertEqual(imported["source_url"], "https://example.com/source")
        self.assertEqual(imported["state"], "")
        csv_export = self.client.get("/export.csv")
        self.assertEqual(csv_export.status_code, 200)
        self.assertIn(b"Company Category", csv_export.data)
        self.assertIn(b"State", csv_export.data)
        self.assertIn(b"Contact Permission", csv_export.data)
        self.assertIn(b"Karnataka", csv_export.data)
        xlsx = self.client.get("/export.xlsx")
        self.assertEqual(xlsx.status_code, 200)
        self.assertIn(
            "spreadsheetml",
            xlsx.headers["Content-Type"],
        )

    def test_permission_fields_import_and_export(self):
        added, skipped = webapp.import_lead_rows([{
            "Company Name": "Permission Import Prospect",
            "City": "Mysuru",
            "Contact Permission": "Permission recorded",
            "Permission Source": "Opt-in web form",
            "Permission Recorded Date": "2026-10-21",
        }])
        self.assertEqual((added, skipped), (1, 0))
        with webapp.db_transaction() as connection:
            row = connection.execute(
                "SELECT contact_permission, permission_source, permission_recorded_at "
                "FROM companies WHERE company_name = 'Permission Import Prospect'"
            ).fetchone()
        self.assertEqual(
            tuple(row),
            ("Permission recorded", "Opt-in web form", "2026-10-21"),
        )
        self.assertIn(b"Opt-in web form", self.client.get("/export.csv").data)

    def test_database_backup_and_confirmed_restore(self):
        self.add_lead(
            company_name="Backup Snapshot Lead",
            sales_status="New Lead",
            estimated_value="",
            confirmed_revenue="",
        )
        created = self.post("/backups/create")
        self.assertEqual(created.status_code, 200)
        self.assertIn("attachment", created.headers["Content-Disposition"])
        created.close()
        backup = webapp.list_database_backups()[0]
        self.assertGreater(backup["size"], 0)

        self.add_lead(
            company_name="Later Lead",
            sales_status="New Lead",
            estimated_value="",
            confirmed_revenue="",
        )
        refused = self.post("/backups/restore", data={
            "backup_name": backup["name"],
            "confirmation": "wrong",
        })
        self.assertEqual(refused.status_code, 302)
        with webapp.db_transaction() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM companies WHERE company_name = 'Later Lead'"
                ).fetchone()[0],
                1,
            )

        restored = self.post(
            "/backups/restore",
            data={"backup_name": backup["name"], "confirmation": "RESTORE"},
            follow_redirects=True,
        )
        self.assertEqual(restored.status_code, 200)
        self.assertIn(b"Database restored", restored.data)
        with webapp.db_transaction() as connection:
            names = {
                row[0] for row in connection.execute(
                    "SELECT company_name FROM companies"
                )
            }
        self.assertIn("Backup Snapshot Lead", names)
        self.assertNotIn("Later Lead", names)
        self.assertGreaterEqual(len(webapp.list_database_backups()), 2)

    def test_daily_backup_is_logged(self):
        backup = webapp.run_daily_backup()
        self.assertTrue(backup.is_file())
        with webapp.db_transaction() as connection:
            entry = connection.execute(
                "SELECT status, summary FROM job_runs "
                "WHERE job_name = 'Daily database backup'"
            ).fetchone()
        self.assertEqual(entry["status"], "Completed")
        self.assertIn(backup.name, entry["summary"])

    def test_invalid_database_restore_preserves_current_crm(self):
        self.add_lead(
            company_name="Keep Current Lead",
            sales_status="New Lead",
            estimated_value="",
            confirmed_revenue="",
        )
        webapp.BACKUP_DIR.mkdir(parents=True)
        invalid_backup = webapp.BACKUP_DIR / "white_petals_backup_invalid.db"
        invalid_backup.write_bytes(b"not a SQLite database")
        response = self.post(
            "/backups/restore",
            data={
                "backup_name": invalid_backup.name,
                "confirmation": "RESTORE",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"current CRM database was preserved", response.data)
        with webapp.db_transaction() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM companies "
                    "WHERE company_name = 'Keep Current Lead'"
                ).fetchone()[0],
                1,
            )

    def test_followup_draft_and_report_metrics(self):
        self.add_lead()
        self.add_lead(
            company_name="Follow-up Example",
            sales_status="New Lead",
            estimated_value="",
            confirmed_revenue="",
            next_follow_up=webapp.local_today(),
        )
        metrics = webapp.collect_daily_metrics()
        self.assertEqual(metrics["confirmed_bookings"], 1)
        self.assertEqual(metrics["confirmed_booking_value"], 750.5)
        self.assertEqual(metrics["follow_ups_due"], 1)
        with webapp.db_transaction() as connection:
            company_id = connection.execute(
                "SELECT id FROM companies WHERE company_name = 'Example Technologies'"
            ).fetchone()["id"]
        response = self.post(
            "/sales",
            data={"company_id": str(company_id), "channel": "Email"},
        )
        self.assertEqual(response.status_code, 302)
        with webapp.db_transaction() as connection:
            draft = connection.execute("SELECT body, status FROM drafts").fetchone()
            sent_count = connection.execute(
                "SELECT COUNT(*) FROM communication_log WHERE direction = 'Sent'"
            ).fetchone()[0]
        self.assertEqual(draft["status"], "Draft")
        self.assertIn("confirm package details", draft["body"])
        self.assertEqual(sent_count, 0)
        report_response = self.post("/reports/run")
        self.assertEqual(report_response.status_code, 302)
        self.assertEqual(self.client.get("/reports").status_code, 200)

    def test_gemini_draft_uses_private_key_header_and_limited_lead_context(self):
        self.add_lead(
            sales_status="Qualified",
            contact_person="Private Contact",
            email="private@example.com",
            phone="5550100",
            notes="Do not send this CRM note",
        )
        with webapp.db_transaction() as connection:
            lead = connection.execute("SELECT * FROM companies WHERE id = 1").fetchone()
        response = Mock(status_code=200)
        response.json.return_value = {
            "candidates": [{
                "content": {"parts": [{
                    "text": '{"subject":"Team event enquiry","body":"Would you like to discuss your requirements?"}'
                }]}
            }]
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key", "GEMINI_MODEL": "gemini-3.8-flash"}), \
                patch("app.requests.post", return_value=response) as post:
            subject, body = webapp.create_gemini_sales_draft(lead, "Email", "Team outing")
        self.assertEqual(subject, "Team event enquiry")
        self.assertIn("discuss", body)
        request_args = post.call_args
        self.assertNotIn("local-test-key", request_args.args[0])
        self.assertEqual(request_args.kwargs["headers"]["x-goog-api-key"], "local-test-key")
        prompt = request_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("Example Technologies", prompt)
        self.assertNotIn("private@example.com", prompt)
        self.assertNotIn("Private Contact", prompt)
        self.assertNotIn("Do not send this CRM note", prompt)
        self.assertEqual(request_args.kwargs["timeout"], (5, 30))

    def test_gemini_draft_errors_are_visible_and_no_fallback_is_saved(self):
        self.add_lead(sales_status="Qualified")
        with webapp.db_transaction() as connection:
            lead = connection.execute("SELECT * FROM companies WHERE id = 1").fetchone()
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                webapp.create_gemini_sales_draft(lead, "Email", "")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key"}), \
                patch("app.requests.post") as post:
            post.return_value.status_code = 429
            response = self.post(
                "/sales",
                data={
                    "company_id": "1",
                    "channel": "Email",
                    "draft_mode": "gemini",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"rate-limiting requests", response.data)
        with webapp.db_transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM drafts").fetchone()[0], 0)

    def test_gemini_unavailable_model_has_specific_guidance(self):
        self.add_lead(sales_status="Qualified")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key", "GEMINI_MODEL": "gemini-2.5-flash"}), \
                patch("app.requests.post") as post:
            post.return_value.status_code = 404
            with self.assertRaisesRegex(RuntimeError, "GEMINI_MODEL=gemini-3.8-flash"):
                with webapp.db_transaction() as connection:
                    lead = connection.execute("SELECT * FROM companies WHERE id = 1").fetchone()
                webapp.create_gemini_sales_draft(lead, "Email", "")

    def test_gemini_overload_error_explains_retry_and_does_not_save_draft(self):
        self.add_lead(sales_status="Qualified")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key", "GEMINI_MODEL": "gemini-3.8-flash"}), \
                patch("app.requests.post") as post:
            post.return_value.status_code = 503
            response = self.post(
                "/sales",
                data={
                    "company_id": "1",
                    "channel": "Email",
                    "draft_mode": "gemini",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"temporarily unavailable", response.data)
        self.assertIn(b"wait and try again", response.data)
        with webapp.db_transaction() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM drafts").fetchone()[0], 0)

    def test_ai_assistant_creates_daily_plan_without_sending_private_data(self):
        self.add_lead(
            company_name="Daily Plan Prospect",
            sales_status="Qualified",
            email="private@example.com",
            contact_person="Private Contact",
            notes="Private CRM note",
        )
        result = {
            "summary": "Review one qualified prospect today.",
            "actions": [{
                "lead_id": 1,
                "priority": "High",
                "action": "Verify the official website.",
                "reason": "Research is incomplete.",
            }],
            "watchouts": ["Verify all facts before outreach."],
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key"}), \
                patch.object(webapp, "request_gemini_json", return_value=result) as generate:
            response = self.post("/ai", data={"mode": "daily_plan"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Suggested plan for today", response.data)
        self.assertIn(b"Verify the official website.", response.data)
        prompt = generate.call_args.args[0]
        self.assertIn("Daily Plan Prospect", prompt)
        self.assertNotIn("private@example.com", prompt)
        self.assertNotIn("Private Contact", prompt)
        self.assertNotIn("Private CRM note", prompt)

    def test_event_proposal_uses_limited_company_context_and_renders_review_sections(self):
        self.add_lead(
            company_name="Milestone Prospect",
            sales_status="Qualified",
            company_category="Technology / IT",
            contact_person="Private Contact",
            email="private@example.com",
            notes="Private CRM note",
            website="https://private.example",
        )
        result = {
            "concept_title": "The Next Chapter",
            "concept_summary": "A suggested milestone experience centered on team connection.",
            "experience_ideas": ["A collaborative story wall, subject to resort approval."],
            "draft_agenda": [
                {"time": "09:00", "segment": "Welcome and shared goals"},
                {"time": "10:00", "segment": "Team activity concept (confirm facilities)"},
            ],
            "planning_checklist": ["Confirm event format and accessibility needs."],
            "discovery_questions": ["What should attendees remember afterward?"],
            "confirm_with_resort": ["Confirm venue, availability, capacity, and current rates."],
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key"}), \
                patch.object(
                    webapp, "load_resort_info",
                    return_value={
                        "name": "White Petals Resort",
                        "package_prices": "",
                        "team_building_activities": "",
                        "official_contact_details": "",
                    },
                ), \
                patch.object(webapp, "request_gemini_json", return_value=result) as generate:
            response = self.post("/ai", data={
                "mode": "event_proposal",
                "proposal_lead_id": "1",
                "event_type": "Milestone retreat",
                "event_date": "2026-12-10",
                "guest_count": "30",
                "event_goal": "Celebrate a team milestone and reconnect.",
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Event Experience Studio", response.data)
        self.assertIn(b"The Next Chapter", response.data)
        self.assertIn(b"Draft run of show", response.data)
        self.assertIn(b"Questions for the prospect", response.data)
        self.assertIn(b"Confirm with the resort", response.data)
        prompt = generate.call_args.args[0]
        self.assertIn("Milestone Prospect", prompt)
        self.assertIn("Celebrate a team milestone and reconnect.", prompt)
        self.assertIn('"guest_count": 30', prompt)
        self.assertNotIn("private@example.com", prompt)
        self.assertNotIn("Private Contact", prompt)
        self.assertNotIn("Private CRM note", prompt)
        self.assertNotIn("private.example", prompt)
        self.assertIn("Never invent or estimate prices", prompt)
        self.assertEqual(generate.call_args.kwargs["max_output_tokens"], 1800)

    def test_event_proposal_rejects_closed_leads_without_ai_request(self):
        self.add_lead(
            company_name="Closed Prospect",
            sales_status="Do Not Contact",
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key"}), \
                patch.object(webapp, "request_gemini_json") as generate:
            response = self.post("/ai", data={
                "mode": "event_proposal",
                "proposal_lead_id": "1",
                "event_type": "Team retreat",
                "event_goal": "Celebrate the team.",
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Choose an active lead", response.data)
        generate.assert_not_called()

    def test_ai_lead_prioritization_ignores_unknown_lead_ids(self):
        self.add_lead(company_name="Known Prospect", sales_status="Qualified")
        result = {
            "recommendations": [
                {"lead_id": 1, "priority": "High", "reason": "Qualified stage.", "next_action": "Research."},
                {"lead_id": 999, "priority": "High", "reason": "Unknown.", "next_action": "Unknown."},
            ]
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key"}), \
                patch.object(webapp, "request_gemini_json", return_value=result) as generate:
            response = self.post("/ai", data={"mode": "prioritize_leads"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Known Prospect", response.data)
        self.assertNotIn(b"Unknown.", response.data)
        with webapp.db_transaction() as connection:
            score = connection.execute(
                "SELECT lead_score FROM companies WHERE id = 1"
            ).fetchone()["lead_score"]
        self.assertGreaterEqual(score, 0)
        self.assertIn("Rank the supplied active leads", generate.call_args.args[0])
        self.assertIn("Known Prospect", generate.call_args.args[0])

    def test_ai_assistant_lead_strategy_rejects_closed_leads(self):
        self.add_lead(sales_status="Do Not Contact")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key"}), \
                patch.object(webapp, "request_gemini_json") as generate:
            response = self.post(
                "/ai",
                data={"mode": "lead_strategy", "lead_id": "1"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Choose an active lead", response.data)
        generate.assert_not_called()

    def test_ai_workspace_lists_specialists_and_creates_custom_agent(self):
        response = self.client.get("/ai")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"AI Agent Control Room", response.data)
        self.assertIn(b"Lead Research Planner", response.data)
        self.assertIn(b"AI Call Coach", response.data)
        self.assertIn(b"fictional scenario", response.data)
        call_coach = next(
            agent for agent in webapp.get_business_agents()
            if agent["name"] == "AI Call Coach"
        )
        self.assertIn("cannot dial", call_coach["instructions"])
        self.assertIn("fictional practice simulation", call_coach["instructions"])
        self.assertIn(b"Work log", response.data)

        response = self.post("/agents/create", data={
            "name": "Event Checklist Agent",
            "specialty": "Event opportunity checklists",
            "instructions": "Prepare questions for human review.",
        })
        self.assertEqual(response.status_code, 302)
        agents = webapp.get_business_agents()
        self.assertTrue(any(agent["name"] == "Event Checklist Agent" for agent in agents))

    def test_agent_task_saves_reviewable_result_without_private_lead_fields(self):
        self.add_lead(
            company_name="Agent Prospect",
            sales_status="Qualified",
            email="private@example.com",
            contact_person="Private Contact",
            notes="Private CRM note",
        )
        agent = next(
            agent for agent in webapp.get_business_agents()
            if agent["name"] == "Lead Prioritization Analyst"
        )
        result = {
            "summary": "Review this qualified lead.",
            "deliverables": ["Prepare a call checklist."],
            "next_steps": ["Verify official public information."],
            "risks": ["No buyer intent is established."],
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key"}), \
                patch.object(webapp, "request_gemini_json", return_value=result) as generate:
            response = self.post(
                f"/agents/{agent['id']}/tasks",
                data={"objective": "Prepare a review checklist."},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Prepare a call checklist.", response.data)
        self.assertIn(b"COMPLETED", response.data)
        prompt = generate.call_args.args[0]
        self.assertIn("Agent Prospect", prompt)
        self.assertNotIn("private@example.com", prompt)
        self.assertNotIn("Private Contact", prompt)
        self.assertNotIn("Private CRM note", prompt)
        with webapp.db_transaction() as connection:
            task = connection.execute(
                "SELECT status, result_json FROM bd_agent_tasks"
            ).fetchone()
        self.assertEqual(task["status"], "Completed")
        self.assertIn("Prepare a call checklist.", task["result_json"])

    def test_agent_task_without_gemini_is_recorded_as_failed(self):
        agent = webapp.get_business_agents()[0]
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            response = self.post(
                f"/agents/{agent['id']}/tasks",
                data={"objective": "Prepare today's plan."},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Gemini is not configured", response.data)
        with webapp.db_transaction() as connection:
            task = connection.execute(
                "SELECT status, error FROM bd_agent_tasks"
            ).fetchone()
        self.assertEqual(task["status"], "Failed")
        self.assertIn("not completed", task["error"])

    def test_call_coach_prepares_consent_gated_lead_brief_without_contact_details(self):
        self.add_lead(
            company_name="Consented Call Prospect",
            sales_status="Qualified",
            contact_permission="Permission recorded",
            permission_source="Opt-in request form",
            permission_recorded_at="2026-10-21",
            email="private@example.com",
            contact_person="Private Contact",
            phone="5550101",
            notes="Private CRM note",
        )
        agent = next(
            agent for agent in webapp.get_business_agents()
            if agent["name"] == "AI Call Coach"
        )
        result = {
            "summary": "A short call guide is ready.",
            "deliverables": ["Ask permission to continue before discussing business."],
            "next_steps": ["Verify event requirements with the caller."],
            "risks": ["Do not quote unverified rates."],
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key"}), \
                patch.object(webapp, "request_gemini_json", return_value=result) as generate:
            response = self.post(
                f"/agents/{agent['id']}/tasks",
                data={
                    "lead_id": "1",
                    "objective": "Prepare a respectful first-call guide.",
                },
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"short call guide is ready", response.data)
        prompt = generate.call_args.args[0]
        self.assertIn("Consented Call Prospect", prompt)
        self.assertNotIn("private@example.com", prompt)
        self.assertNotIn("Private Contact", prompt)
        self.assertNotIn("5550101", prompt)
        self.assertNotIn("Private CRM note", prompt)

    def test_call_coach_blocks_real_lead_without_permission_and_allows_fictional_practice(self):
        self.add_lead(
            company_name="Unverified Call Prospect",
            sales_status="Qualified",
            email="private@example.com",
        )
        agent = next(
            agent for agent in webapp.get_business_agents()
            if agent["name"] == "AI Call Coach"
        )
        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key"}), \
                patch.object(webapp, "request_gemini_json") as generate:
            blocked = self.post(
                f"/agents/{agent['id']}/tasks",
                data={
                    "lead_id": "1",
                    "objective": "Prepare a call guide.",
                },
                follow_redirects=True,
            )
        self.assertIn(b"requires recorded permission", blocked.data)
        generate.assert_not_called()
        with webapp.db_transaction() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM bd_agent_tasks").fetchone()[0],
                0,
            )

        result = {
            "summary": "Fictional practice ready.",
            "deliverables": ["A fictional role-play scenario."],
            "next_steps": ["Practice the opening aloud."],
            "risks": ["This is not a real call."],
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "local-test-key"}), \
                patch.object(webapp, "request_gemini_json", return_value=result) as generate:
            practiced = self.post(
                f"/agents/{agent['id']}/tasks",
                data={
                    "objective": "Create a fictional role-play for practice.",
                },
                follow_redirects=True,
            )
        self.assertEqual(practiced.status_code, 200)
        self.assertIn(b"Fictional practice ready", practiced.data)
        prompt = generate.call_args.args[0]
        self.assertIn("Limited active CRM lead data: []", prompt)
        self.assertNotIn("Unverified Call Prospect", prompt)
        self.assertNotIn("private@example.com", prompt)

    def test_followup_reschedule(self):
        self.add_lead(sales_status="New Lead", estimated_value="", confirmed_revenue="")
        response = self.post(
            "/leads/1/follow-up",
            data={"action": "reschedule", "next_follow_up": "2099-01-01"},
        )
        self.assertEqual(response.status_code, 302)
        with webapp.db_transaction() as connection:
            due = connection.execute(
                "SELECT next_follow_up FROM companies WHERE id=1"
            ).fetchone()["next_follow_up"]
        self.assertEqual(due, "2099-01-01")

    def test_public_url_rejects_loopback_and_csrf_is_required(self):
        with self.assertRaises(ValueError):
            webapp.validate_public_url("http://127.0.0.1/")
        response = self.client.post("/reports/run")
        self.assertEqual(response.status_code, 400)

    def test_research_respects_robots_disallow(self):
        response = Mock(status_code=200)
        response.iter_content.return_value = [b"User-agent: *\nDisallow: /private\n"]
        with patch.object(webapp, "validate_public_url", return_value=urlsplit("https://public.example/private/page")), patch(
            "app.requests.get", return_value=response
        ):
            with self.assertRaisesRegex(RuntimeError, "robots.txt"):
                webapp.check_robots_policy("https://public.example/private/page")
        response.close.assert_called_once()

    def test_integrations_show_demo_state(self):
        with patch.dict(os.environ, {"APP_PASSWORD": "", "GEMINI_API_KEY": ""}):
            response = self.client.get("/integrations")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"not connected", response.data.lower())
        self.assertIn(b"Contact permission tracking", response.data)
        self.assertIn(b"Create &amp; download database backup", response.data)
        self.assertIn(b"02:15", response.data)

    def test_optional_password_login_and_logout(self):
        client = webapp.app.test_client()
        with patch.dict(os.environ, {"APP_PASSWORD": "local-test-password"}):
            self.assertEqual(client.get("/").status_code, 302)
            login_page = client.get("/login")
            self.assertEqual(login_page.status_code, 200)
            with client.session_transaction() as session:
                token = session["csrf_token"]
            response = client.post(
                "/login",
                data={"csrf_token": token, "password": "local-test-password"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(client.get("/").status_code, 200)
            with client.session_transaction() as session:
                token = session["csrf_token"]
            response = client.post("/logout", data={"csrf_token": token})
            self.assertEqual(response.status_code, 302)


if __name__ == "__main__":
    unittest.main()
