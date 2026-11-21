"""
Centralized theme system.

Ported to match the *actual product UI* (the downloader/queue/history/
settings screens in frontend/src/index.css's `.card`, `.btn-primary`,
`.btn-secondary`, `.input-field` component classes and tailwind.config.js's
base/accent scales) rather than the marketing landing page, since that's
what a desktop rebuild of the tool itself should feel like:

  - base grays:  #0a0b0f / #111319 / #161821 / #1c1f2a / #272b3a  (base-950..700)
  - accent:      #8b93ff / #6c73f0 / #565dd6                      (accent-400/500/600)
  - body font:   Inter        (frontend/index.html, tailwind `sans`)
  - display font: Space Grotesk (landing hero/brand wordmark)

All colors live in one place (ACCENT_PRESETS + BASE) and the QSS is built
from them with str.format, so re-skinning the whole app is a one-line
change. Space Grotesk is bundled/used only for prominent display text
(page titles, sidebar brand, eyebrows) as a deliberate second "display"
typeface -- the same pairing the web app uses -- so the UI doesn't read
as a single flat system font.
"""
from __future__ import annotations

BASE = {
    "bg": "#0a0b0f",
    "bg_alt": "#111319",
    "panel": "#161821",
    "panel_alt": "#1c1f2a",
    "card": "#13151d",
    "card_alt": "#171a24",
    "border": "#272b3a",
    "border_soft": "#1c1f2a",
    "border_hair": "#20232f",
    "text": "#f4f6fb",
    "text_dim": "#9aa0b4",
    "text_faint": "#5f6478",
    "success": "#4ade80",
    "success_dim": "#1c3a2a",
    "danger": "#f87171",
    "danger_dim": "#3a1f22",
    "warning": "#facc15",
}

# accent / accent_hover / accent_dim / glow (used for button gradients,
# focus rings, and drop-shadow glows -- see ui/effects.py)
ACCENT_PRESETS = {
    "violet": {"accent": "#6c73f0", "accent_hover": "#8b93ff", "accent_dim": "#565dd6", "glow": "108,115,240"},
    "gold": {"accent": "#d7aa58", "accent_hover": "#e8c06e", "accent_dim": "#a9843f", "glow": "215,170,88"},
    "emerald": {"accent": "#34d399", "accent_hover": "#5fe6b3", "accent_dim": "#1f9d70", "glow": "52,211,153"},
}

FONT_BODY = "'Inter', 'Segoe UI', sans-serif"
FONT_DISPLAY = "'Space Grotesk', 'Inter', 'Segoe UI', sans-serif"


def palette(accent_name: str = "violet") -> dict:
    accent = ACCENT_PRESETS.get(accent_name, ACCENT_PRESETS["violet"])
    return {**BASE, **accent}


def build_qss(accent_name: str = "violet") -> str:
    c = palette(accent_name)
    return """
    * {{
        font-family: {font_body};
        outline: none;
    }}
    QWidget {{
        background-color: transparent;
        color: {text};
        font-size: 13px;
    }}
    QMainWindow, #RootWindow {{
        background: qradialgradient(cx:0.85, cy:-0.1, radius:1.1, fx:0.85, fy:-0.1,
            stop:0 rgba({glow},0.10), stop:0.35 rgba({glow},0.02), stop:1 {bg});
    }}

    /* --- Sidebar --- */
    #Sidebar {{
        background-color: {bg_alt};
        border-right: 1px solid {border_soft};
    }}
    #SidebarLogo {{
        padding: 24px 18px 16px 18px;
    }}
    #SidebarTitle {{
        color: {text};
        font-family: {font_display};
        font-size: 17px;
        font-weight: 700;
        letter-spacing: -0.02em;
    }}
    #SidebarSubtitle {{
        color: {text_faint};
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 1.6px;
    }}
    QLabel#NavSection {{
        color: {text_faint};
        font-family: {font_display};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1.5px;
        padding: 20px 18px 7px 18px;
    }}
    #SidebarFooter {{
        color: {text_faint};
        font-size: 10px;
        padding: 10px 18px 4px 18px;
        letter-spacing: 0.2px;
    }}
    QPushButton#NavButton {{
        text-align: left;
        padding: 12px 18px;
        margin: 2px 10px;
        border-radius: 8px;
        border: none;
        background-color: transparent;
        color: {text_dim};
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton#NavButton:hover {{
        background-color: {panel_alt};
        color: {text};
    }}
    QPushButton#NavButton:checked {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 rgba({glow},0.22), stop:1 rgba({glow},0.06));
        color: {text};
        font-weight: 700;
        border: 1px solid rgba({glow},0.35);
        border-left: 1px solid rgba({glow},0.35);
    }}
    QPushButton#NavButton[compact="true"] {{
        text-align: center;
        padding: 8px 2px;
        margin: 2px 9px;
        font-size: 20px;
        min-height: 44px;
    }}
    QWidget#NavIndicator {{
        background-color: {accent};
        border-radius: 2px;
    }}
    QFrame#DashboardHero {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 rgba({glow},0.20), stop:1 {card});
        border: 1px solid rgba({glow},0.34);
        border-radius: 18px;
    }}
    QLabel#DashboardWelcome {{
        color: {text};
        font-family: {font_display};
        font-size: 27px;
        font-weight: 700;
        letter-spacing: -0.03em;
    }}
    QPushButton#DashboardStat {{
        background-color: {card};
        border: 1px solid {border_hair};
        border-radius: 14px;
        text-align: left;
    }}
    QPushButton#DashboardStat:hover {{
        background-color: {card_alt};
        border-color: {accent_dim};
    }}
    QLabel#DashboardStatLabel {{ color: {text_dim}; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }}
    QLabel#DashboardStatValue {{ color: {text}; font-family: {font_display}; font-size: 27px; font-weight: 700; }}
    QFrame#DashboardStudioPanel {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {panel_alt}, stop:1 {card});
        border: 1px solid {border_hair};
        border-radius: 16px;
    }}
    QPushButton#DashboardAction {{
        text-align: left;
        background-color: rgba({glow},0.08);
        border: 1px solid rgba({glow},0.21);
        border-radius: 10px;
        padding: 11px 12px;
        color: {text};
        font-weight: 600;
    }}
    QPushButton#DashboardAction:hover {{ background-color: rgba({glow},0.15); border-color: {accent_dim}; }}
    QFrame#DashboardTask {{ background-color: {panel}; border: 1px solid {border_hair}; border-radius: 9px; }}
    QLabel#DashboardTaskTitle {{ color: {text}; font-weight: 600; }}
    QLabel#DashboardTaskPercent {{ color: {accent_hover}; font-weight: 700; }}
    QFrame#DashboardEmpty {{ background-color: {panel}; border: 1px dashed {border}; border-radius: 10px; }}
    QLabel#DashboardEmptyTitle {{ color: {text}; font-family: {font_display}; font-size: 14px; font-weight: 700; }}
    QPushButton#DashboardActivity {{ background: transparent; border: none; border-radius: 9px; text-align: left; }}
    QPushButton#DashboardActivity:hover {{ background-color: {panel_alt}; }}
    QLabel#DashboardActivityTitle {{ color: {text}; font-size: 13px; font-weight: 600; }}
    QLabel#DashboardActivityArrow {{ color: {accent_hover}; font-size: 21px; }}

    QTabBar::tab {{
        background-color: {panel};
        color: {text_dim};
        border: 1px solid {border_hair};
        border-bottom: none;
        padding: 10px 14px;
        margin-right: 3px;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
    }}
    QTabBar::tab:selected {{ color: {text}; background-color: {panel_alt}; border-color: {border}; }}
    QTabBar::tab:hover:!selected {{ color: {text}; background-color: {card_alt}; }}
    QTabWidget::pane {{ border: 1px solid {border_hair}; border-radius: 10px; top: -1px; }}

    /* --- Cards / panels --- */
    QFrame#Card {{
        background-color: {card};
        border: 1px solid {border_hair};
        border-radius: 16px;
    }}
    QFrame#CardAlt {{
        background-color: {card_alt};
        border: 1px solid {border_hair};
        border-radius: 12px;
    }}
    QLabel#Eyebrow {{
        color: {accent_hover};
        font-family: {font_display};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 2.5px;
    }}
    QLabel#PageTitle {{
        color: {text};
        font-family: {font_display};
        font-size: 25px;
        font-weight: 700;
        letter-spacing: -0.02em;
    }}
    QLabel#PageSubtitle {{
        color: {text_dim};
        font-size: 13px;
    }}
    QLabel#WorkflowHint {{
        color: {accent_hover};
        font-size: 12px;
        font-weight: 600;
        padding: 9px 12px;
        background-color: rgba({glow},0.09);
        border: 1px solid rgba({glow},0.20);
        border-radius: 8px;
    }}
    QLabel#SectionHeader {{
        color: {text};
        font-family: {font_display};
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.4px;
    }}
    QLabel#Muted {{
        color: {text_dim};
    }}
    QLabel#Faint {{
        color: {text_faint};
        font-size: 11px;
    }}
    QLabel#FieldLabel {{
        color: {text_dim};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.4px;
    }}

    /* --- Inputs --- */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit {{
        background-color: {panel};
        border: 1px solid {border_hair};
        border-radius: 10px;
        padding: 10px 13px;
        color: {text};
        selection-background-color: {accent_dim};
        font-size: 13px;
        min-height: 22px;
    }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QTimeEdit:hover {{
        border: 1px solid {border};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus {{
        border: 1px solid {accent};
        background-color: {panel_alt};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {panel_alt};
        border: 1px solid {border};
        border-radius: 8px;
        selection-background-color: {accent_dim};
        color: {text};
        outline: none;
        padding: 4px;
    }}
    QTableWidget {{
        background-color: {panel};
        alternate-background-color: {panel_alt};
        color: {text};
        border: 1px solid {border_hair};
        border-radius: 10px;
        gridline-color: {border_soft};
        selection-background-color: rgba({glow},0.22);
        selection-color: {text};
        outline: none;
    }}
    QTableWidget::item {{
        padding: 8px;
        border-bottom: 1px solid {border_soft};
    }}
    QDialog#CardDialog {{
        background-color: {card};
        color: {text};
        border: 1px solid {border_hair};
        border-radius: 16px;
    }}
    QLabel#CardTitle {{
        color: {text};
        font-family: {font_display};
        font-size: 18px;
        font-weight: 700;
    }}
    QLabel#PreviewFrame {{
        background-color: {panel};
        border: 1px solid {border_hair};
        border-radius: 12px;
        color: {text_faint};
    }}
    QHeaderView::section {{
        background-color: {panel_alt};
        color: {text_dim};
        border: none;
        border-bottom: 1px solid {border};
        padding: 10px 12px;
        font-size: 11px;
        font-weight: 700;
    }}
    QCheckBox {{
        color: {text_dim};
        spacing: 9px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        background-color: {panel};
        border: 1px solid {border};
        border-radius: 4px;
    }}
    QCheckBox::indicator:checked {{
        background-color: {accent};
        border-color: {accent_hover};
    }}

    /* --- Buttons --- */
    QPushButton#PrimaryButton {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 {accent_hover}, stop:1 {accent_dim});
        color: #ffffff;
        border: 1px solid rgba(255,255,255,0.14);
        border-radius: 10px;
        padding: 10px 22px;
        font-weight: 600;
        font-size: 13px;
    }}
    QPushButton#PrimaryButton:hover {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 {accent_hover}, stop:1 {accent});
    }}
    QPushButton#PrimaryButton:pressed {{
        background: {accent_dim};
    }}
    QPushButton#PrimaryButton:disabled {{
        background: {border};
        color: {text_faint};
        border: 1px solid {border};
    }}
    QPushButton#GhostButton {{
        background-color: {panel_alt};
        color: {text_dim};
        border: 1px solid {border_hair};
        border-radius: 10px;
        padding: 9px 16px;
        font-weight: 500;
    }}
    QPushButton#GhostButton:hover {{
        color: {text};
        border: 1px solid {accent_dim};
        background-color: rgba({glow},0.10);
    }}
    QToolButton#AdvancedToggle {{
        background-color: {panel_alt};
        color: {text_dim};
        border: 1px solid {border_hair};
        border-radius: 9px;
        padding: 11px 13px;
        text-align: left;
        font-weight: 600;
    }}
    QToolButton#AdvancedToggle:hover, QToolButton#AdvancedToggle:checked {{
        color: {text};
        border-color: {accent_dim};
        background-color: rgba({glow},0.10);
    }}
    QPushButton#DangerGhostButton {{
        background-color: transparent;
        color: {danger};
        border: 1px solid {border_hair};
        border-radius: 8px;
        padding: 7px 14px;
        font-weight: 500;
    }}
    QPushButton#DangerGhostButton:hover {{
        border: 1px solid {danger};
        background-color: rgba(248,113,113,0.10);
    }}
    QPushButton#IconButton {{
        background-color: transparent;
        border: 1px solid {border_hair};
        border-radius: 8px;
        padding: 6px 12px;
        color: {text_dim};
        font-weight: 500;
    }}
    QPushButton#IconButton:hover {{
        color: {text};
        border: 1px solid {accent_dim};
        background-color: rgba({glow},0.08);
    }}

    /* --- Quality list --- */
    QFrame#QualityRow {{
        background-color: {panel};
        border: 1px solid {border_hair};
        border-radius: 10px;
    }}
    QFrame#QualityRow:hover {{
        border: 1px solid {border};
        background-color: {panel_alt};
    }}
    QFrame#QualityRow[selected="true"] {{
        border: 1px solid {accent};
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 rgba({glow},0.16), stop:1 rgba({glow},0.04));
    }}
    QLabel#QualityLabel {{
        color: {text};
        font-size: 13px;
        font-weight: 600;
    }}
    QLabel#QualitySub {{
        color: {text_faint};
        font-size: 11px;
    }}
    QLabel#RecommendedTag {{
        color: {accent_hover};
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 1px;
    }}

    /* --- Progress --- */
    QProgressBar {{
        background-color: {panel};
        border: none;
        border-radius: 5px;
        height: 8px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {accent}, stop:1 {accent_hover});
        border-radius: 5px;
    }}

    /* --- Scrollbars --- */
    QScrollArea {{ border: none; }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {border};
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {accent_dim}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ height: 0px; }}

    /* --- Status tags / badges --- */
    QLabel#StatusBadge {{
        border: 1px solid {border};
        border-radius: 5px;
        padding: 3px 9px;
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.5px;
        color: {text_dim};
        background-color: {panel_alt};
    }}
    QLabel#StatusBadge[state="completed"] {{
        color: {success};
        border-color: rgba(74,222,128,0.35);
        background-color: {success_dim};
    }}
    QLabel#StatusBadge[state="failed"] {{
        color: {danger};
        border-color: rgba(248,113,113,0.35);
        background-color: {danger_dim};
    }}
    QLabel#StatusBadge[state="active"] {{
        color: {accent_hover};
        border-color: rgba({glow},0.4);
        background-color: rgba({glow},0.10);
    }}

    QFrame#Divider {{
        background-color: {border_soft};
        max-height: 1px;
        min-height: 1px;
    }}

    QToolTip {{
        background-color: {panel_alt};
        color: {text};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 4px 8px;
    }}
    /* Keyboard focus remains visible on all shared controls. */
    QPushButton:focus, QToolButton:focus {{
        border: 2px solid {accent_hover};
    }}
    QCheckBox:focus {{ color: {text}; }}
    QCheckBox:focus::indicator {{ border: 2px solid {accent_hover}; }}
    QTableWidget:focus, QListWidget:focus {{ border: 1px solid {accent}; }}
    """.format(font_body=FONT_BODY, font_display=FONT_DISPLAY, **c)
