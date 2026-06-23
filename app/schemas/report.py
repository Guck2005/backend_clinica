from datetime import date, datetime

from pydantic import BaseModel


class ReportTotals(BaseModel):
    encaisse_fcfa: int = 0
    especes_fcfa: int = 0
    cheques_fcfa: int = 0
    mobile_money_fcfa: int = 0
    visits_total: int = 0
    alerts_total: int = 0


class ReportSummaryRead(BaseModel):
    period: str
    anchor_date: date
    caisse_id: int | None
    consolidated: bool
    start_date: date
    end_date: date
    totals: ReportTotals
    conclusion: str


class PaymentBreakdownLine(BaseModel):
    moyen_paiement: str
    statut: str
    total_fcfa: int
    count: int


class PaymentBreakdownRead(BaseModel):
    period: str
    anchor_date: date
    caisse_id: int | None
    items: list[PaymentBreakdownLine]


class VisitJournalLine(BaseModel):
    id_visite: str
    patient_nom_complet: str
    patient_tel: str
    motif_visite: str
    service_oriente: str
    statut: str
    created_at: datetime
    agent_accueil_id: int


class VisitJournalRead(BaseModel):
    period: str
    anchor_date: date
    caisse_id: int | None
    items: list[VisitJournalLine]


class MobileMoneyAuditLine(BaseModel):
    id_visite: str
    transaction_id: int
    numero_facture: str | None
    provider_attempt_id: str | None
    provider_status: str | None
    reference_paiement: str | None
    montant_attendu_fcfa: int
    montant_provider_fcfa: int | None
    frais_provider_fcfa: int | None
    verdict: str
    observation: str
    created_at: datetime


class MobileMoneyAuditRead(BaseModel):
    period: str
    anchor_date: date
    caisse_id: int | None
    items: list[MobileMoneyAuditLine]


class AlertDetailedLine(BaseModel):
    code: str
    rule_name: str
    gravite: str
    status: str
    caisse_id: int | None
    impact_amount_fcfa: int | None
    constat: str
    perimetre: str
    ecarts_observes: str
    pieces_concernees: str
    conclusion: str
    recommandation: str
    created_at: datetime
    last_detected_at: datetime


class AlertDetailedReportRead(BaseModel):
    generated_at: datetime
    items: list[AlertDetailedLine]
    total: int

