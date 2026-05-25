from pathlib import Path

import pandas as pd
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="udacity-price-mcp",
    instructions="A MCP server to monitor and share Udacity Prices",
    json_response=True
)
MAIN_DF = pd.read_csv(
    "data/udacity_prices.csv"
)


@mcp.resource(
    "udacity://history/{course_id}",
    name="Get Price History",
    description="Get the price history for a specific Udacity course",
    mime_type="application/json",
    annotations={
        "course_id": "The ID of the Udacity course to retrieve price history for."
    }
)
def get_price_history(course_id: int):
    """Return price history for a specific course."""
    courses = MAIN_DF['name'].unique().tolist()
    course = courses[course_id] if 0 <= course_id < len(courses) else None
    if not course:
        return f"Course with ID {course_id} not found."
    course_history = MAIN_DF[
        MAIN_DF['name'] == course
    ].sort_values(by='timestamp_utc')
    history = []
    for _, row in course_history.iterrows():
        history.append({
            "timestamp_utc": row["timestamp_utc"],
            "price": row["price"],
            "currency": row["currency"]
        })
    return {"course": course, "history": history}


@mcp.resource(
    "udacity://alerts/latest",
    name="Get Latest Price Alerts",
    mime_type="application/json",
    description="Get the latest price alerts for Udacity courses"
)
def get_latest_alerts() -> str | dict:
    """Return the latest price alerts for Udacity courses."""
    alert_csv = "data/udacity_alerts.csv"

    if not Path(alert_csv).exists():
        return "No alerts found."
    alerts_df = pd.read_csv(alert_csv)
    if alerts_df.empty:
        return "No alerts found."
    alerts = []
    for _, row in alerts_df.iterrows():
        alert_info = {
            "timestamp_utc": row["timestamp_utc"],
            "name": row["name"],
            "url": row["url"],
            "currency": row["currency"],
            "price": row["price"],
            "historical_median": row["historical_median"],
            "historical_mean": row["historical_mean"],
            "historical_min": row["historical_min"],
            "historical_count": row["historical_count"],
            "reason": row["reason"]
        }
        alerts.append(alert_info)
    return alerts


@mcp.resource(
    "udacity://courses",
    name="Get All Courses",
    description="Get a list of all Udacity courses with their corresponding URL",
    mime_type="application/json"
)
def get_all_courses():
    """Return list of courses with their corresponding URL."""
    courses = MAIN_DF['name'].unique()
    result = []
    for course in courses:
        url = MAIN_DF.loc[MAIN_DF['name'] == course, 'url']
        url = url.iloc[0] if not url.empty else None
        course_info = {
            "name": course,
            "url": url
        }
        result.append(course_info)
    return result


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http"
    )
    # get_all_courses()
