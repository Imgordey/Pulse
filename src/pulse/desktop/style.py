"""Small palette-aware stylesheet; native controls retain keyboard and focus behavior."""

from PySide6.QtGui import QPalette


def stylesheet(palette: QPalette) -> str:
    dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
    background, card, text, muted, border, accent = (
        ("#171a20", "#22262e", "#eff3f8", "#a8b0bf", "#343b48", "#75d3b3")
        if dark
        else ("#f5f7fa", "#ffffff", "#172334", "#59677a", "#dce3ec", "#14745c")
    )
    return f"""
    QMainWindow, QDialog {{ background: {background}; }}
    QLabel {{ color: {text}; font-size: 13px; }}
    QLabel[role=title] {{ font-size: 28px; font-weight: 650; }}
    QLabel[role=metric] {{ font-size: 30px; font-weight: 600; }}
    QLabel[role=muted] {{ color: {muted}; font-size: 12px; }}
    QLabel[role=warning] {{ color: {accent}; }}
    QFrame[role=card] {{ background: {card}; border: 1px solid {border}; border-radius: 12px; }}
    QPushButton[role=navigation] {{ background: transparent; border: 0;
        padding: 14px 20px; text-align: left; color: {text}; font-size: 14px; }}
    QPushButton[role=navigation]:checked {{ background: {accent}; color: {background}; }}
    QTextEdit {{ background: {card}; color: {text}; border: 1px solid {border};
        border-radius: 10px; padding: 14px; font-size: 14px; }}
    QPushButton {{ padding: 8px 14px; }}
    QPushButton[role=primary] {{ background: {accent}; color: {background};
        border: 0; border-radius: 7px; font-weight: 600; }}
    QPushButton[role=primary]:disabled {{ background: {border}; color: {muted}; }}
    QTableWidget {{ border: 1px solid {border}; border-radius: 6px; }}
    """
