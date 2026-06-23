from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.invoice import Invoice
from app.models.transaction import Payment, Transaction


METHOD_LABELS = {
    "ESPECES": "Especes",
    "CHEQUE": "Cheque",
    "MOBILE_MONEY": "Mobile Money",
}

STATUS_LABELS = {
    "EMISE": "Emise",
    "EN_ATTENTE_CONFIRMATION_BANCAIRE": "En attente de confirmation bancaire",
    "CHEQUE_REJETE": "Cheque rejete",
}


def _safe(value: str | None, fallback: str = "-") -> str:
    cleaned = (value or "").strip()
    return cleaned or fallback


def _build_styles() -> dict[str, ParagraphStyle]:
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "InvoiceTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=16,
            textColor=colors.black,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "InvoiceSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.black,
        ),
        "label": ParagraphStyle(
            "InvoiceLabel",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=9,
            textColor=colors.black,
        ),
        "value": ParagraphStyle(
            "InvoiceValue",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.black,
        ),
        "section": ParagraphStyle(
            "InvoiceSection",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.black,
            spaceAfter=2,
        ),
        "note": ParagraphStyle(
            "InvoiceNote",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=9.5,
            textColor=colors.black,
        ),
    }


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)


def _payment_reference(payment: Payment | None, invoice: Invoice) -> str:
    if payment is None:
        return _safe(invoice.reference_snapshot)
    if payment.moyen_paiement == "CHEQUE":
        return _safe(payment.cheque_numero, _safe(invoice.reference_snapshot))
    return _safe(payment.reference_paiement, _safe(invoice.reference_snapshot))


def _payment_note(invoice: Invoice, payment: Payment | None) -> str:
    if invoice.mention_paiement:
        return invoice.mention_paiement
    if payment is None:
        return "-"
    if payment.moyen_paiement == "ESPECES":
        return "Paiement en especes confirme."
    if payment.moyen_paiement == "MOBILE_MONEY":
        return "Paiement Mobile Money confirme."
    return "Paiement par cheque."


def render_invoice_pdf(invoice: Invoice) -> bytes:
    transaction: Transaction = invoice.transaction
    visit = transaction.visit
    payment = transaction.latest_payment
    styles = _build_styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        pageCompression=0,
    )

    subtotal_fcfa = sum(line.montant_ligne_fcfa for line in transaction.lines)
    non_honore_fcfa = sum(line.montant_ligne_fcfa for line in transaction.lines if not line.payable)
    total_encaisse_fcfa = transaction.montant_encaisse_fcfa

    story = [
        _paragraph("Hopital Saint Jean", styles["title"]),
        _paragraph("CaisseTrace Sante 229", styles["subtitle"]),
        Spacer(1, 4 * mm),
    ]

    meta_table = Table(
        [
            [_paragraph("Facture", styles["label"]), _paragraph(invoice.numero_facture, styles["value"]), _paragraph("Dossier", styles["label"]), _paragraph(invoice.id_visite_snapshot, styles["value"])],
            [_paragraph("Date", styles["label"]), _paragraph(invoice.created_at.strftime("%d/%m/%Y %H:%M"), styles["value"]), _paragraph("Statut", styles["label"]), _paragraph(STATUS_LABELS.get(invoice.statut_document, invoice.statut_document), styles["value"])],
            [_paragraph("Caisse", styles["label"]), _paragraph(_safe(transaction.caisse.nom if transaction.caisse else None), styles["value"]), _paragraph("Caissier", styles["label"]), _paragraph(_safe(transaction.caissier.nom if transaction.caissier else None), styles["value"])],
            [_paragraph("Paiement", styles["label"]), _paragraph(METHOD_LABELS.get(invoice.moyen_paiement_snapshot, invoice.moyen_paiement_snapshot), styles["value"]), _paragraph("Reference", styles["label"]), _paragraph(_payment_reference(payment, invoice), styles["value"])],
        ],
        colWidths=[26 * mm, 59 * mm, 24 * mm, 63 * mm],
        hAlign="LEFT",
    )
    meta_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend([meta_table, Spacer(1, 4 * mm)])

    patient_rows = [
        [_paragraph("Patient", styles["label"]), _paragraph(invoice.patient_nom_snapshot, styles["value"])],
        [_paragraph("Telephone", styles["label"]), _paragraph(invoice.patient_tel_snapshot, styles["value"])],
        [_paragraph("Motif", styles["label"]), _paragraph(_safe(visit.motif_visite), styles["value"])],
        [_paragraph("Service", styles["label"]), _paragraph(_safe(visit.service_oriente), styles["value"])],
    ]
    patient_table = Table(patient_rows, colWidths=[28 * mm, 144 * mm], hAlign="LEFT")
    patient_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend([patient_table, Spacer(1, 4 * mm)])

    line_rows = [
        [
            _paragraph("Code", styles["label"]),
            _paragraph("Libelle", styles["label"]),
            _paragraph("Service", styles["label"]),
            _paragraph("Qte", styles["label"]),
            _paragraph("PU", styles["label"]),
            _paragraph("Montant", styles["label"]),
            _paragraph("Etat", styles["label"]),
        ]
    ]
    for line in transaction.lines:
        line_rows.append(
            [
                _paragraph(line.code_element_snapshot, styles["value"]),
                _paragraph(line.nom_snapshot, styles["value"]),
                _paragraph(line.service_snapshot, styles["value"]),
                _paragraph(str(line.quantite), styles["value"]),
                _paragraph(f"{line.prix_unitaire_fcfa:,} FCFA".replace(",", " "), styles["value"]),
                _paragraph(f"{line.montant_ligne_fcfa:,} FCFA".replace(",", " "), styles["value"]),
                _paragraph(
                    "Paye" if line.payable else f"Non honore - en attente de reglement ({_safe(line.motif_non_honore)})",
                    styles["value"],
                ),
            ]
        )

    lines_table = Table(
        line_rows,
        colWidths=[22 * mm, 56 * mm, 28 * mm, 12 * mm, 24 * mm, 26 * mm, 34 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    lines_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend([lines_table, Spacer(1, 4 * mm)])

    summary_rows = [
        [_paragraph("Sous-total", styles["label"]), _paragraph(f"{subtotal_fcfa:,} FCFA".replace(",", " "), styles["value"])],
        [_paragraph("Non honore", styles["label"]), _paragraph(f"{non_honore_fcfa:,} FCFA".replace(",", " "), styles["value"])],
        [_paragraph("Total encaisse", styles["label"]), _paragraph(f"{total_encaisse_fcfa:,} FCFA".replace(",", " "), styles["value"])],
        [_paragraph("Reference", styles["label"]), _paragraph(_payment_reference(payment, invoice), styles["value"])],
        [_paragraph("Mention paiement", styles["label"]), _paragraph(_payment_note(invoice, payment), styles["value"])],
    ]
    if invoice.statut_document == "EN_ATTENTE_CONFIRMATION_BANCAIRE":
        summary_rows.append(
            [_paragraph("Etat cheque", styles["label"]), _paragraph("Cheque en attente de confirmation bancaire.", styles["value"])]
        )
    if invoice.statut_document == "CHEQUE_REJETE":
        summary_rows.append(
            [_paragraph("Etat cheque", styles["label"]), _paragraph("Cheque rejete par la banque.", styles["value"])]
        )

    summary_table = Table(summary_rows, colWidths=[42 * mm, 130 * mm], hAlign="LEFT")
    summary_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend(
        [
            summary_table,
            Spacer(1, 3 * mm),
            _paragraph("Document genere automatiquement depuis l'encaissement reel.", styles["note"]),
        ]
    )

    doc.build(story)
    return buffer.getvalue()
