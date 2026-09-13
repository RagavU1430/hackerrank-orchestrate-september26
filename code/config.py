"""Centralized configuration and path management for Buy or Wait?

Paths are resolved relative to the repository root to ensure portability
across environments and operating systems.
"""

from pathlib import Path
from typing import Dict

# Repository root (parent directory of code/)
REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Dataset directory and files
DATASET_DIR: Path = REPO_ROOT / "dataset"
REQUESTS_FILE: Path = DATASET_DIR / "requests.csv"
SAMPLE_REQUESTS_FILE: Path = DATASET_DIR / "sample_requests.csv"
FINANCIAL_PROFILES_FILE: Path = DATASET_DIR / "financial_profiles.csv"
FINANCIAL_EVENTS_FILE: Path = DATASET_DIR / "financial_events.csv"
PAYMENT_OPTIONS_FILE: Path = DATASET_DIR / "request_payment_options.csv"
EXCHANGE_RATES_FILE: Path = DATASET_DIR / "exchange_rates.csv"
MESSAGES_FILE: Path = DATASET_DIR / "messages.csv"
IMAGES_FILE: Path = DATASET_DIR / "images.csv"
OUTPUT_TEMPLATE_FILE: Path = DATASET_DIR / "output.csv"
MEDIA_IMAGES_DIR: Path = DATASET_DIR / "media" / "images"

# Target root output file (required by hackathon contract)
ROOT_OUTPUT_FILE: Path = REPO_ROOT / "output.csv"

# Evaluation directory and reports
EVALUATION_DIR: Path = REPO_ROOT / "evaluation"
DATA_QUALITY_REPORT_FILE: Path = EVALUATION_DIR / "data_quality_report.md"
USAGE_REPORT_FILE: Path = EVALUATION_DIR / "usage_report.md"
FORECAST_REPORT_FILE: Path = EVALUATION_DIR / "forecast_report.md"
AFFORDABILITY_REPORT_FILE: Path = EVALUATION_DIR / "affordability_report.md"
SPENDING_REPORT_FILE: Path = EVALUATION_DIR / "spending_adjustment_report.md"
AGENT_REPORT_FILE: Path = EVALUATION_DIR / "agent_report.md"
FINAL_EVALUATION_REPORT_FILE: Path = EVALUATION_DIR / "final_evaluation_report.md"
JUDGE_SUMMARY_FILE: Path = EVALUATION_DIR / "judge_summary.md"


REQUIRED_DATASET_FILES: Dict[str, Path] = {
    "requests": REQUESTS_FILE,
    "sample_requests": SAMPLE_REQUESTS_FILE,
    "financial_profiles": FINANCIAL_PROFILES_FILE,
    "financial_events": FINANCIAL_EVENTS_FILE,
    "request_payment_options": PAYMENT_OPTIONS_FILE,
    "exchange_rates": EXCHANGE_RATES_FILE,
    "messages": MESSAGES_FILE,
    "images": IMAGES_FILE,
}


def check_dataset_files() -> None:
    """Verify that all required dataset files and directories exist.

    Raises:
        FileNotFoundError: If any required file or folder is missing.
    """
    if not DATASET_DIR.is_dir():
        raise FileNotFoundError(f"Required dataset directory missing: {DATASET_DIR}")

    for name, path in REQUIRED_DATASET_FILES.items():
        if not path.is_file():
            raise FileNotFoundError(f"Required dataset file '{name}' missing at: {path}")

    if not MEDIA_IMAGES_DIR.is_dir():
        raise FileNotFoundError(f"Media images directory missing at: {MEDIA_IMAGES_DIR}")
