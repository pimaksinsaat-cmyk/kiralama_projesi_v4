from datetime import date, datetime, timedelta

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app.raporlama import raporlama_bp
from app.services.raporlama_services import RaporlamaService
from app.extensions import db


def _parse_date(value, fallback):
    if not value:
        return fallback
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_iso_date(value, fallback):
    if not value:
        return fallback
    try:
        normalized = value.replace('Z', '+00:00')
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return fallback


@raporlama_bp.route("/", methods=["GET"])
def index():
    today = date.today()
    default_start = date(today.year, 1, 1)

    try:
        start_date = _parse_date(request.args.get("start_date"), default_start)
        end_date = _parse_date(request.args.get("end_date"), today)

        if start_date > end_date:
            start_date, end_date = end_date, start_date
            flash("Tarih araligi ters secildigi icin otomatik duzeltildi.", "warning")

        sube_id = request.args.get("sube_id", type=int)
        calisma_yuksekligi = request.args.get("calisma_yuksekligi", type=int)
        projection_mode = request.args.get("projection_mode", default="yukseklik", type=str)
        machine_search = (request.args.get("machine_search", default="", type=str) or "").strip()
        machine_sube_id = request.args.get("machine_sube_id", type=int)
        machine_limit = request.args.get("machine_limit", default=50, type=int)
        active_tab = request.args.get("active_tab", default="genel", type=str)

        dashboard = RaporlamaService.build_dashboard(
            start_date=start_date,
            end_date=end_date,
            sube_id=sube_id,
            calisma_yuksekligi=calisma_yuksekligi,
            projection_mode=projection_mode,
            machine_search=machine_search,
            machine_sube_id=machine_sube_id,
            machine_limit=machine_limit,
        )
        dashboard["filters"]["active_tab"] = active_tab

        return render_template("raporlama/index.html", dashboard=dashboard)

    except ValueError:
        flash("Tarih formatini YYYY-AA-GG olarak seciniz.", "danger")
        dashboard = RaporlamaService.build_dashboard(
            start_date=default_start,
            end_date=today,
            sube_id=None,
            calisma_yuksekligi=None,
            projection_mode="yukseklik",
            machine_search="",
            machine_sube_id=None,
            machine_limit=50,
        )
        dashboard["filters"]["active_tab"] = "genel"
        return render_template("raporlama/index.html", dashboard=dashboard)


@raporlama_bp.route("/api", methods=["GET"])
def rapor_api():
    today = date.today()
    default_start = date(today.year, 1, 1)

    start_date = _parse_date(request.args.get("start_date"), default_start)
    end_date = _parse_date(request.args.get("end_date"), today)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    sube_id = request.args.get("sube_id", type=int)
    calisma_yuksekligi = request.args.get("calisma_yuksekligi", type=int)
    projection_mode = request.args.get("projection_mode", default="yukseklik", type=str)
    machine_search = (request.args.get("machine_search", default="", type=str) or "").strip()
    machine_sube_id = request.args.get("machine_sube_id", type=int)
    machine_limit = request.args.get("machine_limit", default=50, type=int)
    active_tab = request.args.get("active_tab", default="genel", type=str)

    dashboard = RaporlamaService.build_dashboard(
        start_date=start_date,
        end_date=end_date,
        sube_id=sube_id,
        calisma_yuksekligi=calisma_yuksekligi,
        projection_mode=projection_mode,
        machine_search=machine_search,
        machine_sube_id=machine_sube_id,
        machine_limit=machine_limit,
    )
    dashboard["filters"]["active_tab"] = active_tab

    # JSON uyumlulugu icin tarih alanlarini metne cevir.
    dashboard["filters"]["start_date"] = start_date.isoformat()
    dashboard["filters"]["end_date"] = end_date.isoformat()

    return jsonify(dashboard)
