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
    annotations={
        "course_id": "The ID of the Udacity course to retrieve price history for."
    }
)
def get_price_history(course_id: int):
    pass


@mcp.resource(
    "udacity://alerts/latest",
    name="Get Latest Price Alerts",
    description="Get the latest price alerts for Udacity courses"
)
def get_latest_alerts():
    pass


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
