"""
Tools package for Shift AI Gateway
Contains LangChain-compatible tools for document generation, data analysis,
visualization, and other utilities.

Installation:
pip install python-docx unstructured reportlab python-pptx pandas matplotlib openai textblob qrcode wordcloud pillow

GitHub Repositories:
- python-docx: https://github.com/python-openxml/python-docx
- Unstructured: https://github.com/Unstructured-IO/unstructured
- ReportLab: https://hg.reportlab.com/hg-public/reportlab/
- python-pptx: https://github.com/scanny/python-pptx
- Pandas: https://github.com/pandas-dev/pandas
- Matplotlib: https://github.com/matplotlib/matplotlib
- OpenAI: https://github.com/openai/openai-python
- TextBlob: https://github.com/sloria/TextBlob
- python-qrcode: https://github.com/lincolnloop/python-qrcode
- wordcloud: https://github.com/amueller/word_cloud
"""

from .document_tools import (
    DOCUMENT_TOOLS,
    create_word_document,
    create_brief_document,
    create_meeting_minutes,
)

from .extended_tools import (
    EXTENDED_TOOLS,
    generate_structured_document,
    generate_pdf_report,
    create_presentation,
    analyze_data_table,
    create_chart_visualization,
    generate_marketing_image,
    analyze_content_sentiment,
    generate_campaign_qr,
    generate_keyword_cloud,
)

# Combine all tools for easy import
ALL_TOOLS = DOCUMENT_TOOLS + EXTENDED_TOOLS

__all__ = [
    # Document tools
    "DOCUMENT_TOOLS",
    "create_word_document",
    "create_brief_document",
    "create_meeting_minutes",
    # Extended tools
    "EXTENDED_TOOLS",
    "generate_structured_document",
    "generate_pdf_report",
    "create_presentation",
    "analyze_data_table",
    "create_chart_visualization",
    "generate_marketing_image",
    "analyze_content_sentiment",
    "generate_campaign_qr",
    "generate_keyword_cloud",
    # Combined
    "ALL_TOOLS",
]