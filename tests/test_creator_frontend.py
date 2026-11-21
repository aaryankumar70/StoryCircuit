"""Frontend UI Verification and Integration Tests for CurioLoop Creator Studio.

Tests Section 9 ("Creator Studio") 6-step guided Story-to-Series Studio:
- Step 1: Ingestion (Upload, Paste, Reddit)
- Step 2: Intelligent Story Understanding (Narrative Arc, Characters, Turning Points)
- Step 3: Production-Plan Recommendations (Durations, Pacing Trade-offs)
- Step 4: Episode Breakdown & Three.js Storyboard Review (Invalidation, Approval Gate)
- Step 5: Scheduling Planner (Schedule A/B/C, IST Calendar Table)
- Step 6: Production Queue & Lifecycle (Status, Controls, Automatic Studio Protection)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from curiosity_engine.dashboard.app import app

TEMPLATE_PATH = Path("curiosity_engine/dashboard/templates/index.html")


def test_index_html_structure_and_section9_presence():
    """Verify index.html contains Section 9 and the 6-step Story-to-Series Studio elements."""
    assert TEMPLATE_PATH.exists(), "index.html template must exist."
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    # Verify Section 9 container
    assert '<div id="section-creator" class="studio-section">' in html
    assert 'Creator Studio — Story-to-Series Narrative Engine' in html

    # Verify Stepper Bar & 6 Steps
    assert 'id="csStepperBar"' in html
    for step_num in range(1, 7):
        assert f'id="csStepTab-{step_num}"' in html, f"Step tab {step_num} missing"
        assert f'id="csStepPanel-{step_num}"' in html, f"Step panel {step_num} missing"

    # Step 1 Ingestion: 3 tabs
    assert 'id="csIngestTab-upload"' in html
    assert 'id="csIngestTab-paste"' in html
    assert 'id="csIngestTab-reddit"' in html
    assert 'id="csDropzone"' in html
    assert 'id="csStoryText"' in html
    assert 'id="csRedditUrl"' in html
    assert 'id="csRedditErrorBanner"' in html
    assert 'id="csMetricDuration"' in html
    assert 'id="csMetricWords"' in html

    # Step 2 Understanding: Arc decomposition & continuity
    assert 'id="csArcExposition"' in html
    assert 'id="csArcTension"' in html
    assert 'id="csArcClimax"' in html
    assert 'id="csArcResolution"' in html
    assert 'id="csEntitiesCloud"' in html
    assert 'id="csTurningPointsCloud"' in html
    assert 'id="csContinuityNotes"' in html

    # Step 3 Plan Recommendations
    assert 'id="csPlanCardsContainer"' in html
    assert 'id="csCustomDurationDrawer"' in html

    # Step 4 Storyboards & Three.js Review
    assert 'id="csEpisodesListContainer"' in html
    assert 'id="csGlobalApprovalBadge"' in html
    assert 'Approve All Episodes' in html

    # Step 5 Scheduling Planner (IST)
    assert 'id="csSchedRadioA"' in html
    assert 'id="csSchedRadioB"' in html
    assert 'id="csSchedRadioC"' in html
    assert 'id="csStartDateInput"' in html
    assert 'id="csCalendarPreviewTableBody"' in html
    assert 'id="csCompletionDateText"' in html

    # Step 6 Production Queue & Lifecycle
    assert 'id="csLifecycleStatusBadge"' in html
    assert 'id="csLifecyclePauseBtn"' in html
    assert 'id="csLifecycleCancelBtn"' in html
    assert 'Automatic Studio Protection Active' in html
    assert 'csQueueEpisodesList' in html
    assert 'id="creatorContainer"' in html


def test_creator_studio_js_contracts():
    """Verify all required JavaScript orchestration functions exist in the template."""
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    required_functions = [
        "switchCsIngestMode",
        "updateCsMetrics",
        "handleCsFileSelect",
        "fetchRedditStory",
        "goToCsStep",
        "runStep1AnalyzeStory",
        "renderStep2Analysis",
        "runStep2RecommendPlans",
        "renderStep3Plans",
        "selectCsPlan",
        "handleCsCustomDurationChange",
        "runStep3ConfirmPlan",
        "renderStep4Episodes",
        "initCsThreeScene",
        "saveCsEpisodeEdit",
        "toggleCsStoryboardApproval",
        "approveAllCsStoryboards",
        "updateCsGlobalApprovalBadge",
        "initStep5Scheduling",
        "selectCsSchedulePreset",
        "updateCsSchedulePreview",
        "runStep5CommitSchedule",
        "renderStep6Lifecycle",
        "refreshCsQueueStatus",
        "toggleCsLifecyclePause",
        "cancelCsSeries",
        "loadCreatorData",
        "loadSeriesIntoStudio",
        "resetCreatorStudio",
    ]

    for fn_name in required_functions:
        assert f"function {fn_name}" in html or f"async function {fn_name}" in html, f"Missing function {fn_name}"


def test_dashboard_index_route_serves_html():
    """Verify that GET / returns the dashboard HTML with injected auth secret."""
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    content = response.text
    assert "STUDIO_AUTH_KEY" in content
    assert "Creator Studio — Story-to-Series Narrative Engine" in content


def test_playwright_e2e_render_and_stepper_flow():
    """Verify full end-to-end rendering and 6-step walkthrough in a headless browser."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright not installed in environment.")

    edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if not Path(edge_path).exists():
        pytest.skip("Microsoft Edge not found on standard path.")

    html_uri = TEMPLATE_PATH.resolve().as_uri()

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=edge_path, headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})

        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: console_errors.append(str(err)))
        page.on("dialog", lambda dialog: dialog.accept())

        page.goto(html_uri)
        page.wait_for_timeout(600)

        # Switch to creator studio
        page.evaluate("switchSection('creator')")
        page.wait_for_timeout(300)

        # Verify step 1 active
        step1_active = page.evaluate("() => document.getElementById('csStepTab-1').classList.contains('active')")
        assert step1_active is True

        # Input manuscript and verify metrics
        story_text = "Arthur tuned the radio receiver to 104.5 MHz. The signal whispered his name. It was midnight."
        page.evaluate(f"""() => {{
            document.getElementById('csTitle').value = 'Test Signal Series';
            document.getElementById('csAuthor').value = 'u/TestAuthor';
            document.getElementById('csStoryText').value = {json.dumps(story_text)};
            updateCsMetrics();
        }}""")

        words = page.evaluate("() => document.getElementById('csMetricWords').innerText")
        assert int(words) > 10

        # Run Step 1 -> Step 2
        page.evaluate("async () => await runStep1AnalyzeStory()")
        page.wait_for_timeout(400)
        step2_active = page.evaluate("() => document.getElementById('csStepTab-2').classList.contains('active')")
        assert step2_active is True

        # Run Step 2 -> Step 3
        page.evaluate("async () => await runStep2RecommendPlans()")
        page.wait_for_timeout(400)
        step3_active = page.evaluate("() => document.getElementById('csStepTab-3').classList.contains('active')")
        assert step3_active is True

        # Run Step 3 -> Step 4
        page.evaluate("async () => await runStep3ConfirmPlan()")
        page.wait_for_timeout(600)
        step4_active = page.evaluate("() => document.getElementById('csStepTab-4').classList.contains('active')")
        assert step4_active is True

        # Step 4 -> Step 5
        page.evaluate("goToCsStep(5)")
        page.wait_for_timeout(300)
        step5_active = page.evaluate("() => document.getElementById('csStepTab-5').classList.contains('active')")
        assert step5_active is True

        # Step 5 -> Step 6
        page.evaluate("async () => await runStep5CommitSchedule()")
        page.wait_for_timeout(400)
        step6_active = page.evaluate("() => document.getElementById('csStepTab-6').classList.contains('active')")
        assert step6_active is True

        browser.close()
        # Verify zero unhandled JavaScript syntax or runtime errors (ignoring file:/// origin fetch CORS warnings)
        js_errors = [
            e for e in console_errors
            if "CORS" not in e and "net::ERR_FAILED" not in e and "Failed to fetch" not in e and "file:///" not in e
        ]
        assert len(js_errors) == 0, f"Encountered JS runtime errors: {js_errors}"
