"""
Export Summary Dialog - Display detailed export completion summary.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QTextBrowser, QApplication
)
from PyQt5.QtCore import Qt

from ..exporters.xlsx_exporter import ExportSummary
from ..models.workspace_model import DataSource


class ExportSummaryDialog(QDialog):
    """Dialog displaying detailed export summary with color-coded status."""

    def __init__(self, summary: ExportSummary, parent=None):
        super().__init__(parent)
        self.summary = summary
        self.setWindowTitle("Export Complete")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog UI."""
        layout = QVBoxLayout(self)

        # Text browser for formatted summary
        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(False)
        self.text_browser.setHtml(self._format_summary_html())
        layout.addWidget(self.text_browser)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(self._copy_to_clipboard)
        button_layout.addWidget(copy_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _format_summary_html(self) -> str:
        """Generate HTML-formatted summary."""
        s = self.summary

        # Colors
        GREEN = "#28a745"
        YELLOW = "#ffc107"
        RED = "#dc3545"
        BLUE = "#0066cc"
        GRAY = "#6c757d"

        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 11pt; line-height: 1.6;">

        <p style="font-size: 12pt;">
        <span style="color: {GREEN}; font-size: 14pt;">&#10003;</span>
        <b>Exported {s.samples_processed} sample(s) to:</b><br>
        <span style="margin-left: 24px; font-family: monospace; font-size: 10pt;">{s.filepath}</span>
        </p>

        <h3 style="color: {BLUE}; margin-top: 16px;">Data Processed</h3>
        <p style="margin-left: 20px;">
        <span style="color: {GREEN};">&#10003;</span> {s.gates_exported} gate(s) exported<br>
        <span style="color: {GREEN};">&#10003;</span> {s.statistics.channels_analyzed} channel(s) analyzed<br>
        <span style="color: {GREEN};">&#10003;</span> {s.keywords_exported} keyword(s) exported
        </p>
        """

        # Compensation section
        html += f'<h3 style="color: {BLUE}; margin-top: 16px;">Compensation Applied</h3>\n'
        html += '<p style="margin-left: 20px;">\n'

        comp = s.compensation
        if comp.mode == DataSource.RAW:
            html += f'<span style="color: {GRAY};">&#8505;</span> Raw data mode - compensation not applied<br>\n'
        elif not comp.matrices_used:
            html += f'<span style="color: {YELLOW};">&#9888;</span> No compensation matrices assigned<br>\n'
        else:
            # Show each matrix with sample count
            for matrix_name, count in comp.matrices_used.items():
                spectral_note = ""
                # Check if this specific matrix has spectral samples
                # For simplicity, just note if any spectral samples exist
                html += f'<span style="color: {GREEN};">&#10003;</span> "{matrix_name}" &rarr; {count} sample(s){spectral_note}<br>\n'

            # Note spectral count if any
            if comp.spectral_samples > 0:
                html += f'<span style="color: {GRAY};">&#8505;</span> {comp.spectral_samples} sample(s) using spectral compensation<br>\n'

            # Show failures if any
            if comp.failed_samples > 0:
                html += f'<span style="color: {RED};">&#10007;</span> {comp.failed_samples} sample(s) failed compensation<br>\n'

        html += '</p>\n'

        # Statistics section
        html += f'<h3 style="color: {BLUE}; margin-top: 16px;">Statistics Generated</h3>\n'
        html += '<p style="margin-left: 20px;">\n'

        stat = s.statistics
        if stat.mfi_metrics:
            metrics_str = ", ".join(stat.mfi_metrics)
            html += f'<span style="color: {GREEN};">&#10003;</span> {len(stat.mfi_metrics)} MFI metric(s): {metrics_str}<br>\n'

            # Show calculation counts
            calc_formula = f"{stat.gates_exported} gates &times; {stat.channels_analyzed} channels &times; {s.samples_processed} samples"
            html += f'<span style="color: {GREEN};">&#10003;</span> {stat.total_mfi_calculations:,} MFI calculation(s) ({calc_formula})<br>\n'

        html += f'<span style="color: {GREEN};">&#10003;</span> {stat.frequency_calculations:,} frequency calculation(s) ({stat.gates_exported} gates &times; {s.samples_processed} samples)<br>\n'
        html += '</p>\n'

        # Sheets created section
        html += f'<h3 style="color: {BLUE}; margin-top: 16px;">Sheets Created ({len(s.sheets_created)})</h3>\n'
        html += '<p style="margin-left: 20px; font-family: monospace; font-size: 10pt;">\n'

        # Group sheets for better readability
        for i, sheet_name in enumerate(s.sheets_created):
            html += f"&bull; {sheet_name}<br>\n"

        html += '</p>\n'

        # Warnings section (only if warnings exist)
        if s.warnings:
            html += f'<h3 style="color: {YELLOW}; margin-top: 16px;">&#9888; Warnings ({len(s.warnings)})</h3>\n'
            html += '<p style="margin-left: 20px; font-size: 10pt;">\n'
            html += f'See <b>Warnings</b> sheet in the exported file for details.<br>\n'
            # Show first 2 warnings as preview
            for warning in s.warnings[:2]:
                # Escape HTML in warning text
                escaped_warning = warning.replace('<', '&lt;').replace('>', '&gt;')
                html += f'<span style="color: {GRAY};">&bull;</span> {escaped_warning}<br>\n'
            if len(s.warnings) > 2:
                html += f'<span style="color: {GRAY};">&bull; ... and {len(s.warnings) - 2} more</span><br>\n'
            html += '</p>\n'

        html += '</div>'
        return html

    def _copy_to_clipboard(self):
        """Copy plain text summary to clipboard."""
        s = self.summary

        # Build plain text version
        text = f"Export Complete\n"
        text += f"{'=' * 60}\n\n"
        text += f"Exported {s.samples_processed} sample(s) to:\n"
        text += f"  {s.filepath}\n\n"

        text += f"Data Processed\n"
        text += f"  {s.gates_exported} gate(s) exported\n"
        text += f"  {s.statistics.channels_analyzed} channel(s) analyzed\n"
        text += f"  {s.keywords_exported} keyword(s) exported\n\n"

        text += f"Compensation Applied\n"
        comp = s.compensation
        if comp.mode == DataSource.RAW:
            text += f"  Raw data mode - compensation not applied\n"
        elif comp.matrices_used:
            for matrix_name, count in comp.matrices_used.items():
                text += f'  "{matrix_name}" -> {count} sample(s)\n'
            if comp.spectral_samples > 0:
                text += f"  {comp.spectral_samples} sample(s) using spectral compensation\n"
            if comp.failed_samples > 0:
                text += f"  {comp.failed_samples} sample(s) failed compensation\n"
        else:
            text += f"  No compensation matrices assigned\n"
        text += "\n"

        text += f"Statistics Generated\n"
        stat = s.statistics
        if stat.mfi_metrics:
            metrics_str = ", ".join(stat.mfi_metrics)
            text += f"  {len(stat.mfi_metrics)} MFI metric(s): {metrics_str}\n"
            text += f"  {stat.total_mfi_calculations:,} MFI calculation(s)\n"
        text += f"  {stat.frequency_calculations:,} frequency calculation(s)\n\n"

        text += f"Sheets Created ({len(s.sheets_created)})\n"
        for sheet in s.sheets_created:
            text += f"  - {sheet}\n"

        if s.warnings:
            text += f"\nWarnings ({len(s.warnings)})\n"
            for warning in s.warnings[:5]:
                text += f"  - {warning}\n"
            if len(s.warnings) > 5:
                text += f"  - ... and {len(s.warnings) - 5} more\n"

        # Copy to clipboard
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
