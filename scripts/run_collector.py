"""Run the batch graph with configuration checks and a GitHub run summary."""
import json
import os
from pathlib import Path


def main():
    required = ("GEMINI_API_KEY", "TAVILY_API_KEY", "GOOGLE_SERVICE_ACCOUNT_JSON", "SHEET_ID")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("Missing configuration: " + ", ".join(missing))

    from agent import graph
    from tools.sheets import _get_services, SHEET_TAB

    # Verify access even when collection finds no new events.
    sheets, _ = _get_services()
    if sheets is None:
        raise RuntimeError("Google Sheets credentials could not be loaded")
    sheets.spreadsheets().get(spreadsheetId=os.environ["SHEET_ID"], fields="spreadsheetId").execute()
    result = graph.invoke({"mode": "weekly", "messages": ["GitHub Actions scheduled collection"]})
    errors = result.get("errors") or []
    sheet_result = result.get("sheets_result") or {}
    if sheet_result.get("error"):
        errors.append(sheet_result["error"])
    stats = result.get("stats") or {}
    categories = {}
    for event in result.get("extracted_events", []):
        category = event.get("category", "unknown")
        categories[category] = categories.get(category, 0) + 1
    summary = {"stats": stats, "collected_by_category": categories, "errors": errors}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(
            "## Collection result\n\n```json\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n```\n",
            encoding="utf-8",
        )
    if errors:
        raise RuntimeError("Collection reported errors; see run summary")


if __name__ == "__main__":
    main()
