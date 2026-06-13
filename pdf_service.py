from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import io
from sms_service import get_month_name


def generate_payslip_pdf(employee, payroll):
    """Generate a PDF payslip for an employee and return bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15*mm,
        leftMargin=15*mm,
        topMargin=15*mm,
        bottomMargin=15*mm
    )

    styles = getSampleStyleSheet()
    elements = []

    # --- Header ---
    title_style = ParagraphStyle(
        'Title', parent=styles['Normal'],
        fontSize=18, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#1a237e'),
        alignment=TA_CENTER, spaceAfter=4
    )
    sub_style = ParagraphStyle(
        'Sub', parent=styles['Normal'],
        fontSize=10, alignment=TA_CENTER, spaceAfter=2
    )
    elements.append(Paragraph("SALARY SLIP", title_style))
    elements.append(Paragraph(
        f"{get_month_name(payroll.month)} {payroll.year}", sub_style
    ))
    elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1a237e')))
    elements.append(Spacer(1, 5*mm))

    # --- Employee Info ---
    dept_name = employee.dept.name if employee.dept else 'N/A'
    info_data = [
        ['Employee ID:', employee.emp_id, 'Name:', employee.name],
        ['Designation:', employee.designation or 'N/A', 'Department:', dept_name],
        ['Bank:', employee.bank_name or 'N/A', 'Account No:', employee.account_number or 'N/A'],
        ['PAN:', employee.pan_number or 'N/A', 'Month/Year:', f"{get_month_name(payroll.month)} {payroll.year}"],
    ]
    info_table = Table(info_data, colWidths=[35*mm, 55*mm, 35*mm, 55*mm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#1a237e')),
        ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor('#1a237e')),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#f5f5f5'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
        ('PADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 5*mm))

    # --- Attendance Summary ---
    att_style = ParagraphStyle('H2', parent=styles['Normal'],
                               fontSize=11, fontName='Helvetica-Bold',
                               textColor=colors.HexColor('#1a237e'), spaceAfter=3)
    elements.append(Paragraph("Attendance Summary", att_style))
    att_data = [
        ['Working Days', 'Days Present', 'Overtime Hours'],
        [str(payroll.working_days), f"{payroll.present_days:.1f}", f"{payroll.overtime_hours:.1f} hrs"],
    ]
    att_table = Table(att_data, colWidths=[60*mm, 60*mm, 60*mm])
    att_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#e8eaf6')]),
        ('PADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(att_table)
    elements.append(Spacer(1, 5*mm))

    # --- Earnings & Deductions ---
    elements.append(Paragraph("Earnings & Deductions", att_style))
    salary_data = [
        ['Earnings', 'Amount (Rs.)', 'Deductions', 'Amount (Rs.)'],
        ['Basic Salary', f"{payroll.basic_salary:.2f}", 'Provident Fund (PF)', f"{payroll.pf_deduction:.2f}"],
        ['HRA', f"{payroll.hra:.2f}", 'ESI', f"{payroll.esi_deduction:.2f}"],
        ['Overtime Pay', f"{payroll.overtime_pay:.2f}", 'Professional Tax (PT)', f"{payroll.pt_deduction:.2f}"],
        ['Other Allowances', f"{payroll.other_allowances:.2f}", 'Advance Deduction', f"{payroll.advance_deduction:.2f}"],
        ['', '', 'Other Deductions', f"{payroll.other_deductions:.2f}"],
        ['', '', '', ''],
        ['Gross Salary', f"{payroll.gross_salary:.2f}", 'Total Deductions', f"{payroll.total_deductions:.2f}"],
    ]
    sal_table = Table(salary_data, colWidths=[55*mm, 35*mm, 55*mm, 35*mm])
    sal_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f5f5f5')]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8eaf6')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
        ('PADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(sal_table)
    elements.append(Spacer(1, 5*mm))

    # --- Net Pay ---
    net_data = [['NET SALARY PAYABLE', f"Rs. {payroll.net_salary:.2f}"]]
    net_table = Table(net_data, colWidths=[120*mm, 60*mm])
    net_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1a237e')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(net_table)
    elements.append(Spacer(1, 10*mm))

    # --- Footer ---
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'],
                                  fontSize=8, textColor=colors.grey, alignment=TA_CENTER)
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
    elements.append(Spacer(1, 3*mm))
    elements.append(Paragraph(
        "This is a computer-generated payslip and does not require a signature.",
        footer_style
    ))

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()
