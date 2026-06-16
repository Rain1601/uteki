from uteki_api.tools.base import Tool, ToolRegistry, ToolResult, ToolRiskLevel
from uteki_api.tools.company_intel import CompanyIntelTool
from uteki_api.tools.financials import FinancialsTool
from uteki_api.tools.kline import KLineTool
from uteki_api.tools.macro_fred import MacroFREDTool
from uteki_api.tools.macro_rates import MacroRatesTool
from uteki_api.tools.market_quote import MarketQuoteTool
from uteki_api.tools.news_search import NewsSearchTool
from uteki_api.tools.report_analysis import ReportAnalysisTool
from uteki_api.tools.sec_fundamentals import SECFundamentalsTool
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
default_registry.register(MacroFREDTool())
default_registry.register(MacroRatesTool())
default_registry.register(CompanyIntelTool())
default_registry.register(SECFundamentalsTool())

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
    "MacroFREDTool",
    "MacroRatesTool",
    "CompanyIntelTool",
    "SECFundamentalsTool",
]
