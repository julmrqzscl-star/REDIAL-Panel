from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any, Iterable


TRUE_VALUES = {"1", "true", "yes", "y", "si", "sí", "x"}
FALSE_VALUES = {"0", "false", "no", "n", ""}
LINE_TYPES = {"mobile", "fixed", "unknown"}
ALIASES = {
    "phone": ("phone", "telefono", "teléfono", "numero", "número", "mobile", "celular"),
    "name": ("name", "nombre", "contacto"),
    "line_type": ("line_type", "tipo_linea", "tipo de linea", "tipo de línea", "tipo"),
    "line_type_source": ("line_type_source", "fuente_tipo_linea", "fuente tipo de linea", "fuente tipo de línea"),
    "line_type_checked_at": ("line_type_checked_at", "fecha_tipo_linea", "fecha tipo de linea", "fecha tipo de línea"),
    "carrier": ("carrier", "operador", "compania", "compañía"),
    "carrier_source": ("carrier_source", "fuente_operador", "fuente operador"),
    "carrier_checked_at": ("carrier_checked_at", "fecha_operador", "fecha operador"),
    "sms_consent": ("sms_consent", "consentimiento_sms", "consentimiento sms", "permiso_sms"),
    "sms_consent_at": ("sms_consent_at", "fecha_consentimiento_sms", "fecha permiso sms"),
    "sms_consent_source": ("sms_consent_source", "fuente_consentimiento_sms", "evidencia_sms"),
    "whatsapp_consent": ("whatsapp_consent", "consentimiento_whatsapp", "consentimiento whatsapp", "permiso_whatsapp"),
    "whatsapp_consent_at": ("whatsapp_consent_at", "fecha_consentimiento_whatsapp", "fecha permiso whatsapp"),
    "whatsapp_consent_source": ("whatsapp_consent_source", "fuente_consentimiento_whatsapp", "evidencia_whatsapp"),
}


def normalize_phone(value: Any, default_country: str = "52") -> str:
    """Normalize to digits with Mexico country code; never guesses line type."""
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10:
        digits = default_country + digits
    elif len(digits) == 12 and digits.startswith("52"):
        pass
    elif len(digits) == 13 and digits.startswith("521"):
        # Legacy Mexican mobile prefix; keep digits but strip the obsolete 1.
        digits = "52" + digits[3:]
    return digits


def validate_phone(value: Any) -> tuple[str, bool, str]:
    normalized = normalize_phone(value)
    if re.fullmatch(r"52\d{10}", normalized):
        return normalized, True, "Formato México válido (10 dígitos nacionales); actividad no verificada"
    return normalized, False, "Formato no reconocido; revisar manualmente"


def parse_bool(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return False


def clean_record(raw: dict[str, Any]) -> dict[str, Any]:
    lower = {str(k).strip().lower(): v for k, v in raw.items()}
    row: dict[str, Any] = {}
    for field, names in ALIASES.items():
        row[field] = next((lower[n] for n in names if n in lower), "")
    phone, valid, note = validate_phone(row["phone"])
    kind = str(row["line_type"] or "unknown").strip().lower()
    kind = {"movil": "mobile", "móvil": "mobile", "celular": "mobile", "fijo": "fixed"}.get(kind, kind)
    if kind not in LINE_TYPES:
        kind = "unknown"
    kind_source = str(row["line_type_source"] or "").strip()
    kind_checked_at = str(row["line_type_checked_at"] or "").strip()
    if kind != "unknown" and not (kind_source and kind_checked_at):
        kind = "unknown"
    carrier = str(row["carrier"] or "").strip()
    source = str(row["carrier_source"] or "").strip()
    checked_at = str(row["carrier_checked_at"] or "").strip()
    # Unsupported/unproven claims are preserved as notes, not presented as current verified data.
    carrier_verified = bool(carrier and source and checked_at)
    return {
        "phone": phone,
        "name": str(row["name"] or "").strip(),
        "format_valid": valid,
        "validation_note": note,
        "line_type": kind,
        "line_type_source": kind_source if kind != "unknown" else "",
        "line_type_checked_at": kind_checked_at if kind != "unknown" else "",
        "carrier": carrier if carrier_verified else "",
        "carrier_source": source if carrier_verified else "",
        "carrier_checked_at": checked_at if carrier_verified else "",
        "sms_consent": parse_bool(row["sms_consent"]),
        "sms_consent_at": str(row["sms_consent_at"] or "").strip(),
        "sms_consent_source": str(row["sms_consent_source"] or "").strip(),
        "whatsapp_consent": parse_bool(row["whatsapp_consent"]),
        "whatsapp_consent_at": str(row["whatsapp_consent_at"] or "").strip(),
        "whatsapp_consent_source": str(row["whatsapp_consent_source"] or "").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def import_csv_text(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not reader.fieldnames or not any(str(h).strip().lower() in ALIASES["phone"] for h in reader.fieldnames):
        raise ValueError("El CSV debe contener una columna phone/teléfono.")
    return [clean_record(row) for row in reader]


def eligible(record: dict[str, Any], channel: str) -> bool:
    if channel not in ("sms", "whatsapp"):
        raise ValueError("Canal inválido")
    return bool(
        record.get("format_valid")
        and record.get("line_type") == "mobile"
        and record.get("line_type_source")
        and record.get("line_type_checked_at")
        and record.get(f"{channel}_consent")
        and record.get(f"{channel}_consent_at")
        and record.get(f"{channel}_consent_source")
    )


def build_export(records: Iterable[dict[str, Any]], channel: str) -> str:
    fields = ["phone", "name", "line_type", "line_type_source", "line_type_checked_at", "consent_at", "consent_source"]
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for r in records:
        if eligible(r, channel):
            writer.writerow({
                "phone": r["phone"], "name": r["name"], "line_type": r["line_type"],
                "line_type_source": r["line_type_source"],
                "line_type_checked_at": r["line_type_checked_at"],
                "consent_at": r[f"{channel}_consent_at"],
                "consent_source": r[f"{channel}_consent_source"],
            })
    return out.getvalue()

