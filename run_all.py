"""
Run the whole pipeline
======================

    python run_all.py

Runs steps 1 through 7 in order and stops at the first failure. Takes about a
minute. Everything is seeded, so you get the same numbers I did.

At the end, open outputs/dashboard.html in a browser.
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")

STEPS = [
    ("01_generate_data.py", "Generate the raw fleet and repair data"),
    ("02_data_quality.py", "Validate, clean, and quarantine bad rows"),
    ("03_build_database.py", "Load SQLite, build views, benchmark indexes"),
    ("04_fleet_health_report.py", "Fleet health analysis and charts"),
    ("05_repair_demand_forecast.py", "Forecast repair demand"),
    ("06_shop_assignment_optimizer.py", "Optimize shop assignment"),
    ("07_build_dashboard.py", "Assemble the dashboard"),
]


def main():
    print("=" * 72)
    print("RailPulse: railcar fleet maintenance analytics")
    print("=" * 72)
    t_start = time.time()

    for i, (script, description) in enumerate(STEPS, 1):
        print(f"\n[{i}/{len(STEPS)}] {description}")
        print("-" * 72)
        t0 = time.time()
        result = subprocess.run([sys.executable, script], cwd=SRC)
        if result.returncode != 0:
            print(f"\nFAILED at {script}. Stopping.")
            sys.exit(result.returncode)
        print(f"   done in {time.time() - t0:.1f}s")

    print("\n" + "=" * 72)
    print(f"Pipeline finished in {time.time() - t_start:.1f}s")
    print("=" * 72)
    print("\nOpen this next:")
    print(f"   {os.path.join(HERE, 'outputs', 'dashboard.html')}")
    print("\nOther outputs:")
    print("   data/railpulse.db              query it directly with SQL")
    print("   outputs/*.csv                  every table behind the dashboard")
    print("   outputs/charts/*.png           every chart")


if __name__ == "__main__":
    main()
