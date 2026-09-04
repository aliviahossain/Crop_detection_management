"""End-to-end API tests over the whole core loop.

These run with no trained weights present, which is the honest default state of
a fresh clone -- so they also pin the degraded-mode behaviour: the API must
still respond, and must escalate rather than guess.
"""
from __future__ import annotations

PUNE = {"latitude": 18.5204, "longitude": 73.8567}


def test_root_and_health(client):
    assert client.get("/").status_code == 200
    health = client.get("/meta/health").json()
    assert "components" in health
    # No weights and no weather key in tests, so both are genuinely degraded.
    assert health["status"] == "degraded"
    assert set(health["degraded"]) == {"detection_model_missing", "weather_api_key_missing"}


def test_health_separates_real_faults_from_design_states(client):
    """Template-only advisories and an untrained XGBoost layer are the specified
    design, not faults. Reporting them as degradation implies the system is
    broken when it is behaving exactly as documented."""
    health = client.get("/meta/health").json()
    assert "llm_translation_unused" in health["by_design"]
    assert "secondary_risk_layer_inactive" in health["by_design"]
    assert "llm_translation_unused" not in health["degraded"]
    assert "secondary_risk_layer_inactive" not in health["degraded"]
    # Every entry has to tell the reader what to do about it.
    for entry in health["degraded_detail"] + health["by_design_detail"]:
        assert entry["summary"] and entry["remedy"]


def test_classes_endpoint_reports_the_three_potato_classes(client):
    data = client.get("/meta/classes").json()
    assert data["crop"] == "potato"
    keys = [c["key"] for c in data["classes"]]
    assert keys == ["potato_early_blight", "potato_late_blight", "potato_healthy"]


def test_all_supported_languages_are_fully_translated(client):
    """A partially translated language silently falls back to English mid-advisory,
    which reads as broken to the farmer. Every offered language must be complete."""
    data = client.get("/meta/languages").json()
    assert set(data["supported"]) >= {"en", "mr", "hi", "bn"}
    for lang in data["supported"]:
        assert data["coverage"][lang]["coverage"] == 1.0, (
            f"{lang} is only {data['coverage'][lang]['coverage']:.0%} translated"
        )


def test_bengali_advisory_is_in_bengali(client):
    adv = client.post(
        "/advisory", json={"class_key": "potato_late_blight", "confidence": 0.9, "language": "bn"}
    ).json()["advisory"]
    assert adv["language"] == "bn"
    for text in [adv["summary"], adv["safety"]["items"][0], adv["follow_up"]["text"]]:
        assert any("ঀ" <= ch <= "৿" for ch in text), f"not Bengali: {text}"
    # Doses stay in Latin script and are never translated.
    assert any("Mancozeb" in o["product"] for o in adv["chemical"]["options"])


def test_bengali_class_and_pest_names(client):
    data = client.get("/meta/classes").json()
    for cls in data["classes"]:
        assert "bn" in cls["names"], f"{cls['key']} has no Bengali name"
        assert any("ঀ" <= ch <= "৿" for ch in cls["names"]["bn"])


class TestDetect:
    def test_upload_creates_a_case_and_an_advisory(self, client, sample_image):
        with sample_image.open("rb") as fh:
            resp = client.post(
                "/detect",
                files={"image": ("leaf.jpg", fh, "image/jpeg")},
                data={
                    **{k: str(v) for k, v in PUNE.items()},
                    "crop": "potato",
                    "variety": "Kufri Jyoti",
                    "crop_stage": "tuber_bulking",
                    "soil_condition": "poorly_drained",
                    "district": "Pune",
                    "village": "Manchar",
                    "language": "mr",
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["case_id"] > 0
        assert body["language"] == "mr"
        assert body["triage"]["escalate"] is True  # no weights -> must escalate
        assert body["advisory"]["summary"]
        assert body["follow_up_id"] is not None
        assert body["risk"]["overall_level"] in {"low", "medium", "high"}

    def test_marathi_advisory_is_actually_in_marathi(self, client, sample_image):
        with sample_image.open("rb") as fh:
            body = client.post(
                "/detect",
                files={"image": ("leaf.jpg", fh, "image/jpeg")},
                data={"language": "mr", "district": "Nashik"},
            ).json()
        text = body["advisory"]["safety"]["items"][0]
        assert any("ऀ" <= ch <= "ॿ" for ch in text), text

    def test_rejects_a_non_image_upload(self, client, tmp_path):
        bad = tmp_path / "notes.txt"
        bad.write_text("not an image")
        with bad.open("rb") as fh:
            resp = client.post("/detect", files={"image": ("notes.txt", fh, "text/plain")})
        assert resp.status_code == 415

    def test_rejects_a_corrupt_image(self, client, tmp_path):
        bad = tmp_path / "broken.jpg"
        bad.write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
        with bad.open("rb") as fh:
            resp = client.post("/detect", files={"image": ("broken.jpg", fh, "image/jpeg")})
        assert resp.status_code == 400


class TestLiveScanner:
    """Endpoints backing the real-time camera scanner."""

    def test_frame_inference_creates_no_case(self, client, sample_image):
        """A live camera sends several frames a second. If each one created a
        case, a minute of scanning would produce thousands of junk records."""
        before = client.get("/dashboard/summary", params={"days": 1}).json()["cases"]["total"]
        with sample_image.open("rb") as fh:
            resp = client.post("/detect/frame", files={"image": ("f.jpg", fh, "image/jpeg")})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "top_class" in body and "detections" in body
        # No advisory, no triage, no follow-up on this path.
        assert "advisory" not in body
        after = client.get("/dashboard/summary", params={"days": 1}).json()["cases"]["total"]
        assert after == before

    def test_frame_does_not_retain_the_image(self, client, sample_image):
        """Frames are throughput, not evidence — keeping them fills the disk."""
        from app.config import settings

        before = len(list(settings.upload_dir.rglob("*.jpg")))
        for _ in range(3):
            with sample_image.open("rb") as fh:
                client.post("/detect/frame", files={"image": ("f.jpg", fh, "image/jpeg")})
        assert len(list(settings.upload_dir.rglob("*.jpg"))) == before

    def test_frame_rejects_a_non_image(self, client, tmp_path):
        bad = tmp_path / "x.txt"
        bad.write_text("nope")
        with bad.open("rb") as fh:
            assert client.post(
                "/detect/frame", files={"image": ("x.txt", fh, "text/plain")}
            ).status_code == 415

    def test_thresholds_endpoint_matches_the_server_decoder(self, client):
        """The in-browser decoder reads these. If they drift from what the
        server applies, the same leaf gets two different verdicts."""
        data = client.get("/detect/thresholds").json()
        status = client.get("/detect/status").json()
        assert data["classes"] == status["classes"]
        assert data["per_class"] == status["conf_thresholds"]
        assert data["default"] == status["conf_threshold_default"]
        assert 0 < data["iou_threshold"] < 1

    def test_model_download_404s_with_guidance_when_untrained(self, client):
        resp = client.get("/detect/model")
        assert resp.status_code == 404
        assert "ml/weights" in resp.json()["detail"]


class TestRisk:
    def test_forecast_without_an_image(self, client):
        resp = client.post(
            "/risk",
            json={
                **PUNE,
                "crop": "potato",
                "crop_stage": "tuber_bulking",
                "variety": "Kufri Jyoti",
                "district": "Pune",
                "language": "mr",
                "save_case": True,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        a = body["assessment"]
        assert a["overall_level"] in {"low", "medium", "high"}
        assert {t["key"] for t in a["threats"]} >= {
            "potato_late_blight",
            "potato_early_blight",
            "potato_tuber_moth",
        }
        assert a["weather"]["synthetic"] is True  # no API key in tests
        assert body["case_id"] is not None

    def test_every_threat_carries_its_model_evidence(self, client):
        a = client.post("/risk", json={**PUNE, "include_advisory": False}).json()["assessment"]
        late = next(t for t in a["threats"] if t["key"] == "potato_late_blight")
        names = {m["name"] for m in late["models"]}
        assert names == {"smith_period", "beaumont_period"}
        assert all(m["explanation"] for m in late["models"])

    def test_risk_is_deterministic_for_a_location(self, client):
        one = client.post("/risk", json={**PUNE, "include_advisory": False}).json()
        two = client.post("/risk", json={**PUNE, "include_advisory": False}).json()
        assert one["assessment"]["overall_score"] == two["assessment"]["overall_score"]

    def test_weather_audit_endpoint(self, client):
        data = client.get("/risk/weather", params={**PUNE, "past_days": 5}).json()
        assert len(data["daily"]) >= 5
        assert data["hourly_count"] > 100

    def test_models_endpoint_documents_thresholds(self, client):
        data = client.get("/risk/models").json()
        smith = next(m for m in data["primary"]["models"] if m["name"] == "smith_period")
        assert smith["thresholds"]["rh_hours"] == 11
        assert data["secondary"]["active"] is False  # no historical data shipped


class TestCanopyAirflow:
    """EXPERIMENTAL canopy-airflow modifier -- it adjusts leaf-wetness hours and
    the deterministic fungal models are re-evaluated on the adjusted days.

    The make-or-break honesty rule is tested directly: a breeze may soften a
    warning before conditions are met, but must NEVER un-fire a rule that already
    fired on the observed humidity, and an absent/unknown reading is neutral.
    """

    def test_level_maps_to_a_wetness_hour_delta(self):
        from app.services.risk_engine import _airflow_wetness_delta

        assert _airflow_wetness_delta("still") > 0
        assert _airflow_wetness_delta("light") == 0
        assert _airflow_wetness_delta("breezy") < 0
        # Absent or unrecognised -> None, so the caller skips airflow entirely.
        for bad in (None, "", "gale", "hurricane"):
            assert _airflow_wetness_delta(bad) is None

    def test_adjustment_touches_only_forecast_days_with_existing_dew(self):
        from datetime import date, timedelta

        from app.services.risk_engine import _adjust_days_for_airflow
        from app.services.risk_models import DaySummary

        today = date(2026, 9, 4)

        def day(d, wet, wet_temp=18.0):
            return DaySummary(
                day=d, temp_min=12.0, temp_max=24.0, temp_mean=18.0, rh_mean=88.0,
                hours_rh_above_90=wet, hours_rh_above_75=wet + 4, wetness_hours=wet,
                wetness_mean_temp=wet_temp, rainfall_mm=0.0,
            )

        past = day(today - timedelta(days=2), 9)       # observed -> untouched
        dry_future = day(today + timedelta(days=1), 0, None)  # no dew -> untouched
        wet_future = day(today + timedelta(days=1), 9)  # today+ with dew -> adjusted

        out = _adjust_days_for_airflow([past, dry_future, wet_future], 2, today)
        assert out[0].wetness_hours == 9   # past unchanged
        assert out[1].wetness_hours == 0   # dry day not invented into wetness
        assert out[2].wetness_hours == 11  # forecast day with dew extended
        assert out[2].hours_rh_above_90 == 11  # Smith reads this field too

    def test_still_air_can_push_a_forecast_day_over_the_smith_threshold(self):
        from datetime import date, timedelta

        from app.services.risk_engine import _adjust_days_for_airflow
        from app.services import risk_models

        today = date(2026, 9, 4)

        def qualifying_but_short(offset):
            # Warm enough, and 10 wet hours -> one short of Smith's 11h line.
            d = today + timedelta(days=offset)
            return risk_models.DaySummary(
                day=d, temp_min=12.0, temp_max=22.0, temp_mean=17.0, rh_mean=92.0,
                hours_rh_above_90=10, hours_rh_above_75=14, wetness_hours=10,
                wetness_mean_temp=15.0, rainfall_mm=0.0,
            )

        days = [qualifying_but_short(0), qualifying_but_short(1)]
        assert risk_models.smith_period(days).triggered is False  # 10h < 11h
        adj = _adjust_days_for_airflow(days, 2, today)  # still air -> +2h -> 12h
        assert risk_models.smith_period(adj).triggered is True    # now a Smith Period

    def test_combine_lets_airflow_raise_but_never_weaken_a_fired_rule(self):
        from app.services.risk_engine import _combine_airflow

        # Still air (adjusted > raw): always allowed, even if a rule fired.
        assert _combine_airflow(0.5, 0.7, raw_triggered=True) == (0.7, False)
        # Breeze before a rule fires (adjusted < raw, not triggered): eased.
        assert _combine_airflow(0.5, 0.4, raw_triggered=False) == (0.4, False)
        # Breeze once a rule HAS fired: suppressed, raw score kept.
        assert _combine_airflow(0.8, 0.6, raw_triggered=True) == (0.8, True)

    def test_airflow_surfaces_as_an_experimental_driver_over_the_api(self, client):
        base = client.post("/risk", json={**PUNE, "include_advisory": False}).json()["assessment"]
        still = client.post(
            "/risk", json={**PUNE, "airflow_level": "still", "include_advisory": False}
        ).json()["assessment"]

        base_lb = next(t for t in base["threats"] if t["key"] == "potato_late_blight")
        still_lb = next(t for t in still["threats"] if t["key"] == "potato_late_blight")

        driver = next(d for d in still_lb["drivers"] if d["factor"] == "airflow_experimental")
        assert driver["experimental"] is True
        # Still air can only hold or raise fungal risk, never lower it.
        assert still_lb["score"] >= base_lb["score"]
        # And with no reading, no airflow driver is emitted at all.
        assert not any(d["factor"] == "airflow_experimental" for d in base_lb["drivers"])


class TestAdvisory:
    def test_late_blight_advisory_carries_doses_and_citations(self, client):
        body = client.post(
            "/advisory", json={"class_key": "potato_late_blight", "confidence": 0.93}
        ).json()
        adv = body["advisory"]
        assert adv["chemical"]["status"] == "recommended"
        products = [o["product"] for o in adv["chemical"]["options"]]
        assert any("Mancozeb" in p for p in products)
        assert adv["references"], "advisory must cite the knowledge base"
        assert adv["safety"]["items"]

    def test_both_protectant_and_curative_options_are_returned(self, client):
        """Dose tables are collected by structure, not by heading text.

        The KB splits late blight chemistry across a 'Protectant' and a
        'Curative / systemic' heading. Matching on section titles once dropped
        the curative half silently -- exactly the failure a farmer would never
        notice.
        """
        adv = client.post(
            "/advisory", json={"class_key": "potato_late_blight", "confidence": 0.9}
        ).json()["advisory"]
        products = " ".join(o["product"] for o in adv["chemical"]["options"])
        assert "Mancozeb" in products  # protectant table
        assert "Cymoxanil" in products  # curative table
        assert "Dimethomorph" in products

    def test_healthy_crop_is_told_not_to_spray(self, client):
        adv = client.post(
            "/advisory", json={"class_key": "potato_healthy", "confidence": 0.97}
        ).json()["advisory"]
        assert adv["chemical"]["status"] == "not_required"
        assert adv["chemical"]["options"] == []

    def test_low_confidence_withholds_the_dose_table(self, client):
        adv = client.post(
            "/advisory", json={"class_key": "potato_late_blight", "confidence": 0.2}
        ).json()["advisory"]
        assert adv["chemical"]["status"] == "withheld_pending_expert_confirmation"
        assert adv["referral"]["required"] is True

    def test_unknown_class_is_rejected(self, client):
        assert client.post("/advisory", json={"class_key": "tomato_mosaic"}).status_code == 422

    def test_knowledge_base_search(self, client):
        hits = client.get("/advisory/search", params={"q": "mancozeb dose late blight"}).json()
        assert hits["hits"]
        assert hits["hits"][0]["score"] > 0


class TestSensors:
    def test_ingest_and_summarise_trap_readings(self, client):
        payload = {
            "readings": [
                {
                    "device_id": f"trap-{i}",
                    "metric": "trap_count",
                    "value": 25 + i,
                    "district": "Pune",
                    **PUNE,
                }
                for i in range(3)
            ]
        }
        assert client.post("/sensors/batch", json=payload).json()["ingested"] == 3
        summary = client.get("/sensors/summary").json()
        assert summary["cells"]
        assert summary["cells"][0]["devices"] == 3

    def test_trap_pressure_raises_tuber_moth_risk(self, client):
        a = client.post("/risk", json={**PUNE, "include_advisory": False}).json()["assessment"]
        moth = next(t for t in a["threats"] if t["key"] == "potato_tuber_moth")
        assert any(d["factor"] == "pest_trap" for d in moth["drivers"])

    def test_degree_days_alone_never_reach_high_pest_risk(self, client):
        """Agronomic rule: you scout on degree-days, you act on trap counts.

        Aphids complete a generation in ~10 days of warm weather, so an
        uncapped degree-day score would report HIGH aphid risk all season and
        make the overall risk level meaningless.
        """
        a = client.post(
            "/risk", json={"latitude": 21.27, "longitude": 78.59, "include_advisory": False}
        ).json()["assessment"]
        aphid = next(t for t in a["threats"] if t["key"] == "aphid_vector")
        assert aphid["level"] != "high"
        assert any(d["factor"] == "degree_day_cap" for d in aphid["drivers"])

    def test_pest_threats_are_named_in_marathi(self, client):
        a = client.post("/risk", json={**PUNE, "include_advisory": False}).json()["assessment"]
        moth = next(t for t in a["threats"] if t["key"] == "potato_tuber_moth")
        # display defaults to English; the Marathi name comes through the advisory
        assert moth["display"] == "Potato tuber moth"
        adv = client.post(
            "/advisory", json={"class_key": "potato_late_blight", "language": "mr"}
        ).json()["advisory"]
        assert any("ऀ" <= ch <= "ॿ" for ch in adv["summary"])


class TestReviewAndFeedback:
    def test_queue_confirm_and_accuracy_stats(self, client, sample_image):
        with sample_image.open("rb") as fh:
            case_id = client.post(
                "/detect",
                files={"image": ("leaf.jpg", fh, "image/jpeg")},
                data={**{k: str(v) for k, v in PUNE.items()}, "district": "Satara"},
            ).json()["case_id"]

        queue = client.get("/review/queue").json()
        assert any(c["id"] == case_id for c in queue)

        decided = client.post(
            f"/review/{case_id}",
            json={
                "status": "corrected",
                "confirmed_class": "potato_late_blight",
                "reviewer": "TAO Satara",
                "notes": "White growth on leaf underside confirmed in the field.",
            },
        )
        assert decided.status_code == 200
        assert decided.json()["confirmed_class"] == "potato_late_blight"

        stats = client.get("/review/stats/accuracy").json()
        assert stats["reviewed"] >= 1
        assert stats["retraining_samples_pending_export"] >= 1

    def test_correcting_without_a_class_is_rejected(self, client):
        queue = client.get("/review/queue").json()
        if not queue:
            return
        resp = client.post(
            f"/review/{queue[0]['id']}", json={"status": "corrected", "reviewer": "x"}
        )
        assert resp.status_code == 422


class TestHotspots:
    def test_confirmed_cases_form_a_hotspot(self, client):
        data = client.get("/hotspots", params={"days": 30}).json()
        assert data["total_cells"] >= 1
        cell = data["cells"][0]
        assert cell["dominant_class"]
        assert cell["intensity"] in {"low", "moderate", "high", "severe"}

    def test_geojson_shape_is_valid(self, client):
        gj = client.get("/hotspots/geojson").json()
        assert gj["type"] == "FeatureCollection"
        if gj["features"]:
            geom = gj["features"][0]["geometry"]
            assert geom["type"] == "Polygon"
            assert len(geom["coordinates"][0]) == 5


class TestFollowUp:
    def test_a_failed_treatment_escalates_the_case(self, client, sample_image):
        with sample_image.open("rb") as fh:
            body = client.post(
                "/detect",
                files={"image": ("leaf.jpg", fh, "image/jpeg")},
                data={**{k: str(v) for k, v in PUNE.items()}, "phone": "9999900000"},
            ).json()
        follow_up_id = body["follow_up_id"]
        resp = client.patch(
            f"/followups/{follow_up_id}",
            json={"outcome": "worsened", "treatment_applied": "Mancozeb 75 WP 2.5 g/l"},
        )
        assert resp.status_code == 200
        case = client.get(f"/review/{body['case_id']}").json()
        assert case["escalate"] is True
        codes = {r["code"] for r in (case.get("escalation_reasons") or [])} if case.get(
            "escalation_reasons"
        ) else set()
        assert "followup_treatment_failed" in codes or case["escalate"]

    def test_outcome_stats(self, client):
        stats = client.get("/followups/stats").json()
        assert "counts" in stats


class TestDashboard:
    def test_summary_and_trend(self, client):
        summary = client.get("/dashboard/summary").json()
        assert summary["cases"]["total"] >= 1
        assert "by_class" in summary
        trend = client.get("/dashboard/trend", params={"days": 14}).json()
        assert len(trend["series"]) == 15

    def test_districts_listing(self, client):
        data = client.get("/dashboard/districts").json()
        assert any(d["district"] == "Pune" for d in data["districts"])
