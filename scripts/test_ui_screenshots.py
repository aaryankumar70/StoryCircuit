import os
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

def run():
    html_file = Path('curiosity_engine/dashboard/templates/index.html').resolve()
    html_uri = html_file.as_uri()
    out_dir = Path('docs/screenshots')
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            headless=True
        )
        page = browser.new_page(viewport={'width': 1400, 'height': 1100})
        
        console_logs = []
        page.on('console', lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on('pageerror', lambda err: console_logs.append(f"[pageerror] {err}"))

        page.goto(html_uri)
        page.wait_for_timeout(800)

        # Switch to Section 9 (Creator Studio)
        page.evaluate("switchSection('creator')")
        page.wait_for_timeout(400)

        # Step 1: Input story
        sample_text = (
            "The abandoned frequency had been silent for thirty years, until tonight. "
            "At 03:14 AM, the analog needles spiked violently into the red. Static hissed through "
            "the vacuum tubes, forming the shape of human breath. Arthur leaned toward the receiver, "
            "his headphones trembling. 'Station 9, do you read?' a voice whispered from the depths "
            "of the dial. He had not keyed the transmitter in three decades. The voice was his own. "
            "He reached for the tape recorder, his fingers slick with cold sweat. Every syllable on the "
            "playback matched the sound of a broadcast recorded tomorrow morning."
        )

        page.evaluate(f"""() => {{
            document.getElementById('csTitle').value = 'The Whispering Signal at Station 9';
            document.getElementById('csAuthor').value = 'u/AnalogHorrorWriter';
            document.getElementById('csStoryText').value = {json.dumps(sample_text)};
            updateCsMetrics();
        }}""")
        page.wait_for_timeout(300)
        page.screenshot(path=str(out_dir / 'creator_step1_ingestion.png'))
        print('Captured Step 1 screenshot!')

        # Step 2: Trigger narrative analysis (await Promise)
        page.evaluate("async () => await runStep1AnalyzeStory()")
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_dir / 'creator_step2_analysis.png'))
        print('Captured Step 2 screenshot!')

        # Step 3: Recommend plans (await Promise)
        page.evaluate("async () => await runStep2RecommendPlans()")
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_dir / 'creator_step3_plans.png'))
        print('Captured Step 3 screenshot!')

        # Step 4: Confirm plan & breakdown (generates episodes & Three.js canvas)
        page.evaluate("async () => await runStep3ConfirmPlan()")
        page.wait_for_timeout(1000)
        page.screenshot(path=str(out_dir / 'creator_step4_storyboards.png'))
        print('Captured Step 4 screenshot!')

        # Step 5: Scheduling Planner
        page.evaluate("goToCsStep(5)")
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_dir / 'creator_step5_scheduling.png'))
        print('Captured Step 5 screenshot!')

        # Step 6: Production Queue & Lifecycle
        page.evaluate("async () => await runStep5CommitSchedule()")
        page.wait_for_timeout(600)
        page.screenshot(path=str(out_dir / 'creator_step6_queue.png'))
        print('Captured Step 6 screenshot!')

        browser.close()
        print('All 6 screenshots captured with proper async resolution!')

if __name__ == '__main__':
    run()
