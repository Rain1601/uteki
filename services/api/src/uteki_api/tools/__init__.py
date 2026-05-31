from uteki_api.tools.base import Tool, ToolRegistry, ToolResult, ToolRiskLevel
from uteki_api.tools.financials import FinancialsTool
from uteki_api.tools.kline import KLineTool
from uteki_api.tools.market_quote import MarketQuoteTool
from uteki_api.tools.news_search import NewsSearchTool
from uteki_api.tools.report_analysis import ReportAnalysisTool
from uteki_api.tools.web_extract import WebExtractTool
from uteki_api.tools.web_search import WebSearchTool

default_registry = ToolRegistry()
default_registry.register(MarketQuoteTool())
default_registry.register(NewsSearchTool())
default_registry.register(KLineTool())
default_registry.register(FinancialsTool())
default_registry.register(ReportAnalysisTool())
default_registry.register(WebSearchTool())
default_registry.register(WebExtractTool())

__all__ = [
    "Tool",
    "ToolResult",
    "ToolRiskLevel",
    "ToolRegistry",
    "default_registry",
    "MarketQuoteTool",
    "NewsSearchTool",
    "KLineTool",
    "FinancialsTool",
    "ReportAnalysisTool",
    "WebSearchTool",
    "WebExtractTool",
]
